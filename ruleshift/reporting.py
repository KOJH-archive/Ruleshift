"""Human-readable review report. Output is descriptive, not legal advice."""
from __future__ import annotations
from .models import Report

def markdown_report(report: Report) -> str:
    lines = [f'# RuleShift 변경 영향 검토: {report.title}', '',
             '> 주의: 자동 판정은 법률 자문이나 적용 확정이 아닙니다. 모든 영향 항목은 담당자 원문 검토가 필요합니다.', '',
             f'- 이전 버전: {report.old_version}', f'- 개정 버전: {report.new_version}',
             f'- 문서 상태: {report.stage}',f'- 시행일(입력 기준): {report.effective_date or "미확인"}',
             f'- 공포/발행일(입력 기준): {report.published_date or "미확인"}',
             f'- 출처 유형: {report.source_type}',
             f'- 원문: {report.source_url or "제공되지 않음"}',
             f'- 원문 교차검증: {"완료" if report.verified else "미완료"}', '',
             '## 요약', '',
             f'- 감지한 변경 조문: {len(report.assessments)}개',
             f'- 관련성 높음: {sum(a.relevance == "높음" for a in report.assessments)}개',
             f'- 영향도 높음: {sum(a.impact == "높음" for a in report.assessments)}개', '']
    if report.warnings:
        lines+=['## 검증 경고','']+['- '+x for x in report.warnings]+['']
    for idx,a in enumerate(report.assessments,1):
        lines += [f'## {idx}. {a.change.kind} — {a.change.clause_id}', '',
                  f'- 관련성: {a.relevance} ({a.area})',f'- 영향도(1차 우선순위): {a.impact}',
                  f'- 법적 확정 판단: 불가 / 검토 필요', '',
                  '**변경 전**', '', '```text',a.change.before,'```', '',
                  '**변경 후**', '', '```text',a.change.after,'```', '',
                  f'**분류 이유:** {a.reason}', '']
        if a.laya_suggestion:
            lines += [f'**LAYA 참고 분류:** {a.laya_suggestion}', '']
        if a.change.clause_id in report.ollama_notes:
            note = report.ollama_notes[a.change.clause_id]
            lines += [f'**Ollama 참고 설명:** {note["analysis"]}',
                      f'**원문 대조 인용:** {note["source_quote"]}',
                      '> 주의: 직접 인용만 검사되었으며 해석·적용 여부는 확인되지 않았습니다.', '']
        lines += ['**확인 사항**','']+['- '+x for x in a.actions]+['']
    return '\n'.join(lines)
