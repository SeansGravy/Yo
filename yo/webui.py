"""FastAPI stub for the upcoming Yo Lite UI."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from yo.backends import detect_backends
from yo.brain import YoBrain


@lru_cache(maxsize=1)
def get_brain() -> YoBrain:
    """Create a cached YoBrain instance for reuse across requests."""

    return YoBrain()


app = FastAPI(title="Yo Lite UI", version="0.3.1")


@app.get("/healthz", response_class=JSONResponse)
def healthcheck() -> dict[str, Any]:
    """Simple readiness probe for upcoming Lite UI."""

    return {"status": "ok"}


@app.get("/ui", response_class=HTMLResponse)
def render_ui() -> HTMLResponse:
    """Render a minimal HTML stub for the Lite UI."""

    brain = get_brain()
    namespaces = brain.ns_list(silent=True)
    namespace_items = "".join(f"<li>{ns}</li>" for ns in namespaces) or "<li>No namespaces yet</li>"

    html = f"""
    <html>
      <head>
        <title>Yo Lite UI</title>
        <style>
          body {{ font-family: sans-serif; margin: 2rem; }}
          h1 {{ color: #444; }}
          section {{ margin-bottom: 2rem; }}
          .status-ok {{ color: #2e7d32; }}
        </style>
      </head>
      <body>
        <h1>Yo Lite UI (Coming Soon)</h1>
        <section>
          <h2>System Status</h2>
          <p class="status-ok">✅ Backend online</p>
        </section>
        <section>
          <h2>Namespaces</h2>
          <ul>{namespace_items}</ul>
        </section>
        <section>
          <h2>Ingestion Progress</h2>
          <p>Tracking hooks will appear here in Phase 1.5.</p>
        </section>
      </body>
    </html>
    """

    return HTMLResponse(content=html)


@app.get("/api/status", response_class=JSONResponse)
def api_status() -> JSONResponse:
    """Return backend availability and namespace insights for the Lite UI."""

    backends = detect_backends()
    backend_info = {
        "milvus": {
            "available": backends.milvus.available,
            "detail": backends.milvus.message,
        },
        "ollama": {
            "python": {
                "available": backends.ollama_python.available,
                "detail": backends.ollama_python.message,
            },
            "cli": {
                "available": backends.ollama_cli.available,
                "detail": backends.ollama_cli.message,
            },
            "ready": backends.ollama_python.available and backends.ollama_cli.available,
        },
    }

    namespaces: list[str] = []
    activity: dict[str, Any] = {}
    warning: str | None = None

    try:
        brain = get_brain()
    except Exception as exc:  # pragma: no cover - backend initialization failure
        warning = str(exc)
    else:
        try:
            namespaces = brain.ns_list(silent=True)
            activity = brain.namespace_activity()
        except Exception as exc:  # pragma: no cover - backend query failure
            warning = str(exc)

    payload: dict[str, Any] = {
        "backends": backend_info,
        "namespaces": namespaces,
        "namespace_activity": activity,
    }
    if warning:
        payload["warning"] = warning

    return JSONResponse(content=payload)
