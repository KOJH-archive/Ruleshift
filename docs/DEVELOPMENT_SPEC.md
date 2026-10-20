# RuleShift 개발 명세서 v1.0

## 목표
법령·금융규정·약관·사내 지침의 신구 변경사항을 감지하고 업무·생활 관련성, 적용 조건, 영향도, 대응 체크리스트를 제공하는 로컬 우선 멀티에이전트 시스템. 법률 자문을 대체하지 않음.

## 아키텍처
1. Source Monitor: 국가법령정보센터·금융위원회 자료 또는 사용자 문서 수집, 버전 및 효력 상태 기록
2. Diff Analyzer: 조문 정규화 후 신설·삭제·수정·번호 이동 구분
3. Relevance Classifier: 사용자 업무/생활 프로필과 변경 조문 관련성 분류 (규칙 기반, LAYA 선택형)
4. Impact/Applicability Analyst: 적용대상·시행일·경과규정·예외사항 분석, 불확실성 표시
5. Verification: 원문 근거 확인, 개정예고와 확정·시행 구분, 검토 보류
6. Action Planner: 체크리스트·보고서·알림 생성

## 모듈
- app.py: Streamlit 대시보드
- ruleshift/parser.py, compare.py: 문서 파싱 및 조문 비교
- ruleshift/law_api.py, sources.py, monitor.py: 법령/금융위 수집과 감시
- ruleshift/impact.py, applicability.py, number_extract.py: 관련성·적용성·숫자 후보
- ruleshift/workflow.py, ollama_agent.py: LangGraph/Ollama 선택형 분석
- ruleshift/quant.py: RP 한도 및 대출 이자 시뮬레이션
- ruleshift/storage.py, notify.py, reporting.py: SQLite, ntfy, 보고서
- ruleshift/cli.py: 명령줄 및 자동 실행

## 데이터 및 보안
원문, 출처 URL, 버전, 수집시각, 효력 상태를 저장한다. 수치 변경 후보만으로 법적 한도나 적용 분모를 확정하지 않는다. 사내 문서·개인정보 외부 전송은 기본 비활성화한다. 비밀키는 .env에만 보관하고 커밋하지 않는다.

## 실행과 검증
pip install -r requirements.txt
python -m unittest discover -s tests -v
streamlit run app.py

기존 패키지에서 52개 단위 테스트가 통과했다. 실제 법제처 API 인증/접속, 금융위 사이트 접속, Streamlit UI 실구동, LAYA/Ollama 모델 실행, Windows 스케줄러 및 휴대폰 실수신은 별도 환경 검증이 필요하다. RP Guardian 원본 엑셀 연동은 아직 미완료다.

## 다음 단계
실서비스 수집기 검증 → 원문 근거 추적 고도화 → RP 데이터 매핑 → 오류/알림 운영 테스트.
