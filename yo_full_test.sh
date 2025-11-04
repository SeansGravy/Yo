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

echo "🧠 Starting Yo full test suite..."
echo "All output will be logged to $LOGFILE"
echo "===================================================" | tee "$LOGFILE"

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

# 1️⃣ Verify environment
run "Python available" "python3 -V"
run "Ollama models accessible" "ollama list"
run "Data directory present" "ls data || echo 'No data folder yet (expected on fresh runs).'"

# 2️⃣ Namespace management
run "List namespaces" "python3 -m yo.cli ns list"
run "Ensure test namespace absent" "python3 -m yo.cli ns delete --ns test || echo 'Namespace test not found, skipping.'"

# 3️⃣ Ingestion
run "Ingest docs into default" "python3 -m yo.cli add ./docs/ --ns default"
run "Ingest docs into test" "python3 -m yo.cli add ./docs/ --ns test"

# 4️⃣ Summarization
run "Summarize default namespace" "python3 -m yo.cli summarize --ns default"

# 5️⃣ Q&A (local memory)
run "Answer question from memory" "python3 -m yo.cli ask 'What does Yo do?' --ns default"

# 6️⃣ Q&A with web context
run "Answer question with web" "python3 -m yo.cli ask 'What is new in LangChain 0.3?' --ns default --web"

# 7️⃣ Cache management
run "List cache entries" "python3 -m yo.cli cache list"
run "Clear cache" "python3 -m yo.cli cache clear"
run "List cache after clear" "python3 -m yo.cli cache list"

# 8️⃣ Namespace verification
run "List namespaces after operations" "python3 -m yo.cli ns list"

# 9️⃣ Auto-index verification (run again to confirm)
run "Re-ingest docs into default" "python3 -m yo.cli add ./docs/ --ns default"

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
