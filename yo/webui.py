"""FastAPI application for the Yo Lite UI."""

from __future__ import annotations

import os
import time
from datetime import datetime
from importlib import util as import_util
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.datastructures import UploadFile

from yo.backends import BackendStatus, detect_backends
from yo.brain import IngestionError, MissingDependencyError, YoBrain
from yo.logging_utils import get_logger


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


@app.get("/api/status", response_class=JSONResponse)
def api_status() -> JSONResponse:
    """Return backend availability and namespace insights for the Lite UI."""

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

    namespace_rows: list[dict[str, Any]] = []
    for name in namespaces:
        entry = activity.get(name, {})
        namespace_rows.append(
            {
                "name": name,
                "last_ingested": entry.get("last_ingested"),
                "documents": entry.get("documents"),
                "chunks": entry.get("chunks"),
                "records": entry.get("records"),
            }
        )

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

    payload: dict[str, Any] = {
        "backends": backend_info,
        "namespaces": namespace_rows,
        "ingestion": {
            "enabled": ingestion_enabled,
            "reason": "\n".join(dict.fromkeys(reasons)) if not ingestion_enabled and reasons else None,
        },
        "timestamp": datetime.utcnow().isoformat(),
    }
    if warning:
        payload["warning"] = warning

    return JSONResponse(content=payload)


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
