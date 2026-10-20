"""Explicit profile conditions: a screening aid, NOT a legal applicability verdict."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class Applicability:
    status: str
    matched: tuple[str, ...]
    missing: tuple[str, ...]
    mismatched: tuple[str, ...]
    note: str


def evaluate_applicability(profile: dict[str, Any], conditions: dict[str, Any]) -> Applicability:
    """Supported condition values are strings, numbers, bools, or lists of permitted exact values.

    No user-defined Python/eval/expression execution. Unknown is never treated as a match.
    """
    hit, missing, mismatch = [], [], []
    for key, expected in conditions.items():
        if not isinstance(key, str) or key.startswith('__'):
            raise ValueError('잘못된 프로필 조건 키')
        if not isinstance(expected,(str,int,float,bool,list)) or (isinstance(expected,list) and (len(expected)>50 or any(not isinstance(v,(str,int,float,bool)) for v in expected))):
            raise ValueError('조건은 값 또는 값의 목록만 지원합니다.')
        if key not in profile or profile[key] in (None,''):
            missing.append(key); continue
        actual = profile[key]
        allowed = expected if isinstance(expected,list) else [expected]
        if actual in allowed: hit.append(key)
        else: mismatch.append(key)
    if not conditions:
        status = '조건 미설정'
    elif missing:
        status = '자료 부족·판단 보류'
    elif mismatch:
        status = '사용자 조건 불일치(재확인)'
    else:
        status = '조건 일치(법적 적용 미확정)'
    return Applicability(status,tuple(hit),tuple(missing),tuple(mismatch),
                         '프로필 조건 검사만 수행했습니다. 적용 대상 정의, 예외·부칙을 원문에서 확인해야 합니다.')
