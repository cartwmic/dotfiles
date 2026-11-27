"""Where a T3 thread sits in the thread tree, read from T3's own database (opened read-only).

One way to walk up from a thread to the nearest thread that something owns, shared by
thread_rank.py (workstream-rank) and token-efficiency/workstreams.py (spend per workstream).
Standard library only.
"""
import json
import sqlite3
import urllib.parse


def readonly(path):
    return sqlite3.connect('file:%s?mode=ro' % urllib.parse.quote(path), uri=True)


def parent_from_payload(payload_json):
    """The parent thread id in a T3 thread's stored payload, or None."""
    return (json.loads(payload_json).get('lineage') or {}).get('parentThreadId')


class Parents:
    """thread -> parent thread, one lookup per thread asked. It answers `.get` like a dict, so `nearest` takes it or a dict."""

    def __init__(self, path):
        self.db = readonly(path)

    def get(self, thread, default=None):
        row = self.db.execute('select payload_json from orchestration_v2_projection_threads where thread_id = ?', (thread,)).fetchone()
        return (parent_from_payload(row[0]) if row else None) or default

    def close(self):
        self.db.close()


def nearest(thread, parent, owners):
    """owners[t] for the nearest thread t at or above `thread` that is in `owners`, else None. `parent` has `.get(thread)`. Loops end the walk."""
    seen = set()
    while thread and thread not in seen:
        if thread in owners:
            return owners[thread]
        seen.add(thread)
        thread = parent.get(thread)
    return None
