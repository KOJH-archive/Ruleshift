"""RuleShift: local-first Streamlit dashboard. No data sent to commercial AI by default."""
from __future__ import annotations
import json
import os
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv
from ruleshift.models import Document
from ruleshift.workflow import run_analysis
from ruleshift.storage import SnapshotStore
from ruleshift.parser import parse_bytes
from ruleshift.reporting import markdown_report
from ruleshift.applicability import evaluate_applicability
from ruleshift.monitor import MonitorStore, monitor_once

ROOT=Path(__file__).resolve().parent
load_dotenv(ROOT/'.env')
DB=ROOT/'data'/'ruleshift.sqlite3'
WATCH_DB=ROOT/'data'/'monitor.sqlite3'
store=SnapshotStore(DB)
ms=MonitorStore(WATCH_DB)

st.set_page_config(page_title='RuleShift | 법령 개정 감시',page_icon='⚖️',layout='wide')
st.title('⚖️ RuleShift | 법령 개정 감시')
st.caption('관심 법령의 새 버전 탐지 · 조문/부칙 비교 · 근거와 출처를 검토함에 저장')
st.info('특정 분야를 전제하지 않습니다. 변경 사실과 법적 적용 여부는 다르므로 시행일·경과규정은 원문에서 확인하세요.')

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
        ollama_model=st.text_input('Ollama 모델명',value=os.getenv('OLLAMA_MODEL','auto'))
        st.caption('auto/current이면 현재 로드 모델을 우선 사용하고, 없으면 로컬 설치 모델 중 최근 모델을 자동 선택합니다.')

page_dashboard,page_watch,page_compare,page_help=st.tabs(['📌 변경·검토함','🔔 자동 감시','⚖️ 문서 비교','🔧 설정·제약'])

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
        if errors:st.dataframe(errors,hide_index=True)
        else:st.caption('기록된 오류 없음')

with page_watch:
    st.subheader('관심 법령 / 금융위 예고 감시')
    st.caption('최초 조회는 기준 스냅샷만 저장합니다. 이후 새 버전·공고가 발견되면 검토함에 기록합니다. 수집 실패 시 0건으로 간주하지 않습니다.')
    with st.form('newwatch'):
        kind=st.selectbox('감시 출처',['law','fsc','fsc_final'],format_func=lambda x:({'law':'법제처 법령 (정확한 법령명)','fsc':'금융위 입법·규정변경예고','fsc_final':'금융위 고시·공고·훈령'}[x]))
        query=st.text_input('법령명 또는 관심 키워드',value='',placeholder='정확한 법령명 또는 게시판 검색어')
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
                                   value=json.dumps(current_profile,ensure_ascii=False,indent=2),height=115)
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
    st.caption('변경 정보는 이 PC의 검토함에 저장됩니다. 외부 휴대폰 알림은 기본 사용하지 않습니다.')

with page_compare:
    st.subheader('조문 단위 비교·관련성 분석')
    profile_names=[]
    with st.form('compareconfig'):
        extra=st.text_input('관심 키워드 (선택, 쉼표 구분)',value='',help='비워도 모든 변경 조문을 표시합니다.')
        user_profile_raw=st.text_area('내 적용 조건 (JSON, 선택)',value='{}',height=85)
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
    mode=st.radio('데이터 선택',['가상 예제','파일 업로드','공식 법령 API'],index=2,horizontal=True)
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
        query=st.text_input('법령 검색',value='',placeholder='예: 개인정보 보호법')
        if st.button('공식 법령 검색'):
            try:
                if len(query.strip()) < 2:
                    raise ValueError('검색할 법령명을 2자 이상 입력하세요.')
                from ruleshift.law_api import LawOpenClient
                st.session_state['law_results']=LawOpenClient(oc).search(query)
                st.session_state['law_query']=query
                st.session_state.pop('official_docs',None)
                st.session_state.pop('official_selection',None)
            except Exception as e:st.error(str(e))
        candidates=st.session_state.get('law_results',[]) if st.session_state.get('law_query')==query else []
        if candidates:
            label=lambda r:f"{r['title']} / MST {r['mst']} / 공포 {r['promulgated']} / 시행 {r['effective']}"
            old_i=st.selectbox('이전 버전',range(len(candidates)),index=min(1,len(candidates)-1),format_func=lambda i:label(candidates[i]))
            new_i=st.selectbox('개정 버전',range(len(candidates)),index=0,format_func=lambda i:label(candidates[i]))
            if st.button('두 원문 조회'):
                try:
                    if old_i==new_i:
                        raise ValueError('서로 다른 두 버전을 선택하세요.')
                    if candidates[old_i]['title'] != candidates[new_i]['title']:
                        raise ValueError('같은 법령의 두 버전을 선택하세요.')
                    from ruleshift.law_api import LawOpenClient
                    client=LawOpenClient(oc)
                    st.session_state['official_docs']=(client.fetch(candidates[old_i]['mst']),client.fetch(candidates[new_i]['mst']))
                    st.session_state['official_selection']=(candidates[old_i]['mst'],candidates[new_i]['mst'])
                except Exception as e:st.error(str(e))
        if (candidates and 'official_docs' in st.session_state and
                st.session_state.get('official_selection')==(candidates[old_i]['mst'],candidates[new_i]['mst'])):
            old,new=st.session_state['official_docs']
    if old and new:
        if st.button('개정 내용 비교 실행',type='primary',width='stretch'):
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
        j=json.dumps(rpt.to_dict(),ensure_ascii=False,indent=2)
        st.download_button('JSON 다운로드',j,'ruleshift_report.json','application/json')
        st.download_button('Markdown 보고서',markdown_report(rpt),'ruleshift_review.md','text/markdown')
        if st.button('두 원문 버전 이력 저장'):
            a,b=st.session_state['active_docs']
            count=int(store.save(a))+int(store.save(b))
            st.success(f'새 스냅샷 {count}개 저장했습니다.')

with page_help:
    st.subheader('연동 설정 및 제약')
    st.markdown('''**운영 원칙**
- 기본 실행은 무료·로컬이며 외부 LLM 호출을 하지 않습니다.
- 법제처 OC 인증값은 `.env`에 `LAW_OC=...`로 지정합니다. 최초 기준 버전 저장 후 다음 조회부터 개정 이벤트가 생성됩니다.
- 금융위 게시판은 **규정변경예고 게시물**을 감시하는 것이며, 첨부 개정조문 전체를 정식 법령으로 확정하지 않습니다.
- 외부 모바일 알림은 기본 비활성입니다. 검토함은 이 PC의 로컬 SQLite에 저장됩니다.
- 무인 감시는 앱이 아니라 별도 `python -m ruleshift monitor` 명령을 Windows 작업 스케줄러/cron에서 실행하도록 구성했습니다.
- LAYA는 분류 참고, Ollama는 원문 인용 검증된 설명 참고, LangGraph는 단계별 실행에 사용합니다. 설치되지 않으면 비활성 상태입니다.
- 법제처/금융위 실서버, 모바일 수신, Ollama 모델 실행은 각 환경의 인증·네트워크·설치가 필요합니다.
- **적용 대상과 시행 여부는 자동으로 법적 확정 판정하지 않습니다.**''')
    st.code('python -m ruleshift watch add --kind law --query "정확한 법령명"\npython -m ruleshift monitor\npython -m ruleshift events',language='powershell')
    st.caption('상세 설정 및 Windows 작업 스케줄러 등록법: README.md / scripts/install_daily_task.ps1')
