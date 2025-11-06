"""FastAPI application for the Yo Lite UI."""

from __future__ import annotations

import json
import os
import asyncio
import contextlib
import faulthandler
import socket
import threading
import time
from datetime import datetime, timedelta
from importlib import util as import_util
from functools import lru_cache, partial
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, IO

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
from yo.websocket import ConnectionManager, UpdateBroadcaster, log_ws_error
from yo.optimizer import generate_recommendations, apply_recommendations


TEMPLATES_DIR = Path(__file__).parent / "templates"
JINJA_AVAILABLE = import_util.find_spec("jinja2") is not None
templates = Jinja2Templates(directory=str(TEMPLATES_DIR)) if JINJA_AVAILABLE else None


WEB_START_LOG = Path("data/logs/web_startup.log")
DEADLOCK_DUMP_PATH = Path("data/logs/web_deadlock.dump")
REQUEST_LOG_LIMIT = 10


CHAT_TIMING_LOG = Path("data/logs/chat_timing.log")
CHAT_TIMING_JSONL = Path("data/logs/chat_timing.jsonl")
CHAT_SLOW_THRESHOLD_MS = 4000.0
CHAT_PAGE_WARN_THRESHOLD_MS = 1000.0
CHAT_TIMEOUT_DEFAULT = 10.0
CHAT_STREAM_TIMEOUT_DEFAULT = 3.0


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


SERVER_HOST = os.getenv("YO_WEB_HOST", "127.0.0.1")
SERVER_PORT = int(os.getenv("YO_WEB_PORT", "8000"))
WEB_DEBUG = _is_truthy(os.getenv("YO_WEB_DEBUG"))
SERVER_READY = False

_request_log_count = 0
_deadlock_handle: IO[bytes] | None = None
_deadlock_active = False
_startup_lock = threading.Lock()
_startup_logged = False
_start_time = time.time()


def _append_startup_log(message: str) -> None:
    try:
        WEB_START_LOG.parent.mkdir(parents=True, exist_ok=True)
        with WEB_START_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.utcnow().isoformat()}Z {message}\n")
    except OSError:
        logger.warning("Failed to write startup log entry: %s", message)


def _schedule_deadlock_dump() -> None:
    global _deadlock_handle, _deadlock_active
    if _deadlock_active:
        return
    try:
        DEADLOCK_DUMP_PATH.parent.mkdir(parents=True, exist_ok=True)
        _deadlock_handle = open(DEADLOCK_DUMP_PATH, "wb")
        faulthandler.dump_traceback_later(15, repeat=False, file=_deadlock_handle)
        _deadlock_active = True
    except OSError as exc:  # pragma: no cover - filesystem failure
        logger.warning("Unable to schedule deadlock dump: %s", exc)


def _cancel_deadlock_dump() -> None:
    global _deadlock_handle, _deadlock_active
    if not _deadlock_active:
        return
    try:
        faulthandler.cancel_dump_traceback_later()
    except Exception:  # pragma: no cover - defensive
        pass
    if _deadlock_handle:
        try:
            _deadlock_handle.close()
        except Exception:
            pass
        _deadlock_handle = None
    _deadlock_active = False


def configure_runtime(host: str, port: int, *, debug: bool | None = None) -> None:
    global SERVER_HOST, SERVER_PORT, WEB_DEBUG
    SERVER_HOST = host
    SERVER_PORT = port
    if debug is not None:
        WEB_DEBUG = bool(debug)
        if debug:
            os.environ["YO_WEB_DEBUG"] = "1"
        else:
            os.environ.pop("YO_WEB_DEBUG", None)
    else:
        WEB_DEBUG = _is_truthy(os.getenv("YO_WEB_DEBUG"))
    if WEB_DEBUG:
        try:
            faulthandler.enable()
        except Exception:
            pass
    with _startup_lock:
        global _startup_logged
        if not _startup_logged:
            _append_startup_log(
                f"Starting Yo web server host={host} port={port} pid={os.getpid()}"
            )
            _startup_logged = True
    logger.warning("Yo web starting: host=%s port=%s debug=%s", host, port, WEB_DEBUG)
    _schedule_deadlock_dump()


def _log_request_event(message: str) -> None:
    global _request_log_count
    if _request_log_count >= REQUEST_LOG_LIMIT:
        return
    _append_startup_log(message)
    _request_log_count += 1


def _write_chat_timing(entry: dict[str, Any]) -> None:
    try:
        CHAT_TIMING_LOG.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(entry)
        with CHAT_TIMING_LOG.open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")
        with CHAT_TIMING_JSONL.open("a", encoding="utf-8") as jsonl_handle:
            jsonl_handle.write(payload + "\n")
    except OSError:  # pragma: no cover - logging must not break API
        logger.warning("Unable to write chat timing entry.")


def _extract_reply_text(value: Any) -> str:
    """Return a normalised string representation of a reply payload."""

    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str):
            return text.strip()
        for key in ("response", "reply", "message", "content"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate.strip()
    try:
        return str(value).strip()
    except Exception:  # pragma: no cover - defensive fallback
        return ""


def _coerce_reply_dict(value: Any, *, default_text: str) -> dict[str, str]:
    """Coerce a reply payload into the canonical dict schema."""

    text = _extract_reply_text(value) or default_text
    return {"text": text}


def _log_fallback_emit(session_id: str, namespace: str, reply: dict[str, str]) -> None:
    text = reply.get("text", "") or ""
    chat_logger.info(
        "fallback_emit complete sid=%s ns=%s txt_len=%d",
        session_id,
        namespace,
        len(text),
    )


@lru_cache(maxsize=1)
def get_brain() -> YoBrain:
    """Create a cached YoBrain instance for reuse across requests."""

    return YoBrain()


logger = get_logger(__name__)
chat_logger = get_logger("chat")

app = FastAPI(title="Yo Lite UI", version="0.4.0")

@app.middleware("http")
async def _timing_middleware(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if request.url.path == "/chat":
        status_code = getattr(response, "status_code", 0)
        chat_logger.info("GET /chat %s %.1fms", status_code, elapsed_ms)
        _append_startup_log(f"GET /chat status={status_code} elapsed={elapsed_ms:.1f}ms")
        try:
            record_metric(
                "chat_get",
                elapsed_ms=round(elapsed_ms, 2),
                status=status_code,
            )
        except Exception:  # pragma: no cover - metrics should not break responses
            chat_logger.warning("Unable to record chat_get metric.", exc_info=True)
        if elapsed_ms > CHAT_PAGE_WARN_THRESHOLD_MS:
            chat_logger.warning(
                "GET /chat exceeded threshold (%.1fms > %.1fms)",
                elapsed_ms,
                CHAT_PAGE_WARN_THRESHOLD_MS,
            )
    return response


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
    force_fallback: bool = False


class ConfigUpdateRequest(BaseModel):
    key: str
    value: str
    namespace: str | None = None

class OptimizeApplyRequest(BaseModel):
    ids: list[str] | None = None
    auto_only: bool = True


event_bus = get_event_bus()
chat_connections = ConnectionManager()


@app.middleware("http")
async def _startup_logging_middleware(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        _log_request_event(f"HTTP {request.method} {request.url.path} -> EXC ({exc})")
        _cancel_deadlock_dump()
        raise
    elapsed = time.perf_counter() - start
    _log_request_event(
        f"HTTP {request.method} {request.url.path} -> {response.status_code} ({elapsed:.3f}s)"
    )
    if response.status_code < 500:
        _cancel_deadlock_dump()
    return response


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

    status = "ok" if SERVER_READY else "starting"
    return {"status": status, "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/health", response_class=JSONResponse)
async def api_health() -> JSONResponse:
    status = "ok" if SERVER_READY else "starting"
    payload = {"status": status, "timestamp": datetime.utcnow().isoformat()}
    code = 200 if status == "ok" else 503
    return JSONResponse(content=payload, status_code=code)


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
async def render_chat(request: Request, namespace: str = "default", debug: int = 0) -> HTMLResponse:
    context = {
        "request": request,
        "app_version": app.version,
        "namespace": namespace,
        "debug": bool(debug),
    }
    if templates is None:
        html = (TEMPLATES_DIR / "chat.html").read_text(encoding="utf-8")
        html = html.replace("{{ app_version }}", app.version)
        html = html.replace("{{ namespace }}", namespace)
        html = html.replace("{{ namespace | tojson }}", json.dumps(namespace))
        html = html.replace("{{ 'true' if debug else 'false' }}", "true" if debug else "false")
        return HTMLResponse(content=html)
    return templates.TemplateResponse("chat.html", context)


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
    except WebSocketDisconnect as exc:
        record_metric(
            "ws_connect_error",
            code=getattr(exc, "code", 0) or 0,
            reason=str(getattr(exc, "reason", "disconnect")),
        )
        await event_bus.unsubscribe(queue)
    except Exception as exc:  # pragma: no cover
        record_metric("ws_connect_error", code=-1, reason=str(exc))
        await event_bus.unsubscribe(queue)


@app.websocket("/ws/chat/{session_id}")
async def websocket_chat_stream(session_id: str, websocket: WebSocket) -> None:
    await chat_connections.connect(session_id, websocket)
    _log_request_event(f"WS connect session={session_id}")
    _cancel_deadlock_dump()
    queue = await event_bus.subscribe()

    async def _ping_loop() -> None:
        try:
            while True:
                await asyncio.sleep(15)
                await chat_connections.send(
                    session_id,
                    {
                        "type": "chat_ping",
                        "session_id": session_id,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    },
                )
        except Exception:
            pass

    ping_task = asyncio.create_task(_ping_loop())
    try:
        while True:
            event = await queue.get()
            if event.get("session_id") != session_id:
                continue
            if event.get("type") not in {"chat_token", "chat_complete", "chat_message", "chat_started", "chat_fallback"}:
                continue
            payload = dict(event)
            payload.setdefault("session_id", session_id)
            await chat_connections.send(session_id, payload)
            await asyncio.sleep(0)
    except WebSocketDisconnect:
        await event_bus.unsubscribe(queue)
    except Exception as exc:  # pragma: no cover
        log_ws_error(f"chat stream failure for session {session_id}: {exc}")
        await event_bus.unsubscribe(queue)
    finally:
        ping_task.cancel()
        with contextlib.suppress(Exception):
            await ping_task
        with contextlib.suppress(Exception):
            await event_bus.unsubscribe(queue)
        with contextlib.suppress(Exception):
            await chat_connections.disconnect(session_id, websocket)


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
    env_force_fallback = stream_mode == "force"
    if env_force_fallback:
        stream_requested = False
    elif stream_mode == "off":
        stream_requested = True

    force_fallback = bool(payload.force_fallback) or env_force_fallback
    if force_fallback:
        stream_requested = False

    chat_timeout = float(os.environ.get("YO_CHAT_TIMEOUT", CHAT_TIMEOUT_DEFAULT))
    stream_timeout = float(os.environ.get("YO_CHAT_STREAM_TIMEOUT", CHAT_STREAM_TIMEOUT_DEFAULT))
    timeout_for_stream = stream_timeout if stream_timeout > 0 else chat_timeout

    async def _run_sync(func: callable, timeout: float, **kwargs):
        loop = asyncio.get_running_loop()
        bound = partial(func, **kwargs)
        return await asyncio.wait_for(loop.run_in_executor(None, bound), timeout=timeout)

    started = time.perf_counter()
    fallback_triggered = False
    stream_actual = stream_requested
    session_id = payload.session_id
    reply_text = ""
    reply_dict: dict[str, str] | None = None
    history: list[dict[str, str]] = []
    metadata: dict[str, Any] = {}

    truncated_msg = message[:120]
    chat_logger.info("chat start namespace=%s stream=%s message=%s", namespace, stream_requested, truncated_msg)
    _write_chat_timing(
        {
            "event": "start",
            "namespace": namespace,
            "session_id": session_id,
            "stream": stream_requested,
            "message": truncated_msg,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
    )

    try:
        if stream_requested:
            try:
                session_id, reply_text, history, metadata = await _run_sync(
                    chat_store.stream,
                    timeout=timeout_for_stream,
                    brain=brain,
                    namespace=namespace,
                    message=message,
                    session_id=payload.session_id,
                    web=payload.web,
                )
            except asyncio.TimeoutError:
                fallback_triggered = True
                stream_actual = False
                chat_logger.warning(
                    "chat stream timeout - invoking fallback namespace=%s timeout=%.2fs message=%s",
                    namespace,
                    timeout_for_stream,
                    truncated_msg,
                )
                _write_chat_timing(
                    {
                        "event": "fallback_invoked",
                        "namespace": namespace,
                        "session_id": session_id or payload.session_id,
                        "stream": stream_requested,
                        "message": truncated_msg,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    }
                )
                try:
                    session_id, reply_text, history, metadata = await _run_sync(
                        chat_store.send,
                        timeout=chat_timeout,
                        brain=brain,
                        namespace=namespace,
                        message=message,
                        session_id=payload.session_id,
                        web=payload.web,
                        fallback=True,
                    )
                    reply_dict = _coerce_reply_dict(reply_text, default_text="[fallback reply unavailable]")
                    stream_actual = False
                    fallback_log = {
                        "event": "fallback_result",
                        "namespace": namespace,
                        "session_id": session_id,
                        "stream": False,
                        "reply_text": reply_dict.get("text", "")[:240],
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    }
                    _write_chat_timing(fallback_log)
                    chat_logger.info(
                        "fallback result namespace=%s text=%s",
                        namespace,
                        reply_dict.get("text", "")[:120],
                    )
                    chat_logger.info(
                        "chat fallback namespace=%s txt_len=%d",
                        namespace,
                        len(reply_dict.get("text", "") or ""),
                    )
                    _write_chat_timing(
                        {
                            "event": "fallback_text",
                            "namespace": namespace,
                            "session_id": session_id,
                            "txt_len": len(reply_dict.get("text", "") or ""),
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                        }
                    )
                    chat_logger.info(
                        "deliver fallback sid=%s stream=%s txt_len=%d",
                        session_id,
                        False,
                        len(reply_dict.get("text", "") or ""),
                    )
                    _log_fallback_emit(session_id, namespace, reply_dict)
                except asyncio.TimeoutError:
                    fallback_triggered = True
                    stream_actual = False
                    timeout_reply = "[timeout] Yo chat request exceeded the configured limit."
                    existing_session = chat_store.session(payload.session_id)
                    history_payload = existing_session.as_history() if existing_session else None
                    fallback_payload: Any | None = None
                    fallback_error: Exception | None = None
                    try:
                        fallback_payload = await brain.chat_async(
                            message=message,
                            namespace=namespace,
                            history=history_payload,
                            web=payload.web,
                            timeout=chat_timeout,
                        )
                    except Exception as exc:
                        fallback_error = exc
                        chat_logger.exception("fallback chat_async failed namespace=%s: %s", namespace, exc)
                    final_text = ""
                    if fallback_error is not None:
                        final_text = f"[Error: {fallback_error}]"
                    else:
                        if isinstance(fallback_payload, dict):
                            final_text = (
                                str(fallback_payload.get("text") or "")
                                or str(fallback_payload.get("reply") or "")
                                or str(fallback_payload.get("response") or "")
                            )
                        elif fallback_payload is not None:
                            final_text = str(fallback_payload)
                    final_text = (final_text or "").strip()
                    if not final_text:
                        final_text = "[fallback reply unavailable]"
                    reply_dict = {"text": final_text}
                    reply_text = final_text
                    context = None
                    citations: list[Any] = []
                    if isinstance(fallback_payload, dict):
                        context = fallback_payload.get("context")
                        citations_payload = fallback_payload.get("citations")
                        if isinstance(citations_payload, list):
                            citations = citations_payload
                    session_id, reply_text, history, metadata = chat_store.record_fallback(
                        namespace=namespace,
                        message=message,
                        reply_text=reply_text,
                        session_id=payload.session_id,
                        context=context,
                        citations=citations,
                    )
                    reply_dict = _coerce_reply_dict(reply_text, default_text=timeout_reply)
                    stream_actual = False
                    fallback_log = {
                        "event": "fallback_result",
                        "namespace": namespace,
                        "session_id": session_id,
                        "stream": False,
                        "reply_text": reply_dict.get("text", "")[:240],
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    }
                    if fallback_error:
                        fallback_log["error"] = str(fallback_error)
                    _write_chat_timing(fallback_log)
                    chat_logger.info(
                        "fallback result namespace=%s text=%s",
                        namespace,
                        reply_dict.get("text", "")[:120],
                    )
                    chat_logger.info(
                        "chat fallback namespace=%s txt_len=%d",
                        namespace,
                        len(reply_dict.get("text", "") or ""),
                    )
                    _write_chat_timing(
                        {
                            "event": "fallback_text",
                            "namespace": namespace,
                            "session_id": session_id,
                            "txt_len": len(reply_dict.get("text", "") or ""),
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                        }
                    )
                    chat_logger.info(
                        "deliver fallback sid=%s stream=%s txt_len=%d",
                        session_id,
                        False,
                        len(reply_dict.get("text", "") or ""),
                    )
                    _log_fallback_emit(session_id, namespace, reply_dict)
                except Exception as exc:  # pragma: no cover
                    chat_logger.exception("chat fallback send errored namespace=%s: %s", namespace, exc)
                    raise HTTPException(status_code=500, detail="Chat fallback failed.") from exc
        if not stream_requested or force_fallback or not stream_actual:
            stream_actual = False
            if reply_dict is None:
                session_id, reply_text, history, metadata = await _run_sync(
                    chat_store.send,
                    timeout=chat_timeout,
                    brain=brain,
                    namespace=namespace,
                    message=message,
                    session_id=payload.session_id,
                    web=payload.web,
                    fallback=force_fallback,
                )
                reply_dict = _coerce_reply_dict(reply_text, default_text="[fallback reply unavailable]")
                fallback_triggered = fallback_triggered or force_fallback
                if force_fallback:
                    fallback_log = {
                        "event": "fallback_result",
                        "namespace": namespace,
                        "session_id": session_id,
                        "stream": False,
                        "reply_text": reply_dict.get("text", "")[:240],
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    }
                    _write_chat_timing(fallback_log)
                    chat_logger.info(
                        "fallback result namespace=%s text=%s",
                        namespace,
                        reply_dict.get("text", "")[:120],
                    )
                    chat_logger.info(
                        "deliver fallback sid=%s stream=%s txt_len=%d",
                        session_id,
                        False,
                        len(reply_dict.get("text", "") or ""),
                    )
                    _log_fallback_emit(session_id, namespace, reply_dict)
    except ValueError as exc:
        chat_logger.error("chat validation error namespace=%s: %s", namespace, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except asyncio.TimeoutError:
        chat_logger.warning("chat timeout namespace=%s message=%s", namespace, truncated_msg)
        raise HTTPException(status_code=504, detail="Chat request timed out.") from None
    except Exception as exc:
        chat_logger.exception("chat error namespace=%s: %s", namespace, exc)
        raise HTTPException(status_code=500, detail="Chat failed.") from exc

    if reply_dict is None:
        reply_dict = _coerce_reply_dict(reply_text, default_text="[no text generated]")
    reply_text_value = reply_dict.get("text", "") or ""

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    metadata = metadata or {}
    tokens_emitted = metadata.get("tokens_emitted", 0)
    first_token_latency_ms = metadata.get("first_token_latency_ms")
    fallback_used = bool(metadata.get("fallback_used") or fallback_triggered)
    metadata["fallback_used"] = fallback_used
    if fallback_used:
        stream_actual = False

    chat_logger.info(
        "chat complete namespace=%s stream=%s fallback=%s tokens=%s elapsed=%.1fms",
        namespace,
        stream_actual,
        fallback_used,
        tokens_emitted,
        elapsed_ms,
    )
    _write_chat_timing(
        {
            "event": "complete",
            "namespace": namespace,
            "session_id": session_id,
            "stream": stream_actual,
            "fallback": fallback_used,
            "tokens": tokens_emitted,
            "elapsed_ms": round(elapsed_ms, 2),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
    )

    if elapsed_ms > CHAT_SLOW_THRESHOLD_MS:
        try:
            record_metric(
                "chat_slow",
                namespace=namespace,
                elapsed_ms=round(elapsed_ms, 2),
                stream=stream_actual,
                fallback=fallback_used,
            )
        except Exception:  # pragma: no cover
            chat_logger.warning("Unable to record chat_slow metric.", exc_info=True)

    try:
        record_metric(
            "chat",
            namespace=namespace,
            latency_seconds=round(elapsed_ms / 1000.0, 3),
            tokens=len(reply_text_value),
            stream=stream_actual,
            history_length=len(history),
            fallback=fallback_used,
            tokens_emitted=tokens_emitted,
            first_token_latency_ms=first_token_latency_ms,
        )
        if stream_requested and not stream_actual:
            ws_metric_value = 0
        else:
            ws_metric_value = 100
        record_metric("ws_success_rate", value=ws_metric_value)
        if fallback_used:
            record_metric("chat_fallback_empty", value=0 if reply_text_value else 1)
    except Exception:  # pragma: no cover
        chat_logger.warning("Unable to record chat metrics.", exc_info=True)

    try:
        record_chat_interaction(
            session_id,
            namespace=namespace,
            latency_seconds=round(elapsed_ms / 1000.0, 3),
            tokens=len(reply_text_value),
            stream=stream_actual,
            history_length=len(history),
            fallback=fallback_used,
            first_token_latency_ms=first_token_latency_ms,
        )
    except Exception:  # pragma: no cover
        chat_logger.warning("Unable to record chat analytics.", exc_info=True)

    response_payload = {
        "type": "chat_message",
        "session_id": session_id,
        "reply": reply_dict,
        "namespace": namespace,
        "history": history,
        "context": metadata.get("context"),
        "citations": metadata.get("citations", []),
        "stream": stream_actual,
        "fallback": fallback_used,
        "tokens_emitted": tokens_emitted,
        "first_token_latency_ms": first_token_latency_ms,
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
    _append_startup_log("Lifespan startup event")
    await broadcaster.start()
    global SERVER_READY
    SERVER_READY = True
    elapsed = time.time() - _start_time
    _append_startup_log(f"Startup complete in {elapsed:.2f}s (host={SERVER_HOST} port={SERVER_PORT})")
    try:
        record_metric(
            "web_ready",
            host=SERVER_HOST,
            port=SERVER_PORT,
            debug=int(bool(WEB_DEBUG)),
        )
    except Exception:  # pragma: no cover - telemetry failures shouldn't crash startup
        logger.warning("Failed to record web_ready metric", exc_info=True)


@app.on_event("shutdown")
async def _shutdown_events() -> None:
    await broadcaster.stop()
    _append_startup_log("Lifespan shutdown event")
    _cancel_deadlock_dump()


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


__all__ = ["app", "configure_runtime"]
