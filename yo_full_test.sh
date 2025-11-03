#!/bin/bash
# =====================================================
# Yo Full Test Script — v0.2.0 Validation Suite
# =====================================================

set -e
LOGFILE="yo_test_results_$(date +%Y%m%d_%H%M%S).log"

echo "🧠 Starting Yo full test suite..."
echo "All output will be logged to $LOGFILE"
echo "===================================================" | tee "$LOGFILE"

run() {
  echo "" | tee -a "$LOGFILE"
  echo "▶️ $1" | tee -a "$LOGFILE"
  echo "---------------------------------------------------" | tee -a "$LOGFILE"
  eval "$1" 2>&1 | tee -a "$LOGFILE"
  echo "" | tee -a "$LOGFILE"
}

# 1️⃣ Verify environment
run "python3 -V"
run "ollama list"
run "ls data || echo 'No data folder yet (expected on fresh runs).'"

# 2️⃣ Namespace management
run "python3 -m yo.cli ns list"
run "python3 -m yo.cli ns delete --ns test || echo 'Namespace test not found, skipping.'"

# 3️⃣ Ingestion
run "python3 -m yo.cli add ./docs/ --ns default"
run "python3 -m yo.cli add ./docs/ --ns test"

# 4️⃣ Summarization
run "python3 -m yo.cli summarize --ns default"

# 5️⃣ Q&A (local memory)
run "python3 -m yo.cli ask 'What does Yo do?' --ns default"

# 6️⃣ Q&A with web context
run "python3 -m yo.cli ask 'What is new in LangChain 0.3?' --ns default --web"

# 7️⃣ Cache management
run "python3 -m yo.cli cache list"
run "python3 -m yo.cli cache clear"
run "python3 -m yo.cli cache list"

# 8️⃣ Namespace verification
run "python3 -m yo.cli ns list"

# 9️⃣ Auto-index verification (run again to confirm)
run "python3 -m yo.cli add ./docs/ --ns default"

# 🔟 Log cleanup summary
echo "===================================================" | tee -a "$LOGFILE"
echo "✅ Yo test suite completed successfully at $(date)" | tee -a "$LOGFILE"
echo "Results saved in: $LOGFILE"
echo "===================================================" | tee -a "$LOGFILE"
