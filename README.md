# RuleShift Radar

**법령·금융규정·약관 변경을 탐지하고 업무·생활 영향도를 분석하는 로컬 우선 멀티에이전트 프로젝트**

개정 전후 조문 비교 → 관련성/적용 조건 평가 → 정량 시뮬레이션 → 검토함/알림의 전체 흐름을 지원하도록 설계했습니다.

> 법률 자문이나 확정적 준법 판단을 대체하지 않습니다. 개정예고/공포/시행 상태를 구분하고, 적용 대상·부칙·경과조치를 반드시 원문에서 확인해야 합니다. 샘플은 가상 자료입니다.

## 주요 기능

- 법제처 법령·금융위원회 규정변경예고/고시 수집 및 버전 감시 코드
- 조문 추가·삭제·수정·번호 이동 비교
- 업무(채권/RP/금융투자) 및 생활(대출/보험/소비자계약) 관련성 분류
- LangGraph/LAYA/Ollama 선택형 연동, 규칙 기반 폴백
- RP 채권 만기·운용비율 한도 및 대출이자 변화 시뮬레이션
- SQLite 검토대기열, Windows 스케줄러, ntfy 알림 연결부
- Streamlit 대시보드 및 Markdown/JSON 보고서

## 실행 방법

Python 3.11 권장. 프로젝트 압축본을 해제한 뒤:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Windows에서는 `start_windows.bat`을 사용할 수도 있습니다. `.env.example`을 `.env`로 복사해 법제처 `LAW_OC` 등을 필요에 따라 입력하세요. **실제 키를 Git에 올리지 마세요.**

테스트:
```bash
python -m unittest discover -s tests -v
```

## 구현 및 검증 상태

핵심 모듈의 단위 테스트 **52개 통과**. Streamlit 실제 화면, 법제처·금융위 실서버 연결, LAYA/Ollama 실제 추론, Windows 스케줄러, 모바일 실수신은 외부 환경에서 검증해야 합니다. RP Guardian 원본 Excel 연동은 아직 미완료입니다.

## 문서

- [개발명세서](docs/DEVELOPMENT_SPEC.md): 아키텍처·모듈·데이터 처리·보안·검증 기준
- `SAMPLE_REPORT.md`: 가상 사례 분석 보고서
- `samples/`, `examples/`: 가상 테스트 입력 및 결과
- `tests/`: 회귀 테스트

## 라이선스

저장소의 LICENSE를 참조하세요.
