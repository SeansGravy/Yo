#!/bin/bash
# ===========================================
# Yo Documentation & CLI Verification Script
# ===========================================
set -e

echo "🔍 Verifying Yo documentation consistency..."
echo "--------------------------------------------"

# 1️⃣ Check version tag
if git describe --tags --abbrev=0 >/dev/null 2>&1; then
  tag=$(git describe --tags --abbrev=0)
  echo "✅ Found latest tag: $tag"
else
  echo "⚠️ No git tag found. You should tag v0.2.0 before release."
fi

# 2️⃣ Confirm key docs exist
for file in README.md USER_GUIDE.md ROADMAP.md CHANGELOG.md docs/CLI.md; do
  if [[ -f "$file" ]]; then
    echo "✅ $file exists"
  else
    echo "❌ Missing $file"
  fi
done

# 3️⃣ Lint for command examples in README
if grep -q "python3 -m yo.cli add" README.md && grep -q "yo.cli ask" README.md; then
  echo "✅ CLI usage examples present in README.md"
else
  echo "⚠️ Missing CLI usage examples in README.md"
fi

# 4️⃣ Verify CHANGELOG version
if grep -q "## \[v0.2.0\]" CHANGELOG.md; then
  echo "✅ CHANGELOG includes v0.2.0 entry"
else
  echo "⚠️ CHANGELOG missing v0.2.0 entry"
fi

# 5️⃣ Check Python CLI syntax
echo "🔧 Checking CLI syntax..."
python3 -m py_compile yo/cli.py yo/brain.py && echo "✅ CLI scripts compile cleanly"

# 6️⃣ Optional: dry-run CLI help text
echo "🔧 Testing command help..."
python3 -m yo.cli --help || true

# 7️⃣ Print next steps
echo "--------------------------------------------"
echo "✅ Verification complete!"
echo "If all checks are green, run:"
echo "  git add ."
echo "  git commit -m 'docs: verified and finalized v0.2.0 documentation'"
echo "  git tag -a v0.2.0 -m 'Yo v0.2.0 – verified release'"
echo "  git push origin main --tags"
