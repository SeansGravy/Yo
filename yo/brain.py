import os
import json
import sqlite3

class YoBrain:
    def __init__(self):
        self.db_path = 'data/milvus_lite.db'

    def ns_list(self):
        print('[ns_list] Listing namespaces')
        print(' - yo_default')
        return ['yo_default']

    def ns_delete(self, namespace):
        print(f"[ns_delete] Deleting namespace {namespace}")
        return True

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

# Added stub methods for namespace management
def _yo_ns_list(self):
    print('[ns_list] Listing namespaces')
    print(' - yo_default')
    return ['yo_default']

def _yo_ns_delete(self, namespace):
    print(f'[ns_delete] Deleting namespace {namespace}')
    return True

YoBrain.ns_list = _yo_ns_list
YoBrain.ns_delete = _yo_ns_delete
