#!/bin/bash
# --- yo/brain.py Milvus fix ---
# replaces Collection.list_collections() with proper list_collections() usage

echo "🔧 Applying Milvus list_collections() fix..."
sed -i.bak 's/Collection.list_collections()/list_collections()/g' yo/brain.py
# ensure correct import
grep -q "from pymilvus import list_collections" yo/brain.py || \
sed -i '/from pymilvus import / s/$/, list_collections/' yo/brain.py

echo "✅ Patch complete. Backup saved as yo/brain.py.bak"

