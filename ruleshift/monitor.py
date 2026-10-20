"""Idempotent source monitoring with a durable review queue. First poll seeds baseline."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import contextmanager
from .applicability import evaluate_applicability
from .models import Document
from .sources import FSCNoticeClient, FSCFinalClient, notice_document
from .law_api import LawOpenClient
from .workflow import run_analysis
from .storage import SnapshotStore

@dataclass(frozen=True)
class Watch:
    id: int
    kind: str
    query: str
    keywords: str
    enabled: bool = True

class MonitorStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self._conn() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS watchlist (
                 id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
                 query TEXT NOT NULL, keywords TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1,
                 UNIQUE(kind,query));
              CREATE TABLE IF NOT EXISTS user_profiles (
                 name TEXT PRIMARY KEY, profile_json TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS watch_conditions (
                 watch_id INTEGER PRIMARY KEY, conditions_json TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS seen (
                 watch_id INTEGER NOT NULL, key TEXT NOT NULL,
                 first_seen TEXT NOT NULL, PRIMARY KEY (watch_id,key));
              CREATE TABLE IF NOT EXISTS events (
                 id INTEGER PRIMARY KEY AUTOINCREMENT, watch_id INTEGER NOT NULL,
                 event_key TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
                 created_at TEXT NOT NULL, payload TEXT NOT NULL,
                 reviewed INTEGER NOT NULL DEFAULT 0,
                 notified INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS monitor_errors (
                 id INTEGER PRIMARY KEY AUTOINCREMENT, watch_id INTEGER NOT NULL,
                 occurred_at TEXT NOT NULL,error TEXT NOT NULL);
            ''')
    @contextmanager
    def _conn(self):
        db=sqlite3.connect(self.path,timeout=15)
        db.execute('PRAGMA busy_timeout=15000')
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    def save_profile(self, name: str, profile: dict):
        if not isinstance(profile,dict): raise ValueError('프로필은 JSON 객체여야 합니다.')
        with self._conn() as db:
            db.execute('INSERT OR REPLACE INTO user_profiles(name,profile_json) VALUES(?,?)',(name,json.dumps(profile,ensure_ascii=False)))
    def load_profile(self, name: str='default') -> dict:
        with self._conn() as db:
            row=db.execute('SELECT profile_json FROM user_profiles WHERE name=?',(name,)).fetchone()
        return json.loads(row[0]) if row else {}
    def save_conditions(self, watch_id: int, conditions: dict):
        evaluate_applicability({},conditions)
        with self._conn() as db:
            db.execute('INSERT OR REPLACE INTO watch_conditions(watch_id,conditions_json) VALUES(?,?)',
                       (watch_id,json.dumps(conditions,ensure_ascii=False)))
    def load_conditions(self, watch_id: int) -> dict:
        with self._conn() as db:
            row=db.execute('SELECT conditions_json FROM watch_conditions WHERE watch_id=?',(watch_id,)).fetchone()
        return json.loads(row[0]) if row else {}
    def applicability(self, watch_id: int) -> dict:
        from dataclasses import asdict
        return asdict(evaluate_applicability(self.load_profile(),self.load_conditions(watch_id)))
    def add_watch(self, kind: str, query: str, keywords: str='') -> int:
        if kind not in ('law','fsc','fsc_final'): raise ValueError('지원 감시 소스: law/fsc/fsc_final')
        query=query.strip()
        if not 2<=len(query)<=160: raise ValueError('관심 법령명/검색어 2~160자')
        with self._conn() as db:
            db.execute('INSERT OR IGNORE INTO watchlist(kind,query,keywords) VALUES(?,?,?)',(kind,query,keywords[:500]))
            return db.execute('SELECT id FROM watchlist WHERE kind=? AND query=?',(kind,query)).fetchone()[0]
    def toggle(self, id: int, enabled: bool):
        with self._conn() as db:
            db.execute('UPDATE watchlist SET enabled=? WHERE id=?',(int(enabled),id))
    def list_watches(self, enabled_only: bool=False) -> list[Watch]:
        with self._conn() as db:
            rows=db.execute('SELECT id,kind,query,keywords,enabled FROM watchlist '+('WHERE enabled=1 ' if enabled_only else '')+'ORDER BY id').fetchall()
        return [Watch(int(a),b,c,d,bool(e)) for a,b,c,d,e in rows]
    def has_seen(self, watch_id: int, key: str) -> bool:
        with self._conn() as db:
            return db.execute('SELECT 1 FROM seen WHERE watch_id=? AND key=?',(watch_id,key)).fetchone() is not None
    def seen_count(self, watch_id: int) -> int:
        with self._conn() as db:
            return db.execute('SELECT count(*) FROM seen WHERE watch_id=?',(watch_id,)).fetchone()[0]
    def record_seen(self, watch_id: int, key: str) -> bool:
        with self._conn() as db:
            return db.execute('INSERT OR IGNORE INTO seen(watch_id,key,first_seen) VALUES(?,?,?)',
                              (watch_id,key,datetime.now(timezone.utc).isoformat())).rowcount==1
    def record_event(self, watch_id: int, key: str, title: str, payload: dict) -> bool:
        safe=json.dumps(payload,ensure_ascii=False)
        with self._conn() as db:
            return db.execute('INSERT OR IGNORE INTO events(watch_id,event_key,title,created_at,payload) VALUES(?,?,?,?,?)',
                              (watch_id,key,title,datetime.now(timezone.utc).isoformat(),safe)).rowcount==1
    def event_id(self, key: str) -> int:
        with self._conn() as db:
            row=db.execute('SELECT id FROM events WHERE event_key=?',(key,)).fetchone()
        if row is None:
            raise LookupError('저장된 이벤트를 찾지 못했습니다.')
        return int(row[0])
    def list_events(self, limit: int=100) -> list[dict]:
        with self._conn() as db:
            rows=db.execute('SELECT id,watch_id,title,created_at,payload,reviewed,notified FROM events ORDER BY id DESC LIMIT ?', (min(max(limit,1),500),)).fetchall()
        return [{'id':a,'watch_id':b,'title':c,'created_at':d,'payload':json.loads(e),'reviewed':bool(f),'notified':bool(g)} for a,b,c,d,e,f,g in rows]
    def mark_reviewed(self, id: int, reviewed: bool=True):
        with self._conn() as db:
            db.execute('UPDATE events SET reviewed=? WHERE id=?',(int(reviewed),id))
    def mark_notified(self, ids: list[int]):
        if not ids:return
        with self._conn() as db:
            db.executemany('UPDATE events SET notified=1 WHERE id=?',[(id,) for id in ids])
    def log_error(self, watch_id: int, error: str):
        with self._conn() as db:
            db.execute('INSERT INTO monitor_errors(watch_id,occurred_at,error) VALUES(?,?,?)',
                       (watch_id,datetime.now(timezone.utc).isoformat(),error[:500]))
    def errors(self, limit: int=30) -> list[dict]:
        with self._conn() as db:
            rows=db.execute('SELECT watch_id,occurred_at,error FROM monitor_errors ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        return [dict(watch_id=a,occurred_at=b,error=c) for a,b,c in rows]


def _event_key(w: Watch, unique: str) -> str:
    return hashlib.sha256(f'{w.id}|{w.kind}|{unique}'.encode()).hexdigest()


def monitor_once(store: MonitorStore, snapshot_store: SnapshotStore, law_client=None,
                 fsc_client=None, fsc_final_client=None, use_laya=False,
                 use_langgraph=False, use_ollama=False, ollama_model='qwen2.5:7b') -> dict:
    """Poll sources. Baseline seeds quietly. Failures persist and never imply 'no changes'."""
    stats={'watches':0,'seeded':0,'new_events':0,'unchanged':0,'errors':[],'new_event_ids':[]}
    for w in store.list_watches(enabled_only=True):
        stats['watches']+=1
        try:
            first_poll=store.seen_count(w.id)==0
            if w.kind == 'law':
                if law_client is None: raise ValueError('LAW_OC 미설정 — 법령 감시 실행 불가')
                matches=law_client.search(w.query)
                # Never choose an arbitrary near match.
                exact=[r for r in matches if r['title'].replace(' ','')==w.query.replace(' ','')]
                if not exact: raise LookupError('일치하는 법령명 없음. 검색 조건 또는 API 응답 확인')
                chosen=max(exact,key=lambda r:(r.get('promulgated') or '',r.get('mst') or ''))
                version_key=chosen['mst']
                doc=law_client.fetch(version_key)
                if doc.title.replace(' ','') != w.query.replace(' ',''):
                    raise ValueError('법령 API 검색명과 조회 본문명이 일치하지 않습니다.')
                if str(doc.version) != str(version_key):
                    raise ValueError('검색 결과와 조회한 법령 버전이 일치하지 않습니다.')
                fingerprint=hashlib.sha256(json.dumps(
                    [doc.version,doc.text,doc.effective_date,doc.published_date],
                    ensure_ascii=False).encode('utf-8')).hexdigest()
                if store.has_seen(w.id,fingerprint): stats['unchanged']+=1; continue
                old_versions=snapshot_store.list_versions(doc.title)
                previous=old_versions[0] if old_versions else None
                # Do not advance the baseline before analysis/event persistence succeeds.
                # Otherwise a failed analysis makes the next poll compare the new
                # version against itself and silently lose the amendment event.
                metadata_changed = (previous is not None and
                    (previous.effective_date != doc.effective_date or previous.published_date != doc.published_date))
                version_changed=previous is not None and previous.version != doc.version
                if previous and (previous.text != doc.text or metadata_changed or version_changed) and not first_poll:
                    report=run_analysis(previous,doc,use_laya=use_laya,use_langgraph=use_langgraph,
                                        use_ollama=use_ollama,ollama_model=ollama_model)
                    if metadata_changed:
                        report.warnings.append('공포일·시행일 메타데이터가 변경되었습니다. 원문 및 부칙을 별도 재확인하세요.')
                    payload={'category':'법령 버전/날짜 정보 변경','watch_query':w.query,'source_url':doc.source_url,
                             'stage':doc.stage,'report':report.to_dict(), 'verified':False,
                             'metadata_changed':metadata_changed,
                             'applicability':store.applicability(w.id)}
                    k=_event_key(w,fingerprint)
                    if store.record_event(w.id,k,doc.title,payload):
                        stats['new_events']+=1
                        stats['new_event_ids'].append(store.event_id(k))
                else:
                    stats['seeded']+=int(first_poll)
                snapshot_store.save(doc)
                store.record_seen(w.id,fingerprint)
            elif w.kind in ('fsc','fsc_final'):
                if fsc_client is None: fsc_client=FSCNoticeClient()
                if fsc_final_client is None: fsc_final_client=FSCFinalClient()
                keywords=[s.strip() for s in w.keywords.split(',') if s.strip()]
                if not keywords: keywords=[w.query]
                notices=(fsc_client if w.kind=='fsc' else fsc_final_client).recent(max_items=12,keywords=keywords)
                if not notices:
                    raise LookupError('금융위 게시판에서 일치 항목이 없습니다. 레이아웃/검색어를 확인하세요.')
                for n in notices:
                    if store.has_seen(w.id,n.notice_id):
                        stats['unchanged']+=1; continue
                    if first_poll:
                        store.record_seen(w.id,n.notice_id)
                        stats['seeded']+=1
                        continue
                    doc=notice_document(n)
                    if w.kind=='fsc_final':
                        doc=Document(doc.title,doc.text,doc.version,source_url=doc.source_url,
                                     source_type='금융위 고시·공고 게시판',stage='공포/고시',
                                     published_date=doc.published_date,verified=False)
                    before=Document(doc.title,'제1조(공고문 안내)\n신규 공고문 최초 탐지', '미탐지')
                    report=run_analysis(before,doc,use_laya=use_laya,use_langgraph=use_langgraph,
                                        use_ollama=use_ollama,ollama_model=ollama_model)
                    category=('새 금융위 예고 공고(법령 개정 확정 아님)' if w.kind=='fsc'
                              else '새 금융위 고시·공고 게시물(세부 효력 미확인)')
                    payload={'category':category,'watch_query':w.query,
                             'source_url':n.url,'stage':doc.stage,'notice_id':n.notice_id,
                             'report':report.to_dict(),'verified':False,
                             'content_complete':bool(n.text),
                             'applicability':store.applicability(w.id)}
                    k=_event_key(w,n.notice_id)
                    if store.record_event(w.id,k,n.title,payload):
                        stats['new_events']+=1
                        stats['new_event_ids'].append(store.event_id(k))
                    store.record_seen(w.id,n.notice_id)
            else: raise ValueError('지원되지 않는 소스')
        except Exception as e:
            detail=f'watch #{w.id} ({w.kind}/{w.query}): {type(e).__name__}: {str(e)[:180]}'
            store.log_error(w.id,detail)
            stats['errors'].append(detail)
    return stats
