"""RuleShift: local-first Streamlit dashboard. No data sent to commercial AI by default."""
from __future__ import annotations
import json
import os
from datetime import date
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv
from ruleshift.models import Document
from ruleshift.workflow import run_analysis
from ruleshift.storage import SnapshotStore
from ruleshift.parser import parse_bytes
from ruleshift.reporting import markdown_report
from ruleshift.impact import PROFILES
from ruleshift.applicability import evaluate_applicability
from ruleshift.monitor import MonitorStore, monitor_once
from ruleshift.quant import load_positions_csv, simulate_limit, simulate_loan_rate
from ruleshift.notify import send_ntfy
from ruleshift.number_extract import limit_suggestions

ROOT=Path(__file__).resolve().parent
load_dotenv(ROOT/'.env')
DB=ROOT/'data'/'ruleshift.sqlite3'
WATCH_DB=ROOT/'data'/'monitor.sqlite3'
store=SnapshotStore(DB)
ms=MonitorStore(WATCH_DB)

st.set_page_config(page_title='RuleShift | Regulatory Impact Radar',page_icon='⚖️',layout='wide')
st.title('⚖️ RuleShift | 규정 변경 영향 레이더')
st.caption('법령·금융위 예고·내부 규정 비교 / 근거 중심 영향검토 / 로컬 우선 / 거래·계약 자동 변경 없음')
st.info('검토 보조 도구입니다. 법적 적용대상·시행일·경과규정과 실제 포트폴리오 규정은 사람이 확인해야 합니다. 샘플은 모두 가상입니다.')

with st.sidebar:
    st.markdown('### 실행 환경')
    st.write('스냅샷',len(store.list_titles()),'개 문서')
    st.write('감시 등록',len(ms.list_watches()),'건')
    st.caption('저장소: 프로젝트 data/ 폴더의 SQLite')
    st.warning('사내 비공개 문서는 승인된 PC에서만 취급하고 원격 배포 서버에 올리지 마세요.')
    with st.expander('분류·생성 모델 설정'):
        use_laya=st.checkbox('LAYA 참고 분류',value=False,help='설치 및 다국어 체크포인트 다운로드 필요')
        use_graph=st.checkbox('LangGraph 실행 경로',value=False,help='langgraph 패키지 설치 필요')
        use_ollama=st.checkbox('Ollama 로컬 설명 생성',value=False,help='로컬 Ollama 서버와 설치된 모델 필요')
        ollama_model=st.text_input('Ollama 모델명',value=os.getenv('OLLAMA_MODEL','qwen2.5:7b'))
        st.caption('모델이 실패하면 경고를 기록하고 기본 로직으로 복귀합니다. 생성 설명은 원문 직접 인용을 검사합니다.')

page_dashboard,page_watch,page_compare,page_simulate,page_help=st.tabs(['📌 변경·검토함','🔔 자동 감시','⚖️ 문서 비교','🧮 영향 시뮬레이션','🔧 설정·제약'])

with page_dashboard:
    events=ms.list_events(150)
    c1,c2,c3=st.columns(3)
    c1.metric('수집된 신규 이벤트',len(events))
    c2.metric('미검토',sum(not e['reviewed'] for e in events))
    c3.metric('알림 미발송',sum(not e['notified'] for e in events))
    if not events:
        st.info('변경 이력이 없습니다. 자동 감시 탭에서 관심 법령을 등록하고 최초 기준 버전을 수집하세요.')
    else:
        only_pending=st.toggle('미검토 항목만',value=True)
        for e in events:
            if only_pending and e['reviewed']:continue
            with st.expander(f"#{e['id']} · {e['title']} · {e['created_at'][:16]}" + (' ✓ 검토됨' if e['reviewed'] else ' · 검토 대기')):
                payload=e['payload']; rpt=payload.get('report',{})
                st.write('**감지 유형**',payload.get('category',''), ' / **효력 단계**',payload.get('stage','미확인'))
                if payload.get('source_url'):st.link_button('공식 출처 확인',payload['source_url'])
                for a in rpt.get('assessments',[]):
                    ch=a.get('change',{})
                    st.markdown(f"**{ch.get('kind','')} · {ch.get('clause_id','')}** — 관련성 {a.get('relevance','')}, 영향도 {a.get('impact','')}")
                    st.caption(a.get('reason',''))
                st.caption('내 프로필 적용성 검사: '+payload.get('applicability',{}).get('status','미설정'))
                for warning in rpt.get('warnings',[]):st.warning(warning)
                st.download_button('이벤트 JSON',data=json.dumps(payload,ensure_ascii=False,indent=2),
                                   file_name=f"ruleshift_event_{e['id']}.json",key=f"dl_{e['id']}",mime='application/json')
                if st.button('검토 완료' if not e['reviewed'] else '검토 취소',key=f"review_{e['id']}"):
                    ms.mark_reviewed(e['id'],not e['reviewed']);st.rerun()
    with st.expander('최근 자동 감시 오류'):
        errors=ms.errors()
        if errors:st.dataframe(errors,use_container_width=True,hide_index=True)
        else:st.caption('기록된 오류 없음')

with page_watch:
    st.subheader('관심 법령 / 금융위 예고 감시')
    st.caption('최초 조회는 기준 스냅샷만 저장합니다. 이후 새 버전·공고가 발견되면 검토함에 기록합니다. 수집 실패 시 0건으로 간주하지 않습니다.')
    with st.form('newwatch'):
        kind=st.selectbox('감시 출처',['law','fsc','fsc_final'],format_func=lambda x:({'law':'법제처 법령 (정확한 법령명)','fsc':'금융위 입법·규정변경예고','fsc_final':'금융위 고시·공고·훈령'}[x]))
        query=st.text_input('법령명 또는 관심 키워드',value='자본시장과 금융투자업에 관한 법률' if kind=='law' else '금융투자업규정')
        keywords=st.text_input('금융위 추가 키워드 (선택, 쉼표 구분)',value='')
        submitted=st.form_submit_button('감시 목록에 등록')
    if submitted:
        try:st.success(f'감시 #{ms.add_watch(kind,query,keywords)} 등록 완료')
        except Exception as e:st.error(str(e))
    watchlist=ms.list_watches()
    for w in watchlist:
        cols=st.columns([2,3,1])
        cols[0].write(f"#{w.id} · {'법제처' if w.kind=='law' else '금융위'}")
        cols[1].write(w.query)
        if cols[2].button('일시정지' if w.enabled else '재개',key='toggle'+str(w.id)):
            ms.toggle(w.id,not w.enabled);st.rerun()
    st.divider()
    with st.expander('사용자 프로필 · 관심 감시 조건 관리'):
        current_profile=ms.load_profile()
        profile_input=st.text_area('로컬 저장할 업무·생활 프로필 JSON',
                                   value=json.dumps(current_profile or {'department':'채권운용','book':'RP'},ensure_ascii=False,indent=2),height=115)
        if st.button('로컬 프로필 저장'):
            try:
                obj=json.loads(profile_input)
                if not isinstance(obj,dict):raise ValueError('프로필은 JSON 객체만 허용')
                ms.save_profile('default',obj);st.success('로컬 SQLite에 프로필 저장 완료')
            except Exception as e:st.error('프로필 저장 실패: '+str(e))
        if watchlist:
            selected_watch=st.selectbox('적용 조건을 설정할 감시항목',watchlist,format_func=lambda w:f'#{w.id} {w.query}')
            cond_raw=st.text_area('수동으로 확인한 적용조건 JSON',
                          value=json.dumps(ms.load_conditions(selected_watch.id),ensure_ascii=False,indent=2),height=80,
                          help='예: {"department":"채권운용"}. 실제 법률의 적용 대상은 자동 확정하지 않습니다.')
            if st.button('감시항목 적용조건 저장'):
                try:
                    obj=json.loads(cond_raw)
                    if not isinstance(obj,dict):raise ValueError('적용조건은 JSON 객체만 허용')
                    ms.save_conditions(selected_watch.id,obj)
                    st.success('적용조건 저장: '+ms.applicability(selected_watch.id)['status'])
                except Exception as e:st.error('조건 저장 오류: '+str(e))
    st.divider()
    st.write('**현재 시점에 1회 수집**')
    st.caption('LAW_OC를 설정한 경우에만 법제처 요청이 가능하며, 금융위 접속에도 인터넷이 필요합니다.')
    if st.button('지금 감시 실행',type='primary'):
        from ruleshift.law_api import LawOpenClient
        from ruleshift.sources import FSCNoticeClient, FSCFinalClient
        oc=os.getenv('LAW_OC','')
        law_client=LawOpenClient(oc) if oc else None
        with st.spinner('등록 소스 확인 중'):
            results=monitor_once(ms,store,law_client=law_client,fsc_client=FSCNoticeClient(),fsc_final_client=FSCFinalClient(),
                     use_laya=use_laya,use_langgraph=use_graph,use_ollama=use_ollama,ollama_model=ollama_model)
        st.json(results)
        if results['errors']:st.error('일부 수집 실패. 하단 로그를 확인하세요.')
        elif results['new_events']:st.success('새로운 변경 이벤트를 검토함에 저장했습니다.')
        else:st.info('새 이벤트 없음 또는 첫 기준 데이터 수집.')
    st.divider()
    st.write('**휴대폰 알림 (선택)**')
    ntfy_topic=st.text_input('ntfy 구독 토픽 (12자 이상)',value=os.getenv('NTFY_TOPIC',''),type='password')
    st.caption('휴대폰 ntfy 앱에서 동일한 토픽을 구독하세요. 공개 ntfy 서버에는 민감한 원문을 전송하지 않습니다.')
    unsent=[e for e in ms.list_events(500) if not e['notified']]
    if st.button(f'미발송 {len(unsent)}건 알림 보내기',disabled=not unsent):
        try:
            send_ntfy(ntfy_topic,'법령·규정 변경',len(unsent),os.getenv('NTFY_BASE_URL','https://ntfy.sh'),os.getenv('NTFY_TOKEN',''))
            ms.mark_notified([e['id'] for e in unsent]);st.success('알림 서버 접수 완료 (휴대폰 수신은 별도 확인)')
        except Exception as e:st.error('알림 실패: '+str(e))

with page_compare:
    st.subheader('조문 단위 비교·관련성 분석')
    with st.form('compareconfig'):
        profile_names=st.multiselect('분석 관심 분야',list(PROFILES),default=list(PROFILES))
        extra=st.text_input('추가 관심 키워드',value='RP, 채권, 운용비율')
        user_profile_raw=st.text_area('내 적용 조건 (JSON, 선택)',value='{"department":"채권운용", "book":"RP"}',height=85)
        conditions_raw=st.text_area('해당 규정에 대한 적용 조건 (JSON, 선택)',value='{}',height=75,
                                    help='예: {"department":"채권운용"}; 정확히 일치하는지 1차 검사만 합니다.')
        config_ok=st.form_submit_button('프로필 조건 확인')
    if config_ok:
        try:
            prof=json.loads(user_profile_raw);cond=json.loads(conditions_raw)
            if not isinstance(prof,dict) or not isinstance(cond,dict):raise ValueError('JSON 객체여야 합니다.')
            ap=evaluate_applicability(prof,cond)
            st.info(f'적용 조건 검사: {ap.status}; 정보 부족: {", ".join(ap.missing) or "없음"}. 법적 적용 확정이 아닙니다.')
        except Exception as e:st.error('조건 오류: '+str(e))
    mode=st.radio('데이터 선택',['가상 예제','파일 업로드','공식 법령 API'],horizontal=True)
    old=new=None
    if mode=='가상 예제':
        cases={'RP 운용비율 한도 가상 변경':'rp_limit','대출 수수료 가상 변경':'loan_terms','개인정보 보존기간 가상 변경':'privacy'}
        selected=cases[st.selectbox('사례 선택',list(cases))]
        folder=ROOT/'samples'/selected
        meta=json.loads((folder/'metadata.json').read_text(encoding='utf-8'))
        old=Document(meta['title'],(folder/'before.txt').read_text(encoding='utf-8'),'이전',**meta['old'])
        new=Document(meta['title'],(folder/'after.txt').read_text(encoding='utf-8'),'개정',**meta['new'])
        st.warning('샘플 문서는 실제 법령 개정이 아닌 합성 테스트 데이터입니다.')
    elif mode=='파일 업로드':
        title=st.text_input('문서 공통 명칭',value='내부 규정 또는 약관')
        col1,col2=st.columns(2)
        with col1:up_old=st.file_uploader('이전 버전',type=['txt','md','pdf','docx','hwpx'],key='up_old')
        with col2:up_new=st.file_uploader('개정 버전',type=['txt','md','pdf','docx','hwpx'],key='up_new')
        stage=st.selectbox('개정본 단계 (원문을 기준으로 수동 지정)',['내부문서/미확인','제안/예고','공포/고시','시행'])
        effective=st.text_input('시행일 (선택, 원문 기준 YYYY-MM-DD)')
        source=st.text_input('공식 출처 URL (선택)')
        ocr=st.checkbox('스캔 PDF OCR 시도 (Tesseract 설치 필요, 최대 40장)',value=False)
        if up_old and up_new:
            try:
                old=Document(title,parse_bytes(up_old.getvalue(),up_old.name,allow_ocr=ocr),up_old.name)
                new=Document(title,parse_bytes(up_new.getvalue(),up_new.name,allow_ocr=ocr),up_new.name,
                             stage=stage,effective_date=effective,source_url=source)
            except Exception as e:st.error('추출 실패: '+str(e))
    else:
        st.caption('국가법령정보 API OC가 필요합니다. 검색 결과는 현행 목록일 수 있으니 서로 다른 버전인지 직접 확인하세요.')
        oc=st.text_input('LAW_OC (화면에 저장하지 않음)',value=os.getenv('LAW_OC',''),type='password')
        query=st.text_input('법령 검색',value='자본시장과 금융투자업에 관한 법률')
        if st.button('공식 법령 검색'):
            try:
                from ruleshift.law_api import LawOpenClient
                st.session_state['law_results']=LawOpenClient(oc).search(query)
            except Exception as e:st.error(str(e))
        candidates=st.session_state.get('law_results',[])
        if candidates:
            label=lambda r:f"{r['title']} / MST {r['mst']} / 공포 {r['promulgated']}"
            old_i=st.selectbox('이전 버전',range(len(candidates)),format_func=lambda i:label(candidates[i]))
            new_i=st.selectbox('개정 버전',range(len(candidates)),index=min(1,len(candidates)-1),format_func=lambda i:label(candidates[i]))
            if st.button('두 원문 조회'):
                try:
                    from ruleshift.law_api import LawOpenClient
                    client=LawOpenClient(oc)
                    st.session_state['official_docs']=(client.fetch(candidates[old_i]['mst']),client.fetch(candidates[new_i]['mst']))
                except Exception as e:st.error(str(e))
        if 'official_docs' in st.session_state: old,new=st.session_state['official_docs']
    if old and new:
        if st.button('변경 영향 분석 실행',type='primary',use_container_width=True):
            try:
                rpt=run_analysis(old,new,profile_names,[x.strip() for x in extra.split(',') if x.strip()],
                                 use_laya,use_graph,use_ollama,ollama_model)
                st.session_state['report']=rpt;st.session_state['active_docs']=(old,new)
            except Exception as e:st.error(f'분석 실패: {e}')
    rpt=st.session_state.get('report')
    if rpt:
        st.divider();st.subheader('분석 결과 · '+rpt.title)
        c1,c2,c3=st.columns(3)
        c1.metric('변경 조문',len(rpt.assessments))
        c2.metric('관련성 높음',sum(a.relevance=='높음' for a in rpt.assessments))
        c3.metric('영향도 높음',sum(a.impact=='높음' for a in rpt.assessments))
        st.caption(f'단계: {rpt.stage} / 시행일: {rpt.effective_date or "미확인"} / 원문 교차검증: {"수동 검증 필요" if not rpt.verified else "완료"}')
        for warning in rpt.warnings:st.warning(warning)
        if rpt.source_url:st.link_button('원문 링크 열기',rpt.source_url)
        for a in rpt.assessments:
            c=a.change
            with st.expander(f'{c.kind} {c.clause_id} · 관련성 {a.relevance}, 영향도 {a.impact}',expanded=a.impact=='높음'):
                left,right=st.columns(2)
                with left:st.text_area('기존',c.before,height=130,key=f'b_{c.clause_id}',disabled=True)
                with right:st.text_area('개정',c.after,height=130,key=f'a_{c.clause_id}',disabled=True)
                st.caption(a.reason)
                st.write('**검토해야 할 내용**')
                for action in a.actions:st.write('• '+action)
                if a.laya_suggestion:st.caption('LAYA 제안: '+a.laya_suggestion)
                if c.clause_id in rpt.ollama_notes:
                    note=rpt.ollama_notes[c.clause_id]
                    st.write('**Ollama 보조 설명 (법적 결론 아님)**',note['analysis'])
                    st.code('원문 확인된 인용: '+note['source_quote'])
        proposals=limit_suggestions(rpt)
        if proposals:
            st.markdown('**한도 변화 숫자 후보 (자동 법령 해석 아님)**')
            st.dataframe(proposals,use_container_width=True,hide_index=True)
            choice=st.selectbox('RP 시나리오에 제안할 조문',range(len(proposals)),format_func=lambda i:proposals[i]['clause_id'])
            if st.button('숫자 후보를 RP 시뮬레이터로 보내기 (확인 후 실행)'):
                st.session_state['rp_limit_proposal']=proposals[choice]
                st.success('시뮬레이션 탭에서 제안값을 확인한 뒤 분석을 실행하세요.')
        j=json.dumps(rpt.to_dict(),ensure_ascii=False,indent=2)
        st.download_button('JSON 다운로드',j,'ruleshift_report.json','application/json')
        st.download_button('Markdown 보고서',markdown_report(rpt),'ruleshift_review.md','text/markdown')
        if st.button('두 원문 버전 이력 저장'):
            a,b=st.session_state['active_docs']
            count=int(store.save(a))+int(store.save(b))
            st.success(f'새 스냅샷 {count}개 저장했습니다.')

with page_simulate:
    st.subheader('법령·지침 변경의 정량 영향 실험실')
    st.warning('개정 조문에서 자동 추정한 법적 한도가 아닙니다. 사용자가 직접 확인한 값만 입력하세요. 어떠한 주문·운용 변경도 실행하지 않습니다.')
    simulation=st.radio('계산 유형',['RP 채권 만기구간 편입비율','대출 금리 변경에 따른 단순 이자'],horizontal=True)
    if simulation=='RP 채권 만기구간 편입비율':
        st.markdown('**포지션 CSV** · 필수 열: `security_id,maturity_date,market_value_krw` (기준일 현재 원화 평가금액)')
        uploaded=st.file_uploader('채권 포트폴리오 CSV (원본 대신 가명화 권장)',type=['csv'],key='portfolio')
        example=(ROOT/'examples'/'portfolio_sample.csv').read_bytes()
        st.download_button('가상 포지션 CSV 예제',example,'portfolio_sample.csv','text/csv')
        c1,c2,c3=st.columns(3)
        base_date=c1.date_input('기준일',value=date.today())
        proposal=st.session_state.get('rp_limit_proposal',{})
        if proposal:st.warning(f"{proposal['clause_id']}에서 추출한 후보값. 법령 시행·분모·적용 대상 미확인: {proposal['old_pct']}% → {proposal['new_pct']}%")
        oldlim=c2.number_input('이전 한도 (%)',0.0,100.0,float(proposal.get('old_pct',35.0)),0.5)
        newlim=c3.number_input('변경 한도 (%)',0.0,100.0,float(proposal.get('new_pct',30.0)),0.5)
        a,b=st.columns(2)
        minmonths=a.number_input('구간 시작 개월 수 (포함)',0,360,6)
        maxmonths=b.number_input('구간 종료 개월 수 (포함)',1,1200,60)
        if st.button('정적 포트폴리오 영향 계산',type='primary'):
            try:
                positions=load_positions_csv((uploaded.getvalue() if uploaded else example).decode('utf-8-sig'))
                st.session_state['rp_sim']=simulate_limit(positions,base_date,oldlim,newlim,minmonths,maxmonths)
            except Exception as e:st.error(str(e))
        if 'rp_sim' in st.session_state:
            st.dataframe(st.session_state['rp_sim'],use_container_width=True,hide_index=True)
            st.caption('6개월 및 5년 경계값은 포함, 미래 만기상환된 종목은 제외, 포트폴리오 신규매매/가격변동/현금 유입은 무시')
            st.download_button('계산결과 JSON',json.dumps(st.session_state['rp_sim'],ensure_ascii=False,indent=2),'rp_scenario.json')
    else:
        c1,c2,c3,c4=st.columns(4)
        principal=c1.number_input('대출잔액 (원)',min_value=0.0,value=100000000.0,step=1000000.0)
        oldrate=c2.number_input('기존 연 금리(%)',value=4.0,step=0.1)
        newrate=c3.number_input('변경 연 금리(%)',value=4.5,step=0.1)
        days=c4.number_input('계산 일수',1,366,30)
        if st.button('단순 이자차액 계산'):
            try:st.json(simulate_loan_rate(principal,oldrate,newrate,days))
            except Exception as e:st.error(str(e))

with page_help:
    st.subheader('연동 설정 및 제약')
    st.markdown('''**운영 원칙**
- 기본 실행은 무료·로컬이며 외부 LLM 호출을 하지 않습니다.
- 법제처 OC 인증값은 `.env`에 `LAW_OC=...`로 지정합니다. 최초 기준 버전 저장 후 다음 조회부터 개정 이벤트가 생성됩니다.
- 금융위 게시판은 **규정변경예고 게시물**을 감시하는 것이며, 첨부 개정조문 전체를 정식 법령으로 확정하지 않습니다.
- ntfy 모바일 알림은 앱에서 토픽 구독이 필요하며, 공개 서버 사용 시 민감한 원문은 전송하지 않습니다.
- 무인 감시는 앱이 아니라 별도 `python -m ruleshift monitor` 명령을 Windows 작업 스케줄러/cron에서 실행하도록 구성했습니다.
- LAYA는 분류 참고, Ollama는 원문 인용 검증된 설명 참고, LangGraph는 단계별 실행에 사용합니다. 설치되지 않으면 비활성 상태입니다.
- 법제처/금융위 실서버, 모바일 수신, Ollama 모델 실행은 각 환경의 인증·네트워크·설치가 필요합니다.
- **적용 대상과 시행 여부는 자동으로 법적 확정 판정하지 않습니다.**''')
    st.code('python -m ruleshift monitor --notify\npython -m ruleshift demo --case rp_limit --laya --langgraph',language='powershell')
    st.caption('상세 설정 및 Windows 작업 스케줄러 등록법: README.md / scripts/install_daily_task.ps1')
