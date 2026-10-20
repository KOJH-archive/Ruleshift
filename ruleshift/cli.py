from __future__ import annotations
import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys
from .models import Document
from .storage import SnapshotStore
from .monitor import MonitorStore, monitor_once
from .workflow import run_analysis
from .quant import load_positions_csv, simulate_limit, simulate_loan_rate
from .notify import send_ntfy

ROOT=Path(__file__).resolve().parent.parent

def main(argv=None):
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
    parser=argparse.ArgumentParser(prog='ruleshift',description='법령·규정 변경 영향 레이더 (법률 자문 아님)')
    p=parser.add_subparsers(dest='command',required=True)
    d=p.add_parser('demo',help='가상 데이터 3종 분석')
    d.add_argument('--case',choices=['rp_limit','loan_terms','privacy'],default='rp_limit')
    d.add_argument('--output',default='')
    d.add_argument('--langgraph',action='store_true')
    d.add_argument('--laya',action='store_true')
    d.add_argument('--ollama',action='store_true')
    d.add_argument('--ollama-model',default=os.getenv('OLLAMA_MODEL','qwen2.5:7b'))
    c=p.add_parser('compare',help='두 로컬 문서 비교')
    c.add_argument('before');c.add_argument('after');c.add_argument('--title',required=True)
    c.add_argument('--stage',default='내부문서/미확인',choices=['제안/예고','공포/고시','시행','내부문서/미확인'])
    c.add_argument('--effective-date',default='');c.add_argument('--output',default='')
    w=p.add_parser('watch',help='감시 목록 관리')
    w.add_argument('action',choices=['add','list','pause','resume'])
    w.add_argument('--kind',choices=['law','fsc','fsc_final'],default='law')
    w.add_argument('--query',default='');w.add_argument('--keywords',default='')
    w.add_argument('--id',type=int)
    mon=p.add_parser('monitor',help='등록 소스 확인 후 변경 이벤트 저장')
    mon.add_argument('--notify',action='store_true',help='NTFY_TOPIC 환경설정시 미발송 변경만 알림 전송')
    mon.add_argument('--laya',action='store_true')
    mon.add_argument('--langgraph',action='store_true')
    mon.add_argument('--ollama',action='store_true')
    mon.add_argument('--ollama-model',default=os.getenv('OLLAMA_MODEL','qwen2.5:7b'))
    mon.add_argument('--db',default=str(ROOT/'data'/'monitor.sqlite3'))
    events=p.add_parser('events',help='최근 감시 이벤트 요약')
    events.add_argument('--limit',type=int,default=20)
    events.add_argument('--db',default=str(ROOT/'data'/'monitor.sqlite3'))
    rp=p.add_parser('rp',help='가명화된 포지션 CSV 기준 편입비율 시뮬레이션')
    rp.add_argument('--csv',required=True)
    rp.add_argument('--date',required=True)
    rp.add_argument('--old-limit',type=float,required=True)
    rp.add_argument('--new-limit',type=float,required=True)
    rp.add_argument('--start-months',type=int,default=6)
    rp.add_argument('--end-months',type=int,default=60)
    loan=p.add_parser('loan',help='잔액 고정 ACT/365 금리 변경 이자 계산')
    loan.add_argument('--principal',required=True)
    loan.add_argument('--old-rate',required=True)
    loan.add_argument('--new-rate',required=True)
    loan.add_argument('--days',type=int,default=30)
    a=parser.parse_args(argv)
    result=None
    if a.command=='demo':
        base=ROOT/'samples'/a.case
        meta=json.loads((base/'metadata.json').read_text(encoding='utf-8'))
        old=Document(meta['title'],(base/'before.txt').read_text(encoding='utf-8'),'가상-이전',**meta['old'])
        new=Document(meta['title'],(base/'after.txt').read_text(encoding='utf-8'),'가상-개정',**meta['new'])
        result=run_analysis(old,new,use_laya=a.laya,use_langgraph=a.langgraph,use_ollama=a.ollama,ollama_model=a.ollama_model).to_dict()
    elif a.command=='compare':
        from .parser import parse_bytes
        old_path=Path(a.before);new_path=Path(a.after)
        old=Document(a.title,parse_bytes(old_path.read_bytes(),old_path.name),'이전')
        new=Document(a.title,parse_bytes(new_path.read_bytes(),new_path.name),'개정',stage=a.stage,effective_date=a.effective_date)
        result=run_analysis(old,new).to_dict()
    elif a.command=='watch':
        s=MonitorStore(ROOT/'data'/'monitor.sqlite3')
        if a.action=='add':
            if not a.query:parser.error('watch add에는 --query 필요')
            result={'watch_id':s.add_watch(a.kind,a.query,a.keywords)}
        elif a.action=='list':result=[vars(w) for w in s.list_watches()]
        else:
            if a.id is None: parser.error('watch pause/resume에는 --id 필요')
            s.toggle(a.id,a.action=='resume')
            result={'watch_id':a.id,'enabled':a.action=='resume'}
    elif a.command=='monitor':
        from .law_api import LawOpenClient
        from .sources import FSCNoticeClient, FSCFinalClient
        s=MonitorStore(a.db)
        snapshots=SnapshotStore(ROOT/'data'/'ruleshift.sqlite3')
        oc=os.getenv('LAW_OC','')
        law_client=LawOpenClient(oc) if oc else None
        result=monitor_once(s,snapshots,law_client=law_client,fsc_client=FSCNoticeClient(),fsc_final_client=FSCFinalClient(),
                            use_laya=a.laya,use_langgraph=a.langgraph,use_ollama=a.ollama,ollama_model=a.ollama_model)
        if a.notify:
            pending=[e for e in s.list_events(500) if not e['notified']]
            if pending:
                topic=os.getenv('NTFY_TOPIC','')
                if not topic:
                    result['notification']='미전송: NTFY_TOPIC 미설정'
                else:
                    try:
                        send_ntfy(topic,'감시대상 변경',len(pending),os.getenv('NTFY_BASE_URL','https://ntfy.sh'),os.getenv('NTFY_TOKEN',''))
                        s.mark_notified([e['id'] for e in pending])
                        result['notification']=f'알림 서버에 {len(pending)}건 발송 요청'
                    except Exception as e:
                        result['notification']=f'발송 실패: {type(e).__name__}: {e}'
            else:result['notification']='새 알림 대상 없음'
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if result['errors'] or str(result.get('notification','')).startswith('발송 실패'):sys.exit(2)
        return
    elif a.command=='events':
        result=[{'id':e['id'],'title':e['title'],'created_at':e['created_at'],'reviewed':e['reviewed'],'notified':e['notified']} for e in MonitorStore(a.db).list_events(a.limit)]
    elif a.command=='rp':
        positions=load_positions_csv(Path(a.csv).read_text(encoding='utf-8-sig'))
        result=simulate_limit(positions,date.fromisoformat(a.date),a.old_limit,a.new_limit,a.start_months,a.end_months)
    elif a.command=='loan':
        result=simulate_loan_rate(a.principal,a.old_rate,a.new_rate,a.days)
    payload=json.dumps(result,ensure_ascii=False,indent=2)
    if getattr(a,'output',''):
        Path(a.output).write_text(payload,encoding='utf-8')
        print('저장:',a.output)
    else:print(payload)

if __name__=='__main__':main()
