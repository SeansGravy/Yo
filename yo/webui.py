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
from starlette.datastructures import UploadFile

from yo.backends import BackendStatus, detect_backends
from yo.brain import YoBrain


DASHBOARD_HTML = """
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Yo Lite UI</title>
        <style>
          :root {
            color-scheme: light dark;
          }
          body {
            font-family: "Segoe UI", system-ui, sans-serif;
            margin: 0 auto;
            padding: 2rem;
            max-width: 960px;
            background: #f7f7f7;
            color: #222;
          }
          h1, h2 {
            color: #2b3954;
          }
          header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
          }
          header span {
            font-size: 0.9rem;
            color: #555;
          }
          section {
            background: #fff;
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin-bottom: 2rem;
          }
          table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
          }
          th, td {
            border-bottom: 1px solid #e0e0e0;
            padding: 0.75rem 0.5rem;
            text-align: left;
          }
          tbody tr:last-child td {
            border-bottom: none;
          }
          .status-list {
            list-style: none;
            padding: 0;
            margin: 0;
          }
          .status-list li {
            margin-bottom: 0.5rem;
            display: flex;
            gap: 0.5rem;
            align-items: baseline;
          }
          .status-icon {
            font-weight: bold;
          }
          .notice {
            margin-top: 1rem;
            font-size: 0.95rem;
          }
          .notice.warn {
            color: #a84300;
          }
          .notice.error {
            color: #9b1c1c;
          }
          .notice.ok {
            color: #2e7d32;
          }
          .actions {
            display: flex;
            gap: 0.5rem;
            margin-bottom: 1rem;
            flex-wrap: wrap;
          }
          button {
            background: #2b6cb0;
            color: #fff;
            border: none;
            padding: 0.6rem 1.1rem;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.95rem;
          }
          button[disabled] {
            background: #9ca3af;
            cursor: not-allowed;
          }
          input[type="text"] {
            padding: 0.5rem;
            font-size: 1rem;
            border-radius: 6px;
            border: 1px solid #cbd5e0;
          }
          input[type="file"] {
            font-size: 1rem;
          }
          form .field {
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
            margin-bottom: 1rem;
          }
          .warning-banner {
            padding: 0.75rem 1rem;
            border-radius: 8px;
            background: #fff8e1;
            color: #8a5d00;
            margin-bottom: 1rem;
            display: none;
          }
          .warning-banner.active {
            display: block;
          }
          @media (prefers-color-scheme: dark) {
            body {
              background: #111827;
              color: #e5e7eb;
            }
            section {
              background: #1f2937;
              box-shadow: none;
            }
            header span {
              color: #9ca3af;
            }
            th, td {
              border-bottom: 1px solid #374151;
            }
            input[type="text"], input[type="file"] {
              border: 1px solid #4b5563;
              background: #111827;
              color: #e5e7eb;
            }
          }
        </style>
      </head>
      <body>
        <header>
          <div>
            <h1>Yo Lite UI</h1>
            <span>Dashboard preview · v__APP_VERSION__</span>
          </div>
          <div class="actions">
            <button id="refresh-button" type="button">Refresh Status</button>
          </div>
        </header>
        <div id="status-warning" class="warning-banner"></div>
        <section>
          <h2>Backend Health</h2>
          <ul id="backend-status" class="status-list"></ul>
        </section>
        <section>
          <h2>Namespaces</h2>
          <table id="namespace-table">
            <thead>
              <tr>
                <th>Namespace</th>
                <th>Last Ingested</th>
                <th>Documents</th>
                <th>Chunks</th>
                <th>Records</th>
              </tr>
            </thead>
            <tbody></tbody>
          </table>
        </section>
        <section>
          <h2>Ingest Documents</h2>
          <p id="ingest-notice" class="notice"></p>
          <form id="ingest-form" enctype="multipart/form-data">
            <div class="field">
              <label for="namespace">Namespace</label>
              <input id="namespace" name="namespace" type="text" value="default" required />
            </div>
            <div class="field">
              <label for="files">Files to ingest</label>
              <input id="files" name="files" type="file" multiple required />
            </div>
            <button id="ingest-submit" type="submit">Upload &amp; Ingest</button>
          </form>
          <div id="ingest-feedback" class="notice"></div>
        </section>
        <script>
          const statusUrl = '/api/status';
          const ingestUrl = '/api/ingest';

          function iconFor(available) {
            return available ? '✅' : '❌';
          }

          function renderBackends(backends) {
            const list = document.getElementById('backend-status');
            list.innerHTML = '';
            const rows = [
              ['Milvus Lite runtime', backends.milvus],
              ['Ollama Python bindings', backends.ollama.python],
              ['Ollama CLI', backends.ollama.cli]
            ];
            for (const [label, info] of rows) {
              const item = document.createElement('li');
              const icon = document.createElement('span');
              icon.className = 'status-icon';
              icon.textContent = iconFor(info.available);
              const text = document.createElement('span');
              let detail = info.detail || '';
              if (info.version) {
                detail += detail ? ` (version ${info.version})` : `Version ${info.version}`;
              }
              text.textContent = `${label}: ${detail}`;
              item.appendChild(icon);
              item.appendChild(text);
              list.appendChild(item);
            }
          }

          function renderNamespaces(namespaces) {
            const tbody = document.querySelector('#namespace-table tbody');
            tbody.innerHTML = '';
            if (!Array.isArray(namespaces) || namespaces.length === 0) {
              const row = document.createElement('tr');
              const cell = document.createElement('td');
              cell.colSpan = 5;
              cell.textContent = 'No namespaces available yet.';
              row.appendChild(cell);
              tbody.appendChild(row);
              return;
            }
            for (const ns of namespaces) {
              const row = document.createElement('tr');
              const fields = [
                ns.name,
                ns.last_ingested ? new Date(ns.last_ingested).toLocaleString() : '—',
                ns.documents ?? '—',
                ns.chunks ?? '—',
                ns.records ?? '—'
              ];
              for (const value of fields) {
                const cell = document.createElement('td');
                cell.textContent = value;
                row.appendChild(cell);
              }
              tbody.appendChild(row);
            }
          }

          function updateNotice(element, message, type) {
            element.textContent = message;
            element.className = `notice ${type}`.trim();
          }

          function updateIngestionState(ingestion) {
            const button = document.getElementById('ingest-submit');
            const fileInput = document.getElementById('files');
            const notice = document.getElementById('ingest-notice');
            if (!ingestion.enabled) {
              button.disabled = true;
              fileInput.disabled = true;
              updateNotice(notice, ingestion.reason || 'Ingestion disabled until backends are available.', 'warn');
            } else {
              button.disabled = false;
              fileInput.disabled = false;
              updateNotice(notice, 'Upload files to ingest them into your selected namespace.', 'ok');
            }
          }

          function updateWarningBanner(warning) {
            const banner = document.getElementById('status-warning');
            if (warning) {
              banner.textContent = warning;
              banner.classList.add('active');
            } else {
              banner.textContent = '';
              banner.classList.remove('active');
            }
          }

          async function refreshStatus() {
            try {
              const response = await fetch(statusUrl, { cache: 'no-store' });
              const data = await response.json();
              renderBackends(data.backends);
              renderNamespaces(data.namespaces);
              updateIngestionState(data.ingestion);
              updateWarningBanner(data.warning);
            } catch (error) {
              updateWarningBanner('Unable to load status: ' + error);
            }
          }

          document.getElementById('refresh-button').addEventListener('click', refreshStatus);

          document.getElementById('ingest-form').addEventListener('submit', async (event) => {
            event.preventDefault();
            const feedback = document.getElementById('ingest-feedback');
            updateNotice(feedback, 'Uploading…', '');
            const form = event.currentTarget;
            const formData = new FormData(form);
            try {
              const response = await fetch(ingestUrl, {
                method: 'POST',
                body: formData,
              });
              if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                const message = payload.detail || 'Ingestion failed.';
                updateNotice(feedback, `❌ ${message}`, 'error');
              } else {
                const payload = await response.json();
                const info = payload.ingest || {};
                const docCount = info.documents_ingested ?? '0';
                const chunkCount = info.chunks_ingested ?? '0';
                updateNotice(
                  feedback,
                  `✅ Ingested ${docCount} documents / ${chunkCount} chunks into "${info.namespace || formData.get('namespace')}".`,
                  'ok'
                );
                form.reset();
                document.getElementById('namespace').value = info.namespace || 'default';
                refreshStatus();
              }
            } catch (error) {
              updateNotice(feedback, `❌ Upload failed: ${error}`, 'error');
            }
          });

          refreshStatus();
          setInterval(refreshStatus, 15000);
        </script>
      </body>
    </html>
    """


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
def render_ui() -> HTMLResponse:
    """Render the Lite UI dashboard."""

    html = DASHBOARD_HTML.replace("__APP_VERSION__", app.version)
    return HTMLResponse(content=html)


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
        except ValueError as exc:
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
