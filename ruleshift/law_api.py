"""Opt-in adaptor for the Korean Ministry of Government Legislation's published Law Open API.
Network calls require a real OC token and were not tested in this build environment.
"""
from __future__ import annotations
from urllib.parse import quote
import requests
from defusedxml import ElementTree as ET
from .models import Document

ENDPOINT = 'https://www.law.go.kr/DRF/'

def _value(el, *names) -> str:
    for name in names:
        result = el.findtext(name)
        if result is not None and result.strip():
            return result.strip()
    return ''

class LawOpenClient:
    def __init__(self, oc: str):
        if not oc or oc.lower() == 'test':
            raise ValueError('실제 국가법령정보 공동활용 OC 인증값이 필요합니다.')
        self.oc = oc

    def _xml(self, path: str, params: dict) -> ET.Element:
        response = requests.get(ENDPOINT+path, params={'OC':self.oc,'type':'XML',**params}, timeout=25,
                                headers={'User-Agent':'RuleShiftMVP/0.1 (personal research)'})
        response.raise_for_status()
        if len(response.content) > 8 * 1024 * 1024:
            raise ValueError('법령 원문 응답 제한(8MB) 초과')
        root = ET.fromstring(response.content)
        if 'error' in root.tag.casefold() or root.find('.//error') is not None or root.find('.//에러') is not None:
            raise RuntimeError('법령 API가 오류를 반환했습니다. OC 및 서비스 승인 여부를 확인하세요.')
        return root

    def search(self, query: str) -> list[dict]:
        root = self._xml('lawSearch.do', {'target':'law','query':query,'display':30,'page':1,'sort':'ddes'})
        results = []
        for elem in root.findall('.//법령'):
            name = _value(elem,'법령명한글','법령명_한글','법령명')
            mst = _value(elem,'법령일련번호')
            if name and mst:
                results.append({'title':name,'mst':mst,'promulgated':_value(elem,'공포일자'),
                                'effective':_value(elem,'시행일자'),'type':_value(elem,'법령구분명')})
        return results

    def fetch(self, mst: str, stage: str='내부문서/미확인') -> Document:
        if not str(mst).isdigit():
            raise ValueError('법령일련번호(MST)는 숫자여야 합니다.')
        root = self._xml('lawService.do', {'target':'law','MST':str(mst)})
        name = _value(root,'.//법령명_한글','.//법령명한글','.//법령명')
        if not name:
            raise RuntimeError('응답에서 법령명을 찾지 못했습니다. 원문 구조를 확인하세요.')
        pieces = []
        for article in root.findall('.//조문단위'):
            if _value(article,'조문여부') == '전문':
                continue
            title = _value(article,'조문제목')
            num = _value(article,'조문번호')
            subnum = _value(article,'조문가지번호')
            full_text = _value(article,'조문내용')
            if not full_text and not num:
                continue
            # Often the official 조문내용 contains the full article heading. Avoid double headings.
            if full_text.startswith('제') and '조' in full_text[:16]:
                pieces.append(full_text)
            else:
                heading = f'제{int(num)}조' if num and num.isdigit() else title
                if subnum.isdigit() and int(subnum)>0:
                    heading += f'의{int(subnum)}'
                if title and title not in heading:
                    heading += f'({title})'
                pieces.append(heading+'\n'+full_text)
        for side in root.findall('.//부칙단위'):
            data = _value(side,'부칙내용')
            if data:
                pieces.append('부칙\n'+data)
        if not pieces:
            raise RuntimeError('공식 API 응답에서 조문이 추출되지 않았습니다. 원문 확인 필요.')
        published = _value(root,'.//공포일자')
        effective = _value(root,'.//시행일자')
        return Document(name,'\n\n'.join(pieces),str(mst),
                        source_url='https://www.law.go.kr/법령/'+quote(name),
                        source_type='국가법령정보 공동활용 API',stage=stage,
                        effective_date=effective,published_date=published,verified=False)
