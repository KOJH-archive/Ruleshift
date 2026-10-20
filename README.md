# RuleShift Radar v1.0

법령·금융위 규정변경예고·고시 공고·내부 업무지침·약관의 변경을 수집하고, **개정 전후 비교 → 1차 관련성 분류 → 원문 기반 검토 → 정량 시뮬레이션 → 검토함·알림**까지 연결하는 **로컬 우선** 시스템입니다.

> ⚠️ **법률 자문/준법 확정 서비스가 아닙니다.** 적용 대상, 부칙·경과조치, 별표, 최종 시행일은 원문과 담당자의 검토가 필요합니다. 이 도구는 **실거래/약정/포트폴리오를 변경하지 않습니다.** 샘플은 모두 **가상 문서·가상 채권 데이터**입니다.

## Quick Start — Windows

1. 압축 해제 후 `RuleShift_Radar_v1.0` 폴더에 들어갑니다.
2. `start_windows.bat` 실행 (Python 3.11 필요, 실패 시 콘솔 오류 유지). 설치 후 웹 브라우저에서 `http://localhost:8501`을 열어 사용할 수 있습니다.
3. **문서 비교** 탭에서 가상 예제 선택 → **변경 영향 분석 실행**.
4. **영향 시뮬레이션**에서 제공된 가상 채권 CSV로 한도 변경 시나리오 실행.
5. 실제 공개 법령 수집이 필요하다면 `.env.example`을 `.env`로 복사하고 발급받은 `LAW_OC`를 넣습니다.

**PowerShell 수동 설치** (더 자세한 오류 메시지 확인):

```powershell
cd RuleShift_Radar_v1.0
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

다른 OS에서는 `python3 -m venv .venv`, `.venv/bin/python -m pip install -r requirements.txt`, `.venv/bin/python -m streamlit run app.py`.

## 지금 제공하는 기능 / 실제 검증 상태

| 기능 | 구현 범위 | 확인 상태 |
| --- | --- | --- |
| 문서 파싱 | TXT/MD/DOCX/텍스트 PDF/HWPX / 스캔 PDF 별도 OCR 옵션 | 가상 HWPX 포함 자동 테스트; 실제 기업 문서 포맷은 개별 검증 필요 |
| 개정 비교 | 조문 수정/삭제/신설/동일 본문 번호 이동 | 자동 테스트 통과; 첨부/별표·복잡한 재배치·HWP 표 등은 미확정 |
| 사용자 프로필 | 업무·생활 키워드, 로컬 JSON 프로필, 감시 항목별 명시적 조건 매칭 | 정확한 값 일치 스크리닝 테스트; 법적 적용 확정 아님 |
| 한도 숫자 추출 | 조문별 단일 백분율 변경만 후보로 표기 | 자동 테스트 통과, 인간 승인 없이 적용하지 않음 |
| RP 정량 시뮬레이션 | 가명 CSV 입력, 잔존 만기구간 경계 설정, 0/1/3/6/12개월 만기 도래별 비중·한도초과액 | 자동 테스트 통과; 회계·평가·RP담보·매매흐름은 미포함 |
| 대출 단리 시뮬레이션 | 잔액 일정, ACT/365 단리, 금리 변화 시 이자차액 | 자동 테스트 통과; 약정금리·상환방식과 다를 수 있음 |
| 변동 감시 | 법제처 현재 공포법령 버전 (MST), 금융위 개정예고 게시물, 금융위 고시·공고 게시물 | 테스트용 모의 응답 처리, **외부 실서버 연결 검증 불가** |
| 무인 실행 | Python CLI 1회 폴링, Windows 작업 스케줄러 자동 등록 스크립트 | 코드 작성; 실제 Windows 스케줄러 실행 미검증 |
| 검토 대기열 | SQLite에 원문·변경 이벤트·확인 여부·전송 여부·오류 기록 | 자동 테스트 통과 |
| 휴대폰 알림 | ntfy HTTPS 서버에 비민감 요약만 전달 | API 모의 테스트 통과; **실제 휴대폰 수신 미검증** |
| LangGraph | diff/classify/verify/report 그래프 및 monitor 옵션 | 코드 작성; 패키지 미설치로 실모델 실행 미검증 |
| LAYA | `Router.predict` multilingual 참고 라우팅, 실패 시 규칙 분류 | 라이브러리 문서 준거 코드; **체크포인트 실제 추론 미검증** |
| Ollama | localhost 전용 JSON 보조 분석, 원문 직접 인용 검사 실패시 삭제 | 모의 응답 테스트; **로컬 모델 실실행 미검증** |
| Streamlit | 문서 비교, 감시 등록, 이력·검토함, 프로필, 시뮬레이션, 보고서 | 코드 작성/문법 컴파일; **이 실행 환경에서는 Streamlit 설치 실패로 브라우저 화면 미검증** |

## CLI 간단 사용

```powershell
# 네트워크나 OC 없이 가상 사례 분석
.\.venv\Scripts\python.exe -m ruleshift demo --case rp_limit --output sample_report.json

# 포트폴리오 시나리오 (원화 시장가치, 날짜는 가상)
.\.venv\Scripts\python.exe -m ruleshift rp --csv examples\portfolio_sample.csv --date 2026-10-20 --old-limit 35 --new-limit 30

# 명시적 관심 법령 등록 (API OC 발급 필요)
.\.venv\Scripts\python.exe -m ruleshift watch add --kind law --query "자본시장과 금융투자업에 관한 법률"
# 금융위 개정예고
.\.venv\Scripts\python.exe -m ruleshift watch add --kind fsc --query "금융투자업규정"
# 금융위 확정 고시/공고 게시판
.\.venv\Scripts\python.exe -m ruleshift watch add --kind fsc_final --query "금융투자업규정"

# 수동 폴링 (첫회는 기준선 저장, 이후에 변경 이벤트)
.\.venv\Scripts\python.exe -m ruleshift monitor --notify
.\.venv\Scripts\python.exe -m ruleshift events

# 보조 모델 (선택 설치 및 로컬 모델 사용)
.\.venv\Scripts\python.exe -m pip install -r requirements-agent.txt
.\.venv\Scripts\python.exe -m ruleshift demo --case rp_limit --langgraph --laya --ollama

# 검증
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 정기 감시 등록

Windows PowerShell을 열고 프로젝트 경로에서 다음 명령을 실행합니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_daily_task.ps1 -TaskName RuleShift-Daily -Time 07:30
```

이 명령은 **해당 Windows PC의 작업 스케줄러에 매일 07:30 실행을 등록**합니다. 현재 PC가 꺼져 있거나 네트워크 연결이 없으면 실행·알림이 실패할 수 있습니다. 웹앱 접속과 무관하게 `python -m ruleshift monitor --notify`를 호출합니다. **스케줄을 실제로 등록하는 것은 사용자 PC에서 명령을 실행했을 때뿐**입니다. 배터리 절전/잠금 상태 정책은 사용자 설정에 따릅니다.

서버 운영/클라우드 배포 시에는 동일 CLI를 cron 또는 관리형 스케줄러로 실행할 수 있지만, 공개 서버에 사내 비공개 문서를 저장하지 마세요.

## .env 구성

```dotenv
LAW_OC=발급받은_법제처_API_인증값
NTFY_TOPIC=예측불가능한_영숫자_토픽_12자이상
NTFY_BASE_URL=https://ntfy.sh
NTFY_TOKEN=
OLLAMA_MODEL=qwen2.5:7b
```

- `LAW_OC` : [국가법령정보 공동활용](https://open.law.go.kr/LSO/openApi/guideList.do)에서 신청·발급 후 설정
- `NTFY_TOPIC` : Android에서 [ntfy](https://docs.ntfy.sh/subscribe/phone/) 앱 설치 → 동일 토픽 구독. 토픽은 **비밀처럼 취급**하세요. 공개 서버는 원문 대신 이벤트 건수/제목만 보냅니다.
- `NTFY_TOKEN` : 사설 ntfy 서버가 인증을 요구할 때만 사용. 외부 서버로 보내지 않는 사내 네트워크 자체호스팅 권장.
- Ollama: https://ollama.com 에서 별도 설치 후 `ollama pull qwen2.5:7b`; 서버 기본 `http://127.0.0.1:11434`.
- LAYA: `pip install -r requirements-agent.txt`; 최초 모델 가중치 다운로드 필요. Intel GPU 가속은 별도 XPU PyTorch 지원 설치/테스트 필요.
- 유료 OpenAI/Anthropic/Gemini API 호출 **없음**.

## RP Guardian 연결 계약 (현재 적용 가능 범위)

현재 RP Guardian의 전산 파일 구조를 알 수 없어 사내 원본을 직접 파싱하지 않았습니다. 이 시스템이 받아들이는 최소 표준 인터페이스는:

```csv
security_id,maturity_date,market_value_krw
BOND_A,2027-02-15,18000000000
```

`security_id`는 유일한 가명 종목키, `maturity_date`는 YYYY-MM-DD, `market_value_krw`는 기준일 현재 양의 원화 가치입니다.

**한도 계산 기본 가정:** 기준일에 이미 만기 지난 종목은 제외. 6개월~5년인 종목은 경계값을 포함. 분모는 **해당 기준일 잔존 종목의 시장가치 합계**. 만기 지난 종목은 향후 계산에서 제거. 이 모형은 단순한 **대조용 정적 스냅샷**입니다. 실제 운용지침의 한도는 평가금액/원금/조달잔액 등 다른 기준일 수 있으므로 공식 원문과 대사해야 합니다. 실제 거래를 제안하거나 자동 실행하지 않습니다.

금융위 개정문에서 `%`/`퍼센트`가 각각 단일 발견되는 조항만 후보값으로 제시합니다. **후보 한도와 포트폴리오를 연결하는 액션에는 사용자 확인이 필수**입니다.

## 보안과 정확성

- `.env`와 로컬 SQLite는 `.gitignore` 대상. 문서는 원본 백업을 권장. 회사 규정·대출계약서 등은 허가된 기기에서만 취급.
- API 접근은 공식 법제처 도메인 및 금융위 게시판으로 제한. 금융위 게시판 첨부 PDF/HWPX를 정식 조문으로 자동 적용하지 않음.
- 법제처 `lawSearch` 응답의 최신 **MST**가 갱신된 경우에만 본문을 가져오고, 저장된 과거 버전과 비교.
- 자료 수집 실패 시 "변경 없음"으로 기록하지 않음. 에러 로그 확인.
- 최초 감시는 기준선 설정이므로 변경 알림을 보내지 않음. 이후 새 공고/법령 본문 버전만 이벤트로 저장. 이벤트·알림은 중복 방지.
- 조문 번호가 이동하며 내용도 수정되면 이동/신설/삭제 판정이 정확하지 않을 수 있음.
- 최종 효력의 근거는 **공식 원문과 공포·시행·부칙**. 입법예고는 시행으로 간주하지 않음.
- 프로필 조건은 사용자가 직접 지정하는 **정확값 일치 검사**. 법적 적용요건의 자동 추론은 하지 않음.
- LLM 생성 설명은 `source_quote` 직접 인용을 자동 검사하지만 분석 문장의 인과·법률적 타당성은 **검증하지 못함**.
- 스캔 PDF OCR은 별도 `requirements-ocr.txt`, Tesseract 프로그램 및 한국어 학습데이터가 필요. 정확도 보장 불가.

## 공식 참고

- [국가법령정보 공동활용 API 가이드](https://open.law.go.kr/LSO/openApi/guideList.do)
- [금융위원회 입법예고·규정변경예고](https://www.fsc.go.kr/po040301)
- [금융위원회 금융위 소관규정·고시·공고·훈령](https://www.fsc.go.kr/po040200)
- [LAYA 개발문서](https://github.com/NandhaKishorM/laya)
- [ntfy 전송문서](https://docs.ntfy.sh/publish/)

## 폴더 구성

```text
RuleShift_Radar_v1.0/
  app.py                          Streamlit UI
  ruleshift/
    cli.py                        CLI: monitor/watch/demo/compare/rp/loan/events
    compare.py,parser.py          조문 파싱 및 Diff
    law_api.py,sources.py         공공 소스 수집
    monitor.py,storage.py         영속 감시·스냅샷·이벤트/검토함
    impact.py,applicability.py    분류 및 프로필 조건
    number_extract.py,quant.py   한도 숫자 후보 및 정량 계산
    workflow.py,ollama_agent.py   LangGraph/LAYA/Ollama 선택 경로
    notify.py,reporting.py       알림/보고서
  samples/                        모든 내용이 가상인 3종 테스트 사례
  examples/                       가상 RP 포지션 CSV
  scripts/                        Windows 1회 모니터/작업스케줄러 등록
  tests/                          핵심 자동 테스트
  .env.example                    인증 값 입력 템플릿
  requirements.txt
  requirements-agent.txt
  requirements-ocr.txt
  start_windows.bat
```

## 추가 운영상 제한

- 금융감독원(FSS) 규정 게시판은 아직 정식 수집 커넥터가 없습니다. 공식 법제처·금융위 3가지 수집 소스와 로컬 문서 비교를 제공합니다.
- 금융위 목록 HTML은 사이트 개편에 따라 수집 파서 변경이 필요할 수 있습니다. 실제 접속 테스트는 실행 환경 네트워크 제한으로 수행하지 못했습니다.
- 사용자가 등록한 프로필 JSON과 감시 조건은 로컬에 저장되지만, 이를 통한 법률 적용 가능성 분류는 **정확한 값 일치 수준**입니다.
- 법제처 법령 목록 조회는 새로운 MST 버전이 등장하는지 폴링합니다. 금융위 게시판은 신규 게시물 ID 탐지 방식이며, **기존 게시물의 첨부 수정은 탐지하지 못할 수 있습니다.**
