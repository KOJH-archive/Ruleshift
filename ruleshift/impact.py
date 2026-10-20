from __future__ import annotations
from .models import Assessment, Change, Document

PROFILES = {
    '금융·채권·RP 업무': ['rp','환매조건부','채권','국채','공사채','금융투자','증권사','자금조달','담보','운용','잔액','레버리지','결제','자본시장','유동성','듀레이션','운용비율'],
    '생활·개인 계약': ['대출','금리','이자','중도상환','보험','보험료','약관','개인정보','소비자','환불','청약','자동갱신','구독','주택','임대차','임차인','보증금','통신','계약']
}
MATERIAL = ['한도','의무','하여야','금지','벌칙','과태료','등록','신고','기준','비율','기간','기한','해지','적용','면제','이자','수수료','위반','제한']
SENSITIVE = ['부칙','경과','유예','예외','적용례','시행']

def assess(change: Change, document: Document, profile_names: list[str] | None = None,
           extra_keywords: list[str] | None = None, laya_suggestion: str = '') -> Assessment:
    profile_names = list(PROFILES) if profile_names is None else profile_names
    terms = {name: PROFILES[name] for name in profile_names if name in PROFILES}
    custom = [w.strip() for w in (extra_keywords or []) if w.strip()]
    if custom:
        terms['사용자 관심 키워드'] = custom
    context = (document.title + ' ' + (change.before or '') + ' ' + (change.after or '')).casefold()
    hits = {name:[word for word in words if word.casefold() in context] for name, words in terms.items()}
    matches = {name:ws for name,ws in hits.items() if ws}
    if matches:
        area = ', '.join(matches)
        domain_count = sum(len(v) for v in matches.values())
        relevance = '높음' if domain_count >= 3 else '보통'
    else:
        area, relevance = '미분류', '낮음'
    material = [w for w in MATERIAL if w in context]
    impact = '낮음'
    if relevance != '낮음':
        impact = '높음' if len(material) >= 2 or change.kind in ('삭제','신설') and material else '보통'
    if change.kind == '조문 이동/번호변경':
        impact = '낮음'  # identical body does not imply changed legal duty
    elif relevance == '낮음' and material:
        impact = '판단 보류'  # scope ambiguity, no assumption that it is irrelevant
    reason = f'관심 분야 일치: {", ".join(w for ws in matches.values() for w in ws[:5]) or "자동 확인되지 않음"}. '
    reason += f'검토할 표현: {", ".join(material[:5]) or "명확하지 않음"}. '
    reason += '이는 키워드 기반 1차 분류이며 법적 의무 변경의 확정 판정은 아닙니다.'
    actions = ['원문 조항·부칙·적용 대상과 시행일을 담당자가 확인']
    if document.stage == '제안/예고':
        actions.insert(0, '확정·시행 전 예고 단계로, 현행 규정에 즉시 반영하지 않기')
    if not document.effective_date:
        actions.append('실제 시행일 및 조항별 시행 시점 확인')
    if any(word in context for word in SENSITIVE):
        actions.append('경과규정·유예·예외 적용 여부 확인')
    if relevance != '낮음' and change.kind != '조문 이동/번호변경':
        actions.append('현재 업무 절차 또는 계약 조건과 대조')
    evidence = (change.after or change.before).strip()[:600]
    return Assessment(change, area, relevance, impact, reason, tuple(dict.fromkeys(actions)), evidence,
                      laya_suggestion, True)
