# 🛤️ Yo Roadmap — Building the Local Second Brain

## Vision
Yo is a privacy-first "second brain" that runs entirely on your workstation. We will extend the current Milvus Lite + Ollama stack into a richer assistant that can ingest more document formats, stay aware of the web when asked, and orchestrate autonomous workflows without leaving your machine.

This roadmap breaks the journey into phases. Each phase is shippable on its own and builds toward a cohesive local agent that understands your knowledge base, augments it with fresh context, and can carry out lightweight plans.

---

## Phase 0 — Foundation (✅ Complete)

* Restore the Python CLI (`yo/cli.py`) and core brain (`yo/brain.py`).
* Support text ingestion, retrieval-augmented answers, namespace management, and cached web lookups.
* Harden Milvus Lite initialization with safe recovery and add manual compaction (`yo.cli compact`).
* Document the system (README, USER_GUIDE, Yo_Handoff_Report) and ship end-to-end regression tooling (`yo_full_test.sh`, `yo.cli verify`).

These items are done and establish a stable base for future features.

---

## Phase 1 — Rich RAG Foundation (🚀 v0.3.0 in progress)

**Goal:** Expand Yo's memory so it comfortably ingests and reasons over mixed-format research archives.

### Key Deliverables
1. **Ingestion upgrades**
   * ✅ Add Markdown (`UnstructuredMarkdownLoader`), PDF (`PyPDFLoader` with OCR fallback), and code-focused loaders with extension filters.
   * ✅ Integrate OCR helpers (`unstructured[local-inference]`, `pytesseract`) so scanned PDFs and images are captured when dependencies are installed.
   * ✅ Expose a `--loader` override for power users; default to auto-detect based on file extension.
   * Track ingestion stats (documents, chunks, tokens) and surface them after each run.
2. **Quality & resilience**
   * ✅ Auto-trigger `compact` when the Milvus DB grows beyond a configurable threshold (e.g., 100 MiB) with a pre-compact backup.
   * Optional chunk re-embedding flow to rebuild namespaces when embeddings models change.
3. **Developer ergonomics**
   * Refresh `yo_full_test.sh` to cover new loaders and auto-compaction behavior.
   * Add type hints and docstrings in `yo/brain.py` for new ingestion helpers.

### Success Metrics
* CLI handles `.txt`, `.md`, `.pdf`, and source-code inputs end-to-end.
* Regression script covers at least one Markdown, PDF, and code sample.
* Database size stays within threshold without manual compaction.

### Dependencies
* Python packages: `unstructured`, `pypdf` (or `pypdf2`), OCR extras (e.g., `unstructured[local-inference]`, `pytesseract`), and code parsing utilities.
* Adequate local storage for temporary assets during PDF parsing and OCR staging.

---

## Phase 1.5 — Lite UI Bridge

**Goal:** Provide a minimal desktop/web shell so non-terminal users can browse, ingest, and query Yo.

### Key Deliverables
1. **UI shell**
   * Ship a lightweight UI (e.g., Textual TUI or a small FastAPI + HTMX web panel) for add/ask/summarize flows.
   * Mirror CLI status output (ingestion counts, cache hits, citations) within the interface.
2. **Session persistence**
   * Remember last-used namespace, query history, and cached answers across restarts.
3. **Packaging**
   * Provide a convenience launcher (`yo ui`) and document how to run the interface alongside the CLI.

### Success Metrics
* Users can ingest files, ask questions, and review answers entirely within the UI.
* CLI and UI share the same underlying brain and state with no divergence.

### Dependencies
* Additional framework dependencies (`textual`, `fastapi`, or similar) and static assets for the UI shell.

---

## Phase 2 — Web Awareness & Hybrid Search

**Goal:** Blend trusted web context with local knowledge while preserving privacy controls.

### Key Deliverables
1. **Improved web ingestion**
   * Replace ad-hoc DuckDuckGo scraping with a pluggable search module (DuckDuckGo HTML, Brave, SerpAPI).
   * Normalize responses into structured snippets (title, URL, summary, timestamp).
   * Cache metadata in `data/web_cache.json` with per-source TTL.
2. **Hybrid retrieval**
   * Allow `yo.cli ask` to search multiple namespaces simultaneously and merge scores.
   * Provide CLI flags for weighting local vs. web context.
   * Add a summarization pass that reconciles overlapping facts and deduplicates citations.
3. **Observability & controls**
   * Expand CLI output to show which sources were used (local chunk IDs + web URLs).
   * Add `--offline-only` switch to enforce local answers even if `--web` is set globally.

### Success Metrics
* Users can see which namespaces and web sources influenced each answer.
* Hybrid queries default to safe behavior (no web access without explicit `--web`).
* Cache hit ratio surfaced via `yo.cli cache list`.

### Dependencies
* API keys if a paid search provider is chosen; fall back to anonymous providers otherwise.
* Potential rate limiting protections (exponential backoff, caching strategy tweaks).

---

## Phase 2.5 — Persistent Memory & Model Routing

**Goal:** Enrich answers with long-lived conversational memory while picking the best local model for each task.

### Key Deliverables
1. **Memory fabric**
   * Persist interaction summaries and follow-up questions in a lightweight store (SQLite or JSONL) separate from Milvus.
   * Surface a `--remember` toggle to opt-in to storing query/answer pairs and allow pruning via `yo.cli memory clear`.
2. **Context injection**
   * Blend persistent memories into prompts when they are topically relevant, with safeguards to avoid prompt bloat.
3. **Model routing**
   * Allow per-command model overrides (`--model llama3`, `--model gemma2`) and route automatically based on task type (summaries vs. creative writing).
   * Cache routing decisions so repeated tasks reuse the optimal model.

### Success Metrics
* Memory-enhanced answers show higher factual continuity across sessions.
* Routing chooses smaller models for lightweight tasks without regressing quality.

### Dependencies
* Additional persistence layer (SQLite table or LiteLLM-style JSON store).
* Configuration surface for per-model capabilities and costs.

---

## Phase 3 — Local Autonomy Loop

**Goal:** Let Yo plan and execute lightweight research or maintenance tasks while remaining sandboxed.

### Key Deliverables
1. **Planning engine**
   * Introduce a planning routine (`yo.brain.plan`) that uses Ollama to break a user goal into steps.
   * Persist recent plans and outcomes in a lightweight SQLite table alongside Milvus metadata.
2. **Tool registry**
   * Define safe Python-callable tools (web search, file read/write within a sandbox, shell commands under allowlist).
   * Wire tools into a ReAct-style loop so the LLM can decide when to invoke them.
3. **Background ingestion & macros**
   * Support a background watcher that ingests files from configured folders on a schedule.
   * Allow users to define workflow macros (e.g., "daily research digest") that bundle ingest → summarize → share steps.
4. **Autonomous CLI workflows**
   * Add `yo.cli run "task description"` that executes the plan with streaming updates.
   * Provide dry-run (`--plan-only`) mode for review.
5. **Optional voice I/O (stretch goal)**
   * Integrate Whisper transcription for voice commands and Piper/macOS TTS for responses, fully offline.

### Success Metrics
* Tasks execute with human-interpretable logs and explicit confirmation before mutating actions.
* Plans survive process restarts via persisted memory.
* Voice mode remains optional and fully local with no external services required.

### Dependencies
* Additional Python packages: `whisper`, `sounddevice`, or platform-specific audio bindings if voice support is enabled.
* OS-specific sandboxing (e.g., restrict shell commands via config file).

---

## Cross-Cutting Initiatives
* **Security & Privacy:** enforce configuration-driven allowlists, redact sensitive data from logs, and ensure cached web data is easy to purge.
* **Testing & CI:** set up GitHub Actions (or local pre-commit hooks) that run unit tests, linting, and the CLI smoke suite.
* **Documentation:** keep README/USER_GUIDE aligned with new commands; publish architecture diagrams once hybrid retrieval ships.
* **Packaging:** explore a `pipx`-friendly CLI wrapper once dependencies stabilize.

---

## Release Milestones
| Version | Focus | Key Artifacts |
| ------- | ----- | ------------- |
| `v0.2.x` | Foundation hardening | Current CLI + docs + manual compact |
| `v0.3.0` | Phase 1 – Rich RAG | ✅ Enhanced loaders (OCR, PDF, code), auto-compaction, updated tests |
| `v0.3.5` | Phase 1.5 – Lite UI | Minimal UI shell + shared state |
| `v0.4.0` | Phase 2 – Web awareness | Pluggable search, hybrid retrieval, observability |
| `v0.4.5` | Phase 2.5 – Memory & routing | Persistent conversations, adaptive model selection |
| `v0.5.0` | Phase 3 – Autonomy | Planner loop, workflow macros, optional voice mode |

Keep iterating on this roadmap as requirements evolve. Each phase should land behind feature flags where possible, letting you trial new capabilities without destabilizing your core second brain.
