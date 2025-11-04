"""FastAPI application for the Yo Lite UI."""

from __future__ import annotations

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


TEMPLATES_DIR = Path(__file__).parent / "templates"
JINJA_AVAILABLE = import_util.find_spec("jinja2") is not None
templates = Jinja2Templates(directory=str(TEMPLATES_DIR)) if JINJA_AVAILABLE else None


@lru_cache(maxsize=1)
def get_brain() -> YoBrain:
    """Create a cached YoBrain instance for reuse across requests."""

    return YoBrain()


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
    if not (
        backends.milvus.available
        and backends.ollama_python.available
        and backends.ollama_cli.available
    ):
        raise HTTPException(
            status_code=503,
            detail="Ingestion requires Milvus Lite and the Ollama runtime to be installed.",
        )

    try:
        namespace, uploads = await _extract_uploads(request)
    except HTTPException as exc:
        raise exc

    try:
        brain = get_brain()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"YoBrain unavailable: {exc}") from exc

    written_paths: list[Path] = []
    with TemporaryDirectory() as tmpdir:
        temp_dir = Path(tmpdir)
        for upload in uploads:
            contents = await upload.read()
            await upload.close()
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

        if not written_paths:
            raise HTTPException(status_code=400, detail="Uploaded files were empty.")

        if len(written_paths) == 1:
            source = str(written_paths[0])
        else:
            source = str(temp_dir)

        try:
            result = brain.ingest(source, namespace=namespace)
        except MissingDependencyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except IngestionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - defensive guard
            raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}") from exc

    return JSONResponse(
        content={
            "status": "ok",
            "ingest": result
            or {
                "namespace": namespace,
                "documents_ingested": 0,
                "chunks_ingested": 0,
            },
        }
    )
