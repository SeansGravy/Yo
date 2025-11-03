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

## Phase 1 — Rich RAG Foundation (Next release target)

**Goal:** Expand Yo's memory so it comfortably ingests and reasons over mixed-format research archives.

### Key Deliverables
1. **Ingestion upgrades**
   * Add Markdown (`UnstructuredMarkdownLoader`) and PDF (`PyPDFLoader`) support with graceful fallbacks.
   * Expose a `--loader` override for power users; default to auto-detect based on file extension.
   * Track ingestion stats (documents, chunks, tokens) and surface them after each run.
2. **Quality & resilience**
   * Auto-trigger `compact` when the Milvus DB grows beyond a configurable threshold (e.g., 100 MiB) with a pre-compact backup.
   * Optional chunk re-embedding flow to rebuild namespaces when embeddings models change.
3. **Developer ergonomics**
   * Refresh `yo_full_test.sh` to cover new loaders and auto-compaction behavior.
   * Add type hints and docstrings in `yo/brain.py` for new ingestion helpers.

### Success Metrics
* CLI handles `.txt`, `.md`, and `.pdf` inputs end-to-end.
* Regression script covers at least one Markdown and PDF sample.
* Database size stays within threshold without manual compaction.

### Dependencies
* Python packages: `unstructured`, `pypdf` (or `pypdf2`), and any OCR fallback if PDFs are scanned.
* Adequate local storage for temporary assets during PDF parsing.

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

## Phase 3 — Local Autonomy Loop

**Goal:** Let Yo plan and execute lightweight research or maintenance tasks while remaining sandboxed.

### Key Deliverables
1. **Planning engine**
   * Introduce a planning routine (`yo.brain.plan`) that uses Ollama to break a user goal into steps.
   * Persist recent plans and outcomes in a lightweight SQLite table alongside Milvus metadata.
2. **Tool registry**
   * Define safe Python-callable tools (web search, file read/write within a sandbox, shell commands under allowlist).
   * Wire tools into a ReAct-style loop so the LLM can decide when to invoke them.
3. **Autonomous CLI workflows**
   * Add `yo.cli run "task description"` that executes the plan with streaming updates.
   * Provide dry-run (`--plan-only`) mode for review.
4. **Voice I/O (stretch)**
   * Optional Whisper transcription for voice commands and Piper/macOS TTS for responses.

### Success Metrics
* Tasks execute with human-interpretable logs and explicit confirmation before mutating actions.
* Plans survive process restarts via persisted memory.
* Voice mode is fully local with no external services required.

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
| `v0.3.0` | Phase 1 – Rich RAG | Extended loaders, auto-compaction, updated tests |
| `v0.4.0` | Phase 2 – Web awareness | Pluggable search, hybrid retrieval, observability |
| `v0.5.0` | Phase 3 – Autonomy | Planner loop, tool registry, optional voice mode |

Keep iterating on this roadmap as requirements evolve. Each phase should land behind feature flags where possible, letting you trial new capabilities without destabilizing your core second brain.
