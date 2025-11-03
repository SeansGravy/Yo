import os, json, sqlite3
from pymilvus import connections

class YoBrain:
    def __init__(self):
        self.db_path = 'data/milvus_lite.db'

    def add(self, path, namespace='default'):
        print(f'[add] Ingesting from {path} into namespace {namespace}')
        return True

    def ask(self, query, namespace='default', web=False):
        print(f'[ask] Query: {query} (ns={namespace}, web={web})')
        return f'Placeholder answer for {query}'

    def summarize(self, namespace='default'):
        print(f'[summarize] Summarizing namespace {namespace}')
        return f'Summary for namespace {namespace}'

    def _list_cache(self):
        cache_file = 'data/web_cache.json'
        if not os.path.exists(cache_file):
            print('No cache file found.')
            return
        with open(cache_file, 'r') as f:
            data = json.load(f)
        print(json.dumps(data, indent=2))

    def _clear_cache(self):
        cache_file = 'data/web_cache.json'
        if os.path.exists(cache_file):
            os.remove(cache_file)
            print('Cache cleared.')
        else:
            print('No cache to clear.')

    def compact(self):
        print('Running SQLite VACUUM on Milvus Lite DB...')
        conn = sqlite3.connect(self.db_path)
        conn.execute('VACUUM;')
        conn.close()
        print('Compaction complete.')
