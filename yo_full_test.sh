#!/bin/bash
# =====================================================
# Yo Full Test Script — v0.2.0 Validation Suite
# =====================================================

set -u
set -o pipefail
LOGFILE=${YO_LOGFILE:-}
if [[ -z "$LOGFILE" ]]; then
  LOGFILE="yo_test_results_$(date +%Y%m%d_%H%M%S).log"
fi
SUMMARY=()
FAILED=0

run() {
  local label="$1"
  local command="$2"

  echo "" | tee -a "$LOGFILE"
  echo "▶️ $command" | tee -a "$LOGFILE"
  echo "---------------------------------------------------" | tee -a "$LOGFILE"
  eval "$command" 2>&1 | tee -a "$LOGFILE"
  local status=${PIPESTATUS[0]}
  echo "" | tee -a "$LOGFILE"

  if [[ $status -eq 0 ]]; then
    SUMMARY+=("✅ $label")
  else
    SUMMARY+=("❌ $label (exit $status)")
    FAILED=1
  fi
}

skip() {
  local label="$1"
  local reason="$2"
  echo "" | tee -a "$LOGFILE"
  echo "⏭️ Skipping: $label" | tee -a "$LOGFILE"
  echo "    Reason: $reason" | tee -a "$LOGFILE"
  SUMMARY+=("⚠️ $label (skipped: $reason)")
}

detect_python_modules() {
  local first="$1"
  local second="$2"
  python3 - <<PY
import importlib.util
import sys

if importlib.util.find_spec("$first") and importlib.util.find_spec("$second"):
    sys.exit(0)
sys.exit(1)
PY
}

detect_python_module() {
  local module="$1"
  python3 - <<PY
import importlib.util
import sys

if importlib.util.find_spec("$module"):
    sys.exit(0)
sys.exit(1)
PY
}

# -----------------------------------------------------
# Backend detection (can be overridden by environment)
# -----------------------------------------------------

MILVUS_READY=${YO_HAVE_MILVUS:-}
MILVUS_REASON=${YO_MILVUS_REASON:-"Install Milvus Lite support via 'pip install pymilvus[milvus_lite]'."}
if [[ -z "$MILVUS_READY" ]]; then
  if detect_python_modules "milvus_lite" "pymilvus"; then
    MILVUS_READY=1
    MILVUS_REASON="Milvus Lite runtime detected."
  else
    MILVUS_READY=0
  fi
fi

OLLAMA_PY_READY=${YO_HAVE_OLLAMA_PY:-}
OLLAMA_PY_REASON=${YO_OLLAMA_PY_REASON:-"Install the Ollama Python bindings via 'pip install ollama langchain-ollama'."}
if [[ -z "$OLLAMA_PY_READY" ]]; then
  if detect_python_modules "ollama" "langchain_ollama"; then
    OLLAMA_PY_READY=1
    OLLAMA_PY_REASON="Ollama Python bindings detected."
  else
    OLLAMA_PY_READY=0
  fi
fi

if [[ -n "${YO_HAVE_OLLAMA_CLI:-}" ]]; then
  OLLAMA_CLI_READY=${YO_HAVE_OLLAMA_CLI}
else
  if command -v ollama >/dev/null 2>&1; then
    OLLAMA_CLI_READY=1
    OLLAMA_CLI_REASON="Ollama CLI detected."
  else
    OLLAMA_CLI_READY=0
    OLLAMA_CLI_REASON="Install the Ollama CLI from https://ollama.com/download and ensure it is on your PATH."
  fi
fi
OLLAMA_CLI_REASON=${YO_OLLAMA_CLI_REASON:-${OLLAMA_CLI_REASON:-"Install the Ollama CLI from https://ollama.com/download."}}

CHARDET_READY=${YO_HAVE_CHARDET:-}
CHARDET_REASON=${YO_CHARDET_REASON:-"Install chardet via 'pip install chardet'."}
if [[ -z "$CHARDET_READY" ]]; then
  if detect_python_module "chardet"; then
    CHARDET_READY=1
    CHARDET_REASON="chardet detected."
  else
    CHARDET_READY=0
  fi
fi

OPENPYXL_READY=${YO_HAVE_OPENPYXL:-}
OPENPYXL_REASON=${YO_OPENPYXL_REASON:-"Install openpyxl via 'pip install openpyxl'."}
if [[ -z "$OPENPYXL_READY" ]]; then
  if detect_python_module "openpyxl"; then
    OPENPYXL_READY=1
    OPENPYXL_REASON="openpyxl detected."
  else
    OPENPYXL_READY=0
  fi
fi

run_step() {
  local label="$1"
  local command="$2"
  local need_milvus="${3:-0}"
  local need_ollama_py="${4:-0}"
  local need_ollama_cli="${5:-$need_ollama_py}"

  local reason=""
  if [[ "$need_milvus" == "1" && "$MILVUS_READY" != "1" ]]; then
    reason="Milvus Lite unavailable (${MILVUS_REASON})"
  elif [[ "$need_ollama_py" == "1" && "$OLLAMA_PY_READY" != "1" ]]; then
    reason="Ollama Python bindings unavailable (${OLLAMA_PY_REASON})"
  elif [[ "$need_ollama_cli" == "1" && "$OLLAMA_CLI_READY" != "1" ]]; then
    reason="Ollama CLI unavailable (${OLLAMA_CLI_REASON})"
  fi

  if [[ -n "$reason" ]]; then
    skip "$label" "$reason"
    return
  fi

  run "$label" "$command"
}

if [[ "$MILVUS_READY" != "1" ]]; then
  echo "⚠️ Milvus Lite not detected — vector-store operations will be skipped." | tee -a "$LOGFILE"
fi
if [[ "$OLLAMA_PY_READY" != "1" || "$OLLAMA_CLI_READY" != "1" ]]; then
  echo "⚠️ Ollama backend incomplete — generation tests will be skipped as needed." | tee -a "$LOGFILE"
  if [[ "$OLLAMA_PY_READY" != "1" ]]; then
    echo "   • $OLLAMA_PY_REASON" | tee -a "$LOGFILE"
  fi
  if [[ "$OLLAMA_CLI_READY" != "1" ]]; then
    echo "   • $OLLAMA_CLI_REASON" | tee -a "$LOGFILE"
  fi
fi

echo "🧠 Starting Yo full test suite..."
echo "All output will be logged to $LOGFILE"
echo "===================================================" | tee "$LOGFILE"

# 1️⃣ Verify environment
run_step "Python available" "python3 -V"
run_step "Ollama models accessible" "ollama list" 0 0 1
run_step "Data directory present" "ls data || echo 'No data folder yet (expected on fresh runs).'"

# 2️⃣ Namespace management
run_step "List namespaces" "python3 -m yo.cli ns list" 1 1
run_step "Ensure test namespace absent" "python3 -m yo.cli ns delete --ns test || echo 'Namespace test not found, skipping.'" 1 1

# 3️⃣ Ingestion
run_step "Ensure sample fixtures" "python3 scripts/generate_ingest_fixtures.py" 1 1
run_step "Ingest docs into default" "python3 -m yo.cli add ./docs/ --ns default" 1 1
run_step "Ingest docs into test" "python3 -m yo.cli add ./docs/ --ns test" 1 1

if [[ "$CHARDET_READY" == "1" ]]; then
  run_step "Ingest PDF fixture" "python3 -m yo.cli add fixtures/ingest/brochure.pdf --ns ingest_pdf" 1 1
else
  skip "Ingest PDF fixture" "chardet unavailable (${CHARDET_REASON})"
fi

if [[ "$CHARDET_READY" == "1" && "$OPENPYXL_READY" == "1" ]]; then
  run_step "Ingest XLSX fixture" "python3 -m yo.cli add fixtures/ingest/sample.xlsx --ns ingest_xlsx" 1 1
else
  reason=""
  if [[ "$CHARDET_READY" != "1" ]]; then
    reason="chardet unavailable (${CHARDET_REASON})"
  elif [[ "$OPENPYXL_READY" != "1" ]]; then
    reason="openpyxl unavailable (${OPENPYXL_REASON})"
  fi
  skip "Ingest XLSX fixture" "$reason"
fi

# 4️⃣ Summarization
run_step "Summarize default namespace" "python3 -m yo.cli summarize --ns default" 1 1

# 5️⃣ Q&A (local memory)
run_step "Answer question from memory" "python3 -m yo.cli ask 'What does Yo do?' --ns default" 1 1

# 6️⃣ Q&A with web context
run_step "Answer question with web" "python3 -m yo.cli ask 'What is new in LangChain 0.3?' --ns default --web" 1 1

# 7️⃣ Cache management
run_step "List cache entries" "python3 -m yo.cli cache list" 1 1
run_step "Clear cache" "python3 -m yo.cli cache clear" 1 1
run_step "List cache after clear" "python3 -m yo.cli cache list" 1 1

# 8️⃣ Namespace verification
run_step "List namespaces after operations" "python3 -m yo.cli ns list" 1 1

# 9️⃣ Auto-index verification (run again to confirm)
run_step "Re-ingest docs into default" "python3 -m yo.cli add ./docs/ --ns default" 1 1

# 🔟 Log cleanup summary
echo "===================================================" | tee -a "$LOGFILE"
for line in "${SUMMARY[@]}"; do
  echo "$line" | tee -a "$LOGFILE"
done

if [[ $FAILED -eq 0 ]]; then
  echo "✅ Yo test suite completed successfully at $(date)" | tee -a "$LOGFILE"
else
  echo "❌ Yo test suite encountered failures at $(date)" | tee -a "$LOGFILE"
fi
echo "Results saved in: $LOGFILE"
echo "===================================================" | tee -a "$LOGFILE"

exit $FAILED
