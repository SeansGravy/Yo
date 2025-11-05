"""FastAPI application for the Yo Lite UI."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from importlib import util as import_util
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.datastructures import UploadFile

from yo.backends import BackendStatus, detect_backends
from yo.brain import IngestionError, MissingDependencyError, YoBrain
from yo.chat import ChatSessionStore
from yo.config import get_config, update_config_value
from yo.events import get_event_bus, publish_event
from yo.logging_utils import get_logger
from yo.metrics import summarize_since, record_metric, parse_since_window
from yo.analytics import (
    analytics_enabled,
    load_analytics,
    record_chat_interaction,
    record_ingest_event,
    summarize_usage,
)
from yo.telemetry import (
    build_telemetry_summary,
    compute_trend,
    load_dependency_history,
    load_test_history,
    load_test_summary,
    load_telemetry_summary,
)
from yo.release import (
    DEFAULT_MANIFEST_PATH,
    load_integrity_manifest,
    load_release_manifest,
    list_release_manifests,
    verify_integrity_manifest,
)
from yo.websocket import UpdateBroadcaster
from yo.optimizer import generate_recommendations, apply_recommendations


TEMPLATES_DIR = Path(__file__).parent / "templates"
JINJA_AVAILABLE = import_util.find_spec("jinja2") is not None
templates = Jinja2Templates(directory=str(TEMPLATES_DIR)) if JINJA_AVAILABLE else None


@lru_cache(maxsize=1)
def get_brain() -> YoBrain:
    """Create a cached YoBrain instance for reuse across requests."""

    return YoBrain()


logger = get_logger(__name__)

app = FastAPI(title="Yo Lite UI", version="0.4.0")


MULTIPART_AVAILABLE = import_util.find_spec("python_multipart") is not None

NAMESPACE_DOCUMENT_ALERT = 1000
NAMESPACE_CHUNK_ALERT = 5000
NAMESPACE_GROWTH_ALERT = 75.0
DEFAULT_DRIFT_WINDOW = timedelta(days=7)
DRIFT_WINDOW_LABEL = "7d"


class ChatRequest(BaseModel):
    namespace: str = "default"
    message: str
    session_id: str | None = None
    web: bool = False
    stream: bool = False


class ConfigUpdateRequest(BaseModel):
    key: str
    value: str
    namespace: str | None = None

class OptimizeApplyRequest(BaseModel):
    ids: list[str] | None = None
    auto_only: bool = True


event_bus = get_event_bus()


def _format_backend(status: BackendStatus) -> dict[str, Any]:
    return {
        "available": status.available,
        "detail": status.message,
        "version": status.version,
    }


async def _extract_uploads(request: Request) -> tuple[str, list[UploadFile]]:
    """Extract namespace and uploaded files from a multipart request."""

    if not MULTIPART_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Install python-multipart to enable browser uploads.",
        )

    form = await request.form()
    namespace = (form.get("namespace") or "default").strip() or "default"
    raw_files = form.getlist("files")
    uploads: list[UploadFile] = [
        file for file in raw_files if isinstance(file, UploadFile)
    ]

    if not uploads:
        raise HTTPException(status_code=400, detail="At least one file must be uploaded.")

    return namespace, uploads


def _build_success_response(
    *,
    namespace: str,
    files: list[dict[str, Any]],
    ingest: dict[str, Any] | None,
    duration: float,
) -> JSONResponse:
    summary = dict(ingest or {})
    summary.setdefault("namespace", namespace)
    summary.setdefault("documents_ingested", 0)
    summary.setdefault("chunks_ingested", 0)
    summary.setdefault("duration_seconds", round(duration, 3))

    record_metric("ingest", **summary)
    record_ingest_event(
        namespace=namespace,
        documents=summary["documents_ingested"],
        chunks=summary["chunks_ingested"],
        duration_seconds=summary["duration_seconds"],
    )

    payload: dict[str, Any] = {
        "status": "ok",
        "namespace": namespace,
        "timestamp": datetime.utcnow().isoformat(),
        "files": files,
        "ingest": summary,
    }
    return JSONResponse(content=payload)


def _build_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    namespace: str,
    files: list[dict[str, Any]],
    detail: str | None = None,
) -> JSONResponse:
    error_payload: dict[str, Any] = {
        "status": "error",
        "namespace": namespace,
        "timestamp": datetime.utcnow().isoformat(),
        "files": files,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if detail:
        error_payload["error"]["detail"] = detail
    error_payload["detail"] = message if status_code >= 400 else None
    return JSONResponse(status_code=status_code, content=error_payload)


def _collect_release_entries() -> list[dict[str, Any]]:
    releases: list[dict[str, Any]] = []
    for manifest in list_release_manifests():
        manifest_path = Path(manifest.get("manifest_path", DEFAULT_MANIFEST_PATH))
        verify_result = verify_integrity_manifest(manifest_path)
        status = "verified" if verify_result.get("success") else "failed"
        status_reason = "; ".join(verify_result.get("errors", [])) if verify_result.get("errors") else ""
        releases.append(
            {
                "version": manifest.get("version"),
                "timestamp": manifest.get("timestamp"),
                "health": manifest.get("health"),
                "bundle": manifest.get("release_bundle"),
                "signature": manifest.get("bundle_signature"),
                "manifest": manifest.get("manifest_path"),
                "status": status,
                "status_reason": status_reason,
            }
        )
    releases.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
    return releases


@app.get("/healthz", response_class=JSONResponse)
def healthcheck() -> dict[str, Any]:
    """Simple readiness probe for the Lite UI."""

    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/ui", response_class=HTMLResponse)
def render_ui(request: Request) -> HTMLResponse:
    """Render the Lite UI dashboard."""

    if templates is None:
        html = (TEMPLATES_DIR / "ui.html").read_text(encoding="utf-8")
        html = html.replace("{{ app_version }}", app.version)
        return HTMLResponse(content=html)

    context = {"request": request, "app_version": app.version}
    return templates.TemplateResponse("ui.html", context)


@app.get("/chat", response_class=HTMLResponse)
def render_chat(request: Request) -> HTMLResponse:
    if templates is None:
        html = (TEMPLATES_DIR / "chat.html").read_text(encoding="utf-8")
        html = html.replace("{{ app_version }}", app.version)
        return HTMLResponse(content=html)
    return templates.TemplateResponse("chat.html", {"request": request, "app_version": app.version})


@app.get("/config", response_class=HTMLResponse)
def render_config_editor(request: Request) -> HTMLResponse:
    if templates is None:
        html = (TEMPLATES_DIR / "config.html").read_text(encoding="utf-8")
        html = html.replace("{{ app_version }}", app.version)
        return HTMLResponse(content=html)
    return templates.TemplateResponse("config.html", {"request": request, "app_version": app.version})


@app.get("/api/docs", include_in_schema=False)
def api_docs_redirect() -> RedirectResponse:
    """Expose OpenAPI docs under /api/docs."""

    return RedirectResponse(url="/docs")


def build_status_payload() -> dict[str, Any]:
    backends = detect_backends()
    backend_info = {
        "milvus": _format_backend(backends.milvus),
        "ollama": {
            "python": _format_backend(backends.ollama_python),
            "cli": _format_backend(backends.ollama_cli),
            "ready": backends.ollama_python.available and backends.ollama_cli.available,
        },
    }

    namespaces: list[str] = []
    activity: dict[str, dict[str, Any]] = {}
    warning: str | None = None

    brain_available = True
    try:
        brain = get_brain()
    except Exception as exc:  # pragma: no cover - backend initialization failure
        warning = str(exc)
        brain_available = False
    else:
        try:
            namespaces = brain.ns_list(silent=True)
            activity = brain.namespace_activity()
        except Exception as exc:  # pragma: no cover - backend query failure
            warning = str(exc)
            brain_available = False

    telemetry_summary = load_telemetry_summary() or build_telemetry_summary()
    test_summary = load_test_summary()

    drift_activity: dict[str, dict[str, Any]] = {}
    if brain_available:
        try:
            drift_activity = brain.namespace_drift(DEFAULT_DRIFT_WINDOW)
        except Exception:  # pragma: no cover - defensive guard
            drift_activity = {}

    namespace_rows: list[dict[str, Any]] = []
    for name in namespaces:
        entry = activity.get(name, {})
        drift_entry = drift_activity.get(name, {})
        documents = int(entry.get("documents", 0) or 0)
        chunks = int(entry.get("chunks", 0) or 0)
        growth_value = float(
            drift_entry.get("growth_percent", entry.get("growth_percent", 0.0)) or 0.0
        )
        alerts: list[str] = []
        if documents > NAMESPACE_DOCUMENT_ALERT:
            alerts.append(f"Document count {documents} exceeds {NAMESPACE_DOCUMENT_ALERT}")
        if chunks > NAMESPACE_CHUNK_ALERT:
            alerts.append(f"Chunk count {chunks} exceeds {NAMESPACE_CHUNK_ALERT}")
        if growth_value > NAMESPACE_GROWTH_ALERT:
            alerts.append(f"Growth {growth_value:.1f}% exceeds threshold")

        namespace_rows.append(
            {
                "name": name,
                "last_ingested": entry.get("last_ingested"),
                "documents": documents,
                "documents_delta": entry.get("documents_delta"),
                "chunks": chunks,
                "chunks_delta": entry.get("chunks_delta"),
                "records": entry.get("records"),
                "growth_percent": growth_value,
                "ingest_runs": entry.get("ingest_runs"),
                "drift": {
                    "documents_added": drift_entry.get("documents_added"),
                    "chunks_added": drift_entry.get("chunks_added"),
                    "ingests": drift_entry.get("ingests"),
                },
                "last_verify_status": (test_summary or {}).get("status"),
                "alerts": alerts,
            }
        )

    verification_info: dict[str, Any] = {}
    ledger_path = Path("data/logs/verification_ledger.jsonl")
    signature_path = Path("data/logs/checksums/artifact_hashes.sig")
    if ledger_path.exists():
        try:
            ledger_lines = [line for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if ledger_lines:
                latest = json.loads(ledger_lines[-1])
                verification_info = {
                    "version": latest.get("version"),
                    "commit": latest.get("commit"),
                    "health": latest.get("health"),
                    "timestamp": latest.get("timestamp"),
                    "checksum_file": latest.get("checksum_file"),
                    "signature": str(signature_path) if signature_path.exists() else latest.get("signature"),
                }
        except json.JSONDecodeError:
            verification_info = {}

    manifest_data = load_integrity_manifest()
    releases_list = _collect_release_entries()
    release_info: dict[str, Any] = {}
    if manifest_data:
        release_info = {
            "version": manifest_data.get("version"),
            "bundle": manifest_data.get("release_bundle"),
            "bundle_signature": manifest_data.get("bundle_signature"),
            "bundle_checksum": manifest_data.get("bundle_checksum"),
            "manifest": str(DEFAULT_MANIFEST_PATH),
            "timestamp": manifest_data.get("timestamp"),
            "health": manifest_data.get("health"),
        }

    ingestion_enabled = (
        brain_available
        and backends.milvus.available
        and backends.ollama_python.available
        and backends.ollama_cli.available
        and MULTIPART_AVAILABLE
    )
    reasons: list[str] = []
    if not backends.milvus.available:
        reasons.append(backends.milvus.message)
    if not backends.ollama_python.available:
        reasons.append(backends.ollama_python.message)
    if not backends.ollama_cli.available:
        reasons.append(backends.ollama_cli.message)
    if not MULTIPART_AVAILABLE:
        reasons.append("Install python-multipart to enable browser uploads.")
    if warning:
        reasons.append(warning)

    metrics_snapshot = summarize_since("7d")
    analytics_snapshot = summarize_usage(load_analytics())

    payload: dict[str, Any] = {
        "backends": backend_info,
        "namespaces": namespace_rows,
        "ingestion": {
            "enabled": ingestion_enabled,
            "reason": "\n".join(dict.fromkeys(reasons)) if not ingestion_enabled and reasons else None,
        },
        "health": {
            "score": telemetry_summary.get("health_score"),
            "pass_rate": telemetry_summary.get("pass_rate_mean"),
            "latest_status": (test_summary or {}).get("status"),
            "timestamp": (test_summary or {}).get("timestamp"),
        },
        "warning": warning,
        "drift_window": DRIFT_WINDOW_LABEL,
        "timestamp": datetime.utcnow().isoformat(),
        "verification": verification_info,
        "release": release_info,
        "releases": releases_list,
        "metrics": metrics_snapshot,
        "analytics": analytics_snapshot,
    }
    payload["optimizer"] = {
        "recommendations": generate_recommendations()[:3],
    }
    return payload


@app.get("/api/status", response_class=JSONResponse)
def api_status() -> JSONResponse:
    """Return backend availability and namespace insights for the Lite UI."""

    return JSONResponse(content=build_status_payload())


@app.get("/api/metrics", response_class=JSONResponse)
def api_metrics(since: str | None = None) -> JSONResponse:
    try:
        summary = summarize_since(since)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(content=summary)


@app.get("/api/analytics", response_class=JSONResponse)
def api_analytics_endpoint(since: str | None = None) -> JSONResponse:
    try:
        window = parse_since_window(since) if since else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    entries = load_analytics(since=window)
    summary = summarize_usage(entries)
    summary["window"] = since or "all"
    summary["enabled"] = analytics_enabled()
    return JSONResponse(content=summary)


@app.get("/api/optimize", response_class=JSONResponse)
def api_optimize() -> JSONResponse:
    recommendations = generate_recommendations()
    return JSONResponse(content={"recommendations": recommendations})


@app.post("/api/optimize/apply", response_class=JSONResponse)
async def api_optimize_apply(payload: OptimizeApplyRequest) -> JSONResponse:
    recommendations = generate_recommendations()
    if payload.ids:
        recommendations = [rec for rec in recommendations if rec.get("id") in payload.ids]
    applied = apply_recommendations(recommendations, auto_only=payload.auto_only)
    return JSONResponse(content={"applied": applied, "requested": payload.ids or []})


@app.websocket("/ws/updates")
async def websocket_updates(websocket: WebSocket) -> None:
    await websocket.accept()
    await broadcaster.connect(websocket)
    try:
        await websocket.send_text(json.dumps(build_status_payload()))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await broadcaster.disconnect(websocket)
    except Exception:  # pragma: no cover - network failure path
        await broadcaster.disconnect(websocket)


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket) -> None:
    await websocket.accept()
    queue = await event_bus.subscribe()
    try:
        while True:
            event = await queue.get()
            await websocket.send_text(json.dumps(event))
    except WebSocketDisconnect:
        await event_bus.unsubscribe(queue)
    except Exception:  # pragma: no cover
        await event_bus.unsubscribe(queue)


@app.websocket("/ws/chat/{session_id}")
async def websocket_chat_stream(session_id: str, websocket: WebSocket) -> None:
    await websocket.accept()
    queue = await event_bus.subscribe()
    try:
        while True:
            event = await queue.get()
            if event.get("session_id") != session_id:
                continue
            if event.get("type") not in {"chat_token", "chat_complete", "chat_message", "chat_started"}:
                continue
            await websocket.send_text(json.dumps(event))
    except WebSocketDisconnect:
        await event_bus.unsubscribe(queue)
    except Exception:  # pragma: no cover
        await event_bus.unsubscribe(queue)


def build_config_payload() -> dict[str, Any]:
    cfg = get_config()
    overrides = {name: value.as_dict() for name, value in cfg.namespace_overrides.items()}
    payload: dict[str, Any] = {
        "namespace": cfg.namespace,
        "model": cfg.model_spec,
        "embed_model": cfg.embed_model_spec,
        "db_uri": cfg.db_uri,
        "data_dir": str(cfg.data_dir),
        "namespace_overrides": overrides,
        "sources": cfg.sources,
    }
    return payload


@app.get("/api/config", response_class=JSONResponse)
def api_config() -> JSONResponse:
    return JSONResponse(content=build_config_payload())


@app.post("/api/config", response_class=JSONResponse)
async def api_config_update(payload: ConfigUpdateRequest) -> JSONResponse:
    namespace = (payload.namespace or "").strip() or None
    data_dir = None
    try:
        brain = get_brain()
        data_dir = brain.data_dir
    except Exception:  # pragma: no cover - brain initialisation failure
        data_dir = None

    try:
        update_config_value(payload.key, payload.value, namespace=namespace, data_dir=data_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await broadcaster.trigger()
    config_snapshot = build_config_payload()
    publish_event(
        "config_updated",
        {
            "key": payload.key,
            "namespace": payload.namespace,
            "value": payload.value,
        },
    )
    return JSONResponse(content={"status": "ok", "config": config_snapshot})


@app.post("/api/chat", response_class=JSONResponse)
async def api_chat(payload: ChatRequest) -> JSONResponse:
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    namespace = payload.namespace.strip() or get_config().namespace
    try:
        brain = get_brain()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"YoBrain unavailable: {exc}") from exc

    stream_mode = os.environ.get("YO_CHAT_STREAM_FALLBACK", "auto").lower()
    stream_requested = payload.stream
    if stream_mode == "force":
        stream_requested = False
    elif stream_mode == "off":
        stream_requested = True

    started = time.perf_counter()
    try:
        if stream_requested:
            session_id, reply, history, metadata = chat_store.stream(
                brain=brain,
                namespace=namespace,
                message=message,
                session_id=payload.session_id,
                web=payload.web,
            )
        else:
            session_id, reply, history, metadata = chat_store.send(
                brain=brain,
                namespace=namespace,
                message=message,
                session_id=payload.session_id,
                web=payload.web,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    latency = time.perf_counter() - started
    reply_text = reply or ""

    record_metric(
        "chat",
        namespace=namespace,
        latency_seconds=round(latency, 3),
        tokens=len(reply_text),
        stream=stream_requested,
        history_length=len(history),
    )
    record_chat_interaction(
        session_id,
        namespace=namespace,
        latency_seconds=latency,
        tokens=len(reply_text),
        stream=stream_requested,
        history_length=len(history),
    )

    response_payload = {
        "session_id": session_id,
        "reply": reply,
        "namespace": namespace,
        "history": history,
        "context": metadata.get("context"),
        "citations": metadata.get("citations", []),
        "stream": stream_requested,
    }
    return JSONResponse(content=response_payload)


chat_store = ChatSessionStore()
broadcaster = UpdateBroadcaster(
    [
        Path("data/logs"),
        Path("data/namespace_meta.json"),
        Path(".env"),
    ],
    build_status_payload,
    event_type="status_update",
)


@app.on_event("startup")
async def _startup_events() -> None:
    await broadcaster.start()


@app.on_event("shutdown")
async def _shutdown_events() -> None:
    await broadcaster.stop()


@app.get("/api/releases", response_class=JSONResponse)
def api_releases() -> JSONResponse:
    """List packaged releases."""

    releases = _collect_release_entries()
    return JSONResponse(content={"releases": releases})


@app.get("/api/release/latest", response_class=JSONResponse)
def api_release_latest() -> JSONResponse:
    """Return metadata for the latest release."""

    releases = _collect_release_entries()
    if not releases:
        raise HTTPException(status_code=404, detail="No releases packaged yet.")
    return JSONResponse(content={"release": releases[0]})


@app.get("/api/release/{version}", response_class=JSONResponse)
def api_release_version(version: str) -> JSONResponse:
    """Return release metadata for a requested version."""

    manifest = load_release_manifest(version)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"No release data for version {version}.")
    return JSONResponse(content={"manifest": manifest})


@app.get("/api/release/{version}/verify", response_class=JSONResponse)
def api_release_version_verify(version: str) -> JSONResponse:
    """Verify release integrity for a given version."""

    manifest = load_release_manifest(version)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"No release data for version {version}.")
    manifest_path = Path(manifest.get("manifest_path", DEFAULT_MANIFEST_PATH))
    verification = verify_integrity_manifest(manifest_path)
    artifact_sig = verification.get("artifact_signature") or {}
    bundle_sig = verification.get("bundle_signature") or {}
    payload = {
        "version": version,
        "success": verification.get("success"),
        "signature_valid": bool(artifact_sig.get("success")) if artifact_sig else verification.get("success"),
        "bundle_signature_valid": bool(bundle_sig.get("success")) if bundle_sig else None,
        "checksum_match": verification.get("checksum_valid"),
        "errors": verification.get("errors", []),
        "manifest_path": str(manifest_path),
    }
    return JSONResponse(content=payload)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(_: Request) -> HTMLResponse:
    summary = load_test_summary()
    history = load_test_history()
    dependencies = load_dependency_history(limit=5)
    trend = compute_trend(history, days=7)
    telemetry_summary = load_telemetry_summary() or build_telemetry_summary()
    release_entries = _collect_release_entries()
    latest_release = release_entries[0] if release_entries else None
    ledger_entry: dict[str, Any] | None = None
    signature_path = Path("data/logs/checksums/artifact_hashes.sig")
    ledger_path = Path("data/logs/verification_ledger.jsonl")
    if ledger_path.exists():
        try:
            ledger_lines = [line for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if ledger_lines:
                ledger_entry = json.loads(ledger_lines[-1])
        except json.JSONDecodeError:
            ledger_entry = None

    status_line = "Unknown"
    if summary:
        status_line = (
            f"{summary.get('status', 'unknown')} — {summary.get('tests_passed', 0)}/{summary.get('tests_total', 0)} passed"
        )
        if summary.get("duration_seconds") is not None:
            status_line += f" in {float(summary['duration_seconds']):.2f}s"

    dependency_lines = "".join(
        f"<li>{event.get('timestamp')}: {event.get('action')} ({', '.join(event.get('packages', []))})</li>"
        for event in dependencies
    ) or "<li>No recent dependency events.</li>"

    trend_rows = "".join(
        "<tr><td>{ts}</td><td>{status}</td><td>{fail}</td><td>{duration}</td><td>{rate}</td></tr>".format(
            ts=entry.get("timestamp", ""),
            status=entry.get("status", ""),
            fail=entry.get("tests_failed", 0),
            duration=("{}s".format(round(float(entry.get("duration_seconds")), 2)) if entry.get("duration_seconds") is not None else "n/a"),
            rate=("{}%".format(round(float(entry.get("pass_rate_percent")), 1)) if entry.get("pass_rate_percent") is not None else "n/a"),
        )
        for entry in trend
    ) or "<tr><td colspan='5'>No history available.</td></tr>"

    try:
        brain = get_brain()
        namespace_activity = brain.namespace_activity()
        namespace_drift = brain.namespace_drift(DEFAULT_DRIFT_WINDOW)
        namespace_rows = []
        for name, details in namespace_activity.items():
            drift_entry = namespace_drift.get(name, {})
            documents = details.get("documents", 0)
            chunks = details.get("chunks", 0)
            growth_value = drift_entry.get("growth_percent", details.get("growth_percent", 0.0))
            alerts = []
            if isinstance(documents, (int, float)) and documents > NAMESPACE_DOCUMENT_ALERT:
                alerts.append(f"Documents {documents} > {NAMESPACE_DOCUMENT_ALERT}")
            if isinstance(chunks, (int, float)) and chunks > NAMESPACE_CHUNK_ALERT:
                alerts.append(f"Chunks {chunks} > {NAMESPACE_CHUNK_ALERT}")
            if isinstance(growth_value, (int, float)) and growth_value > NAMESPACE_GROWTH_ALERT:
                alerts.append(f"Growth {growth_value:.1f}% > {NAMESPACE_GROWTH_ALERT}")
            namespace_rows.append(
                "<tr><td>{name}</td><td>{docs}</td><td>{delta_docs}</td><td>{chunks}</td>"
                "<td>{delta_chunks}</td><td>{growth}</td><td>{ingests}</td><td>{alerts}</td></tr>".format(
                    name=name,
                    docs=details.get("documents", 0),
                    delta_docs=details.get("documents_delta", 0),
                    chunks=details.get("chunks", 0),
                    delta_chunks=details.get("chunks_delta", 0),
                    growth=f"{growth_value:.1f}%" if isinstance(growth_value, (int, float)) else "—",
                    ingests=details.get("ingest_runs", 0),
                    alerts=", ".join(alerts) if alerts else "—",
                )
            )
        namespace_table = "".join(namespace_rows) or "<tr><td colspan='8'>No namespaces recorded.</td></tr>"
    except Exception as exc:  # pragma: no cover - defensive guard for dashboard
        namespace_table = f"<tr><td colspan='8'>Error retrieving namespaces: {exc}</td></tr>"

    telemetry_block = ""
    if telemetry_summary:
        mean_rate = telemetry_summary.get("pass_rate_mean")
        volatility = telemetry_summary.get("pass_rate_volatility")
        duration_avg = telemetry_summary.get("duration_average")
        mean_rate_display = f"{mean_rate * 100:.1f}%" if isinstance(mean_rate, (int, float)) else "n/a"
        volatility_display = f"{volatility:.3f}" if isinstance(volatility, (int, float)) else "n/a"
        duration_display = f"{duration_avg:.2f}s" if isinstance(duration_avg, (int, float)) else "n/a"
        recurring = telemetry_summary.get("recurring_errors") or []
        recurring_block = "".join(
            f"<li>{issue['message']} ({issue['count']}x)</li>" for issue in recurring
        ) or "<li>No recurring issues detected.</li>"
        telemetry_block = f"""
        <section>
          <h2>Telemetry Insights</h2>
          <ul>
            <li>Average pass rate: {mean_rate_display}</li>
            <li>Pass-rate volatility: {volatility_display}</li>
            <li>Average runtime: {duration_display}</li>
          </ul>
          <h3>Top recurring issues</h3>
          <ul>{recurring_block}</ul>
        </section>
        """

    health_score = telemetry_summary.get("health_score") if telemetry_summary else None
    health_section = f"<section><h2>Health Overview</h2><ul><li>Health score: {health_score if health_score is not None else 'n/a'}</li><li>Drift window: {DRIFT_WINDOW_LABEL}</li></ul></section>"

    if ledger_entry:
        signature_display = str(signature_path) if signature_path.exists() else ledger_entry.get("signature", "n/a")
        verification_block = f"""
        <section>
          <h2>Signed Verification</h2>
          <ul>
            <li>Version: {ledger_entry.get('version', 'unknown')}</li>
            <li>Commit: {ledger_entry.get('commit', 'unknown')}</li>
            <li>Health: {ledger_entry.get('health', 'n/a')}</li>
            <li>Checksum: {ledger_entry.get('checksum_file', 'n/a')}</li>
            <li>Signature: {signature_display}</li>
          </ul>
        </section>
        """
    else:
        verification_block = """
        <section>
          <h2>Signed Verification</h2>
          <p>No signed verification recorded yet.</p>
        </section>
        """

    if release_entries:
        def _badge(entry: dict[str, Any]) -> str:
            status = entry.get("status")
            if status == "verified":
                return "🟢 Verified"
            if status == "failed":
                return "🔴 Failed"
            return "🟡 Pending"

        release_rows = "".join(
            "<tr><td>{version}</td><td>{health}</td><td>{timestamp}</td><td>{badge}</td><td>{bundle}</td></tr>".format(
                version=entry.get("version", "unknown"),
                health=entry.get("health", "n/a"),
                timestamp=entry.get("timestamp", "unknown"),
                badge=_badge(entry),
                bundle=entry.get("bundle", "n/a"),
            )
            for entry in release_entries
        )
        release_block = f"""
        <section>
          <h2>Releases</h2>
          <table>
            <thead><tr><th>Version</th><th>Health</th><th>Timestamp</th><th>Status</th><th>Bundle</th></tr></thead>
            <tbody>{release_rows}</tbody>
          </table>
        </section>
        """
    else:
        release_block = """
        <section>
          <h2>Releases</h2>
          <p>No release bundle packaged yet. Run <code>yo package release</code> after verification.</p>
        </section>
        """

    html = f"""
    <html>
      <head>
        <title>Yo Dashboard</title>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 2rem; }}
          h2 {{ border-bottom: 1px solid #ddd; padding-bottom: 0.3rem; }}
          table {{ border-collapse: collapse; width: 100%; margin-top: 0.5rem; }}
          th, td {{ border: 1px solid #ddd; padding: 0.5rem; text-align: left; }}
          th {{ background: #f5f5f5; }}
        </style>
      </head>
      <body>
        <h1>Yo Developer Dashboard</h1>
        <section>
          <h2>Latest Verification</h2>
          <p>{status_line}</p>
        </section>
        {health_section}
        {verification_block}
        {release_block}
        <section>
          <h2>Recent Trend (last {len(trend)} runs)</h2>
          <table>
            <thead><tr><th>Timestamp</th><th>Status</th><th>Failures</th><th>Duration</th><th>Pass Rate</th></tr></thead>
            <tbody>{trend_rows}</tbody>
          </table>
        </section>
        <section>
          <h2>Dependency Events</h2>
          <ul>{dependency_lines}</ul>
        </section>
        {telemetry_block}
        <section>
          <h2>Namespace Activity</h2>
          <table>
            <thead><tr><th>Namespace</th><th>Documents</th><th>Δ Docs</th><th>Chunks</th><th>Δ Chunks</th><th>Growth</th><th>Ingests</th><th>Alerts</th></tr></thead>
            <tbody>{namespace_table}</tbody>
          </table>
        </section>
      </body>
    </html>
    """

    return HTMLResponse(content=html)


@app.post("/api/ingest", response_class=JSONResponse)
async def api_ingest(request: Request) -> JSONResponse:
    """Handle document uploads from the Lite UI and trigger ingestion."""

    backends = detect_backends()
    missing_reasons: list[str] = []
    if not backends.milvus.available:
        missing_reasons.append(backends.milvus.message)
    if not backends.ollama_python.available:
        missing_reasons.append(backends.ollama_python.message)
    if not backends.ollama_cli.available:
        missing_reasons.append(backends.ollama_cli.message)

    if missing_reasons:
        detail = "\n".join(dict.fromkeys(missing_reasons))
        message = "Ingestion requires Milvus Lite and the Ollama runtime to be installed."
        logger.warning("API ingest rejected — backends unavailable: %s", detail)
        return _build_error_response(
            status_code=503,
            code="backend_unavailable",
            message=message,
            namespace="default",
            files=[],
            detail=detail,
        )

    namespace = "default"
    try:
        namespace, uploads = await _extract_uploads(request)
    except HTTPException as exc:
        logger.warning(
            "API ingest rejected (status=%s): %s",
            exc.status_code,
            exc.detail,
        )
        return _build_error_response(
            status_code=exc.status_code,
            code="invalid_request",
            message=str(exc.detail),
            namespace=namespace,
            files=[],
        )

    try:
        brain = get_brain()
    except Exception as exc:
        logger.exception("API ingest aborted — YoBrain unavailable.")
        return _build_error_response(
            status_code=503,
            code="brain_unavailable",
            message="YoBrain is unavailable. Retry once dependencies are healthy.",
            namespace=namespace,
            files=[],
            detail=str(exc),
        )

    file_summaries: list[dict[str, Any]] = []
    written_paths: list[Path] = []
    total_bytes = 0
    start = time.perf_counter()
    result: dict[str, Any] | None = None

    with TemporaryDirectory() as tmpdir:
        temp_dir = Path(tmpdir)
        for upload in uploads:
            contents = await upload.read()
            content_type = getattr(upload, "content_type", None) or "application/octet-stream"
            await upload.close()
            if contents is None:
                size = 0
            else:
                size = len(contents)
            total_bytes += size
            if contents is None:
                continue
            filename = Path(upload.filename or "upload").name or "upload"
            destination = temp_dir / filename
            counter = 1
            while destination.exists():
                destination = temp_dir / f"{destination.stem}_{counter}{destination.suffix}"
                counter += 1
            destination.write_bytes(contents)
            written_paths.append(destination)
            file_summaries.append(
                {
                    "name": destination.name,
                    "size": size,
                    "content_type": content_type,
                }
            )

        if not written_paths:
            logger.warning(
                "API ingest aborted — uploaded files were empty (namespace=%s)",
                namespace,
            )
            return _build_error_response(
                status_code=400,
                code="empty_upload",
                message="Uploaded files were empty.",
                namespace=namespace,
                files=file_summaries,
            )

        if len(written_paths) == 1:
            source = str(written_paths[0])
        else:
            source = str(temp_dir)

        logger.info(
            "API ingest executing YoBrain pipeline (namespace=%s, files=%s, bytes=%s)",
            namespace,
            len(file_summaries),
            total_bytes,
        )

        try:
            result = brain.ingest(source, namespace=namespace)
        except MissingDependencyError as exc:
            logger.warning(
                "API ingest failed — missing dependency (namespace=%s): %s",
                namespace,
                exc,
            )
            return _build_error_response(
                status_code=400,
                code="missing_dependency",
                message=str(exc),
                namespace=namespace,
                files=file_summaries,
            )
        except IngestionError as exc:
            logger.warning(
                "API ingest failed — ingestion error (namespace=%s): %s",
                namespace,
                exc,
            )
            return _build_error_response(
                status_code=400,
                code="ingestion_error",
                message=str(exc),
                namespace=namespace,
                files=file_summaries,
            )
        except FileNotFoundError as exc:
            logger.warning(
                "API ingest failed — file not found (namespace=%s): %s",
                namespace,
                exc,
            )
            return _build_error_response(
                status_code=400,
                code="not_found",
                message=str(exc),
                namespace=namespace,
                files=file_summaries,
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.exception("API ingest failed — unexpected error (namespace=%s)", namespace)
            return _build_error_response(
                status_code=500,
                code="internal_error",
                message="Ingestion failed due to an internal error.",
                namespace=namespace,
                files=file_summaries,
                detail=str(exc),
            )

    duration = time.perf_counter() - start
    ingest_summary = result or {
        "namespace": namespace,
        "documents_ingested": 0,
        "chunks_ingested": 0,
    }
    logger.info(
        "API ingest complete (namespace=%s, documents=%s, chunks=%s, duration=%.3fs)",
        namespace,
        ingest_summary.get("documents_ingested", 0),
        ingest_summary.get("chunks_ingested", 0),
        duration,
    )
    publish_event(
        "ingest_complete",
        {
            "namespace": namespace,
            "documents": ingest_summary.get("documents_ingested", 0),
            "chunks": ingest_summary.get("chunks_ingested", 0),
            "duration": duration,
        },
    )
    return _build_success_response(
        namespace=namespace,
        files=file_summaries,
        ingest=ingest_summary,
        duration=duration,
    )


def main() -> None:  # pragma: no cover - executed manually during development
    """Run the Yo web UI with the hardened WatchFiles reload supervisor."""

    import asyncio

    from yo.reloader import (
        DEFAULT_DEBOUNCE,
        DEFAULT_IGNORE_GLOBS,
        create_uvicorn_config_factory,
        serve_uvicorn_with_watchfiles,
    )

    host = os.environ.get("YO_HOST", "127.0.0.1")
    port = int(os.environ.get("YO_PORT", "8000"))
    reload_dirs = [Path("yo"), Path("tests")]

    config_factory = create_uvicorn_config_factory(
        "yo.webui:app",
        host=host,
        port=port,
    )

    try:
        asyncio.run(
            serve_uvicorn_with_watchfiles(
                config_factory,
                reload_dirs=reload_dirs,
                debounce=DEFAULT_DEBOUNCE,
                ignore_globs=DEFAULT_IGNORE_GLOBS,
            )
        )
    except RuntimeError as exc:
        logger.warning(
            "WatchFiles unavailable — falling back to standard uvicorn run (%s).",
            exc,
        )
        import uvicorn

        uvicorn.run("yo.webui:app", host=host, port=port, reload=False)


if __name__ == "__main__":  # pragma: no cover - manual execution path
    main()
