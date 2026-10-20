from __future__ import annotations
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from .models import Document

class SnapshotStore:
    def __init__(self, path: str | Path='data/ruleshift.sqlite3'):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as con:
            con.execute('''CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_key TEXT NOT NULL, version TEXT NOT NULL, sha256 TEXT NOT NULL,
                captured_at TEXT NOT NULL, payload TEXT NOT NULL,
                UNIQUE(doc_key,sha256)
            )''')

    @contextmanager
    def _conn(self):
        con=sqlite3.connect(self.path,timeout=15)
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def save(self, doc: Document) -> bool:
        data = json.dumps(asdict(doc), ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(data.encode('utf-8')).hexdigest()
        with self._conn() as con:
            cur = con.execute('INSERT OR IGNORE INTO snapshots(doc_key,version,sha256,captured_at,payload) VALUES(?,?,?,?,?)',
                          (doc.title.strip(), doc.version, digest, datetime.now(timezone.utc).isoformat(), data))
            return cur.rowcount == 1

    def list_versions(self, title: str) -> list[Document]:
        with self._conn() as con:
            rows = con.execute('SELECT payload FROM snapshots WHERE doc_key=? ORDER BY id DESC',(title.strip(),)).fetchall()
        return [Document(**json.loads(row[0])) for row in rows]

    def list_titles(self) -> list[str]:
        with self._conn() as con:
            return [row[0] for row in con.execute('SELECT DISTINCT doc_key FROM snapshots ORDER BY doc_key')]
