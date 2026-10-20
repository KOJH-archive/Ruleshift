from __future__ import annotations
from difflib import SequenceMatcher, unified_diff
from .models import Change, Document
from .parser import clean, parse_clauses

def _line_diff(old: str, new: str) -> str:
    return '\n'.join(unified_diff(old.splitlines(), new.splitlines(), fromfile='개정 전', tofile='개정 후', lineterm=''))

def compare(old: Document, new: Document) -> list[Change]:
    if old.title.strip() != new.title.strip():
        raise ValueError('서로 다른 문서명이므로 비교할 수 없습니다. 동일 문서 여부를 확인하세요.')
    before = {c.id: c for c in parse_clauses(old.text)}
    after = {c.id: c for c in parse_clauses(new.text)}
    results: list[Change] = []
    for key in before.keys() & after.keys():
        a, b = before[key], after[key]
        if clean(a.heading + ' ' + a.text) != clean(b.heading + ' ' + b.text):
            results.append(Change('수정', key, a.heading+'\n'+a.text, b.heading+'\n'+b.text,
                                  diff=_line_diff(a.heading+'\n'+a.text, b.heading+'\n'+b.text)))
    removed = [before[k] for k in before.keys() - after.keys()]
    added = [after[k] for k in after.keys() - before.keys()]
    paired_old, paired_new = set(), set()
    # Conservative renumber detection: near-identical *substantive bodies*, not just shared headings.
    potentials = []
    for i, a in enumerate(removed):
        for j, b in enumerate(added):
            if len(clean(a.text)) < 25 or len(clean(b.text)) < 25:
                continue
            sim = SequenceMatcher(None, clean(a.text), clean(b.text)).ratio()
            if sim >= 0.985:
                potentials.append((sim, i, j))
    for _, i, j in sorted(potentials, reverse=True):
        if i in paired_old or j in paired_new:
            continue
        a, b = removed[i], added[j]
        paired_old.add(i); paired_new.add(j)
        results.append(Change('조문 이동/번호변경', b.id, a.heading+'\n'+a.text, b.heading+'\n'+b.text,
                              previous_id=a.id, diff=_line_diff(a.heading, b.heading)))
    for i, clause in enumerate(removed):
        if i not in paired_old:
            results.append(Change('삭제', clause.id, clause.heading+'\n'+clause.text, ''))
    for j, clause in enumerate(added):
        if j not in paired_new:
            results.append(Change('신설', clause.id, '', clause.heading+'\n'+clause.text))
    priority = {'수정':0, '삭제':1, '신설':2, '조문 이동/번호변경':3}
    return sorted(results, key=lambda x:(priority[x.kind], x.clause_id))
