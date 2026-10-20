"""Read-only comparison of any two official law MST versions.

Example: python scripts/verify_live_law.py OLD_MST NEW_MST
The OC credential is read from the local .env and never printed.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ruleshift.compare import compare
from ruleshift.law_api import LawOpenClient
from ruleshift.monitor import MonitorStore, monitor_once
from ruleshift.parser import parse_clauses
from ruleshift.storage import SnapshotStore


def main() -> int:
    parser = argparse.ArgumentParser(description='공식 법령 버전 읽기 전용 비교')
    parser.add_argument('old_mst', help='이전 법령일련번호')
    parser.add_argument('new_mst', help='새 법령일련번호')
    parser.add_argument('--inspect-sections', action='store_true', help='부칙/별표 식별자 차이 확인')
    parser.add_argument('--monitor-flow', action='store_true', help='임시 DB에서 기준선→개정→중복방지 검증')
    args = parser.parse_args()
    load_dotenv(ROOT / '.env')
    try:
        client = LawOpenClient(os.getenv('LAW_OC', ''))
        before = client.fetch(args.old_mst)
        after = client.fetch(args.new_mst)
        changes = compare(before, after)
    except (ValueError, RuntimeError, LookupError) as exc:
        print(f'검증 실패: {exc}', file=sys.stderr)
        return 1
    print(f'법령: {after.title}')
    print(f'버전: {before.version} → {after.version}')
    print(f'조문/부칙/별표 개수: {len(parse_clauses(before.text))} → {len(parse_clauses(after.text))}')
    print(f'감지 변경: {len(changes)}건')
    for change in changes:
        print(f'  {change.kind}: {change.clause_id}')
    if args.inspect_sections:
        for label, doc in [('이전', before), ('개정', after)]:
            sections = [item for item in parse_clauses(doc.text)
                        if item.id.startswith(('부칙', '별표'))]
            print(f'{label} 부칙/별표: {len(sections)}건')
            for item in sections[-6:]:
                print(f'  {item.id}: {len(item.text)}자')
    if args.monitor_flow:
        class FixedVersion:
            mst = args.old_mst
            def search(self, query):
                return [{'title': query, 'mst': self.mst, 'promulgated': ''}]
            def fetch(self, mst):
                return client.fetch(mst)
        source = FixedVersion()
        with tempfile.TemporaryDirectory(prefix='ruleshift-live-', dir=ROOT / 'data') as folder:
            store = MonitorStore(Path(folder) / 'monitor.sqlite3')
            snapshots = SnapshotStore(Path(folder) / 'snapshots.sqlite3')
            store.add_watch('law', after.title)
            baseline = monitor_once(store, snapshots, law_client=source)
            source.mst = args.new_mst
            amendment = monitor_once(store, snapshots, law_client=source)
            repeated = monitor_once(store, snapshots, law_client=source)
            if baseline['errors'] or amendment['errors'] or repeated['errors']:
                print('감시 흐름 검증 실패: 수집 오류', file=sys.stderr)
                return 1
            if (baseline['new_events'], amendment['new_events'], repeated['new_events']) != (0, 1, 0):
                print('감시 흐름 검증 실패: 이벤트 건수가 예상과 다릅니다.', file=sys.stderr)
                return 1
            print('감시 흐름 검증: 기준선 0건 → 개정 알림 1건 → 재조회 중복 0건')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
