"""Deterministic core; optional LAYA (advisory) and LangGraph (state orchestration).
No LLM output can silently alter official facts or elevate a proposal to active law.
"""
from __future__ import annotations
from typing import TypedDict, Any
from .models import Document, Report, Change, Assessment
from .compare import compare
from .impact import assess, PROFILES

class AnalysisState(TypedDict, total=False):
    old: Document
    new: Document
    profiles: list[str]
    extra_keywords: list[str]
    use_laya: bool
    changes: list[Change]
    assessments: list[Assessment]
    warnings: list[str]
    report: Report

def _diff(state: AnalysisState) -> dict:
    return {'changes':compare(state['old'],state['new'])}

def _laya_advisory(change: Change) -> str:
    # LAYA is optional and downloads a multilingual checkpoint on first activation.
    from laya import Router
    if not hasattr(_laya_advisory,'router'):
        _laya_advisory.router = Router()
    questions = {'area':{'type':'choice','instructions':'이 규정 개정 조항의 주요 관련 분야는?',
                          'criteria':{'work':'채권, RP, 금융투자, 금융기관 운용 업무',
                                      'life':'대출, 보험, 주거, 소비자 계약 및 개인정보',
                                      'other':'그 외 분야'}}}
    answer = _laya_advisory.router.predict((change.after or change.before)[:2500], questions, model='multilingual')
    label = answer['answers']['area']['choice']
    conf = answer['answers']['area'].get('answer_confidence')
    return f'{label} (모델 점수: {conf:.2f})' if isinstance(conf,(int,float)) else str(label)

def _classification(state: AnalysisState) -> dict:
    assessments=[]
    warnings=list(state.get('warnings', []))
    for change in state['changes']:
        suggestion = ''
        if state.get('use_laya',False):
            try:
                suggestion = _laya_advisory(change)
            except (ImportError,RuntimeError,ValueError,OSError,KeyError) as err:
                warnings.append(f'LAYA 실행 실패: {type(err).__name__}. 규칙 기반 분류로 처리.')
                # Don't retry on every changed clause when model is inaccessible.
                state['use_laya']=False
        assessments.append(assess(change,state['new'],state.get('profiles'),state.get('extra_keywords'),suggestion))
    return {'assessments':assessments,'warnings':warnings}

def _verify(state: AnalysisState) -> dict:
    warnings = list(state.get('warnings', []))
    new=state['new']; old=state['old']
    if new.stage == '제안/예고':
        warnings.append('개정안·예고 단계입니다. 현재 효력이 발생했다고 판단하지 마세요.')
    if not new.effective_date:
        warnings.append('시행일이 제공되지 않았습니다. 원문·부칙으로 확인하세요.')
    if not new.verified or not old.verified:
        warnings.append('최소 한 개 버전의 공식 원문 교차 검증이 완료되지 않았습니다.')
    if '부칙' not in new.text:
        warnings.append('부칙을 확보하지 못했거나 없을 수 있습니다. 경과조치·시행일을 별도 확인하세요.')
    if not state['changes']:
        warnings.append('입력된 두 버전의 조문 텍스트에서 변경사항을 발견하지 못했습니다.')
    return {'warnings':warnings}

def _report(state: AnalysisState) -> dict:
    old,new=state['old'],state['new']
    return {'report':Report(new.title,old.version,new.version,new.source_url,new.source_type,new.stage,
                            new.effective_date,new.published_date,new.verified,state['assessments'],state['warnings'])}

def run_analysis(old: Document, new: Document, profiles: list[str] | None=None,
                 extra_keywords: list[str] | None=None, use_laya: bool=False,
                 use_langgraph: bool=False, use_ollama: bool=False, ollama_model: str="auto") -> Report:
    state: AnalysisState = {'old':old,'new':new,'profiles':profiles if profiles is not None else list(PROFILES),
                            'extra_keywords':extra_keywords or [],'use_laya':use_laya,'warnings':[]}
    if use_langgraph:
        try:
            from langgraph.graph import StateGraph, START, END
        except ImportError as exc:
            raise RuntimeError('LangGraph 미설치: pip install langgraph 후 다시 실행하세요.') from exc
        builder=StateGraph(AnalysisState)
        for name,func in [('diff',_diff),('classify',_classification),('verify',_verify),('report',_report)]:
            builder.add_node(name,func)
        builder.add_edge(START,'diff')
        builder.add_edge('diff','classify')
        builder.add_edge('classify','verify')
        builder.add_edge('verify','report')
        builder.add_edge('report',END)
        report = builder.compile().invoke(state)['report']
        return _add_ollama(report, use_ollama, ollama_model)
    for fn in (_diff,_classification,_verify,_report):
        state.update(fn(state))
    return _add_ollama(state['report'], use_ollama, ollama_model)


def _add_ollama(report: Report, enabled: bool, model: str) -> Report:
    if enabled:
        try:
            from .ollama_agent import get_ollama_notes
            report.ollama_notes = get_ollama_notes(report,model=model)
            if not report.ollama_notes:
                report.warnings.append('Ollama 응답에서 근거 인용을 검증한 설명이 없습니다. 생성 해석을 표시하지 않습니다.')
        except (ImportError,RuntimeError,ValueError,OSError,KeyError,ConnectionError) as e:
            report.warnings.append(f'Ollama 실행 실패: {type(e).__name__}. 기본 분석만 제공합니다.')
        except Exception as e:
            report.warnings.append(f'Ollama 분석 이용 불가: {type(e).__name__}. 기본 분석만 제공합니다.')
    return report
