import sqlite3
from pathlib import Path
from pymilvus import connections

class YoBrain:
    def __init__(self):
        """Initialize Milvus Lite connection with safe fallback."""
        self.data_dir = Path("data/milvus_lite.db")
        try:
            connections.connect(alias="default", uri=str(self.data_dir))
            print(f"✅ Connected to Milvus Lite at {self.data_dir}")
        except Exception as e:
            print(f"⚠️  Connection failed: {e}")

    def compact(self):
        """Perform a lightweight SQLite VACUUM to compact the Milvus Lite DB."""
        try:
            print("🧹 Running database compaction...")
            before = self.data_dir.stat().st_size / (1024 * 1024)
            conn = sqlite3.connect(self.data_dir)
            conn.execute("VACUUM;")
            conn.close()
            after = self.data_dir.stat().st_size / (1024 * 1024)
            print(f"✅ Compaction complete. Size: {before:.2f}MB → {after:.2f}MB")
        except Exception as e:
            print(f"⚠️  Compaction failed: {e}")
