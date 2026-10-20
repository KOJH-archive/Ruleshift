"""Unverified numeric suggestions from text differences. Never automatically apply rules."""
from __future__ import annotations
import re
from .models import Report

PCT=re.compile(r'(?<![\d.])(\d{1,3}(?:\.\d{1,4})?)\s*(?:%|％|퍼센트)',re.I)
LIMIT_CONTEXT=('한도','편입비율','운용비율','비중','이하','초과','제한')


def limit_suggestions(report: Report) -> list[dict]:
    results=[]
    for a in report.assessments:
        c=a.change
        if c.kind not in ('수정','신설','삭제') or not c.before or not c.after:
            continue
        if not any(w in c.before+c.after for w in LIMIT_CONTEXT):continue
        old=[float(x) for x in PCT.findall(c.before)]
        new=[float(x) for x in PCT.findall(c.after)]
        if len(old)!=1 or len(new)!=1 or old[0]==new[0] or not all(0<=x<=100 for x in old+new):
            continue
        results.append({'clause_id':c.clause_id,'old_pct':old[0],'new_pct':new[0],
                        'review_required':True,
                        'warning':'숫자 후보값만 추출. 실제 한도 여부, 적용 대상, 분자·분모·시행 시점은 미확인.'})
    return results
