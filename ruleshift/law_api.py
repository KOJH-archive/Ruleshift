"""Official Korean law search and complete article extraction."""
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


def _content(el) -> str:
    """Preserve text within inline XML markup without inheriting sibling sections."""
    return ' '.join(''.join(el.itertext()).split()) if el is not None else ''


def _article_lines(article) -> list[str]:
    # 조문내용 is usually only the introduction. 항/호/목 are separate nested nodes.
    return [value for node in article.iter()
            if node.tag in {'조문내용', '항내용', '호내용', '목내용'}
            if (value := _content(node))]

class LawOpenClient:
    def __init__(self, oc: str):
        if not oc or oc.lower() == 'test':
            raise ValueError('실제 국가법령정보 공동활용 OC 인증값이 필요합니다.')
        self.oc = oc

    def _xml(self, path: str, params: dict) -> ET.Element:
        try:
            response = requests.get(ENDPOINT+path, params={'OC':self.oc,'type':'XML',**params}, timeout=25,
                                    allow_redirects=False,
                                    headers={'User-Agent':'RuleShiftMVP/0.1 (personal research)'})
        except requests.RequestException:
            # requests exceptions can embed the request URL, including the OC value.
            raise RuntimeError('법령 API 연결에 실패했습니다. 네트워크 상태를 확인하세요.') from None
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f'법령 API HTTP {response.status_code} 응답. OC 및 서비스 상태를 확인하세요.')
        if len(response.content) > 8 * 1024 * 1024:
            raise ValueError('법령 원문 응답 제한(8MB) 초과')
        root = ET.fromstring(response.content)
        if 'error' in root.tag.casefold() or root.find('.//error') is not None or root.find('.//에러') is not None:
            raise RuntimeError('법령 API가 오류를 반환했습니다. OC 및 서비스 승인 여부를 확인하세요.')
        return root

    def search(self, query: str) -> list[dict]:
        root = self._xml('lawSearch.do', {'target':'law','query':query,'display':30,'page':1,'sort':'ddes'})
        results = []
        # The live API currently returns result rows as <law>; older/mock
        # responses may use the Korean <법령> tag.
        elems = root.findall('.//law') or root.findall('.//법령')
        for elem in elems:
            name = _value(elem,'법령명한글','법령명_한글','법령명')
            mst = _value(elem,'법령일련번호')
            if name and mst:
                results.append({'title':name,'mst':mst,'promulgated':_value(elem,'공포일자'),
                                'effective':_value(elem,'시행일자'),'type':_value(elem,'법령구분명')})
        return results

    def fetch(self, mst: str, stage: str='공포/고시') -> Document:
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
            lines = _article_lines(article)
            full_text = '\n'.join(lines)
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
        for index, side in enumerate(root.findall('.//부칙단위'), 1):
            data = _content(side.find('부칙내용'))
            if data:
                issued = _value(side, '부칙공포일자', '공포일자')
                number = _value(side, '부칙공포번호', '공포번호')
                identity = '-'.join(x for x in (issued, number) if x) or str(index)
                # Official 부칙내용 may itself start with "부칙". Keep it as body,
                # not a second synthetic section heading for the text parser.
                pieces.append(f'부칙({identity})\n원문: {data}')
        for index, annex in enumerate(root.findall('.//별표단위'), 1):
            data = _content(annex.find('별표내용'))
            if data:
                number = _value(annex, '별표번호') or str(index)
                branch = _value(annex, '별표가지번호')
                kind = _value(annex, '별표구분')
                identity = '-'.join(x for x in (kind, number, branch) if x)
                title = _value(annex, '별표제목')
                pieces.append(f'별표({identity})\n{title}\n원문: {data}')
        if not pieces:
            raise RuntimeError('공식 API 응답에서 조문이 추출되지 않았습니다. 원문 확인 필요.')
        published = _value(root,'.//공포일자')
        effective = _value(root,'.//시행일자')
        return Document(name,'\n\n'.join(pieces),str(mst),
                        source_url='https://www.law.go.kr/법령/'+quote(name),
                        source_type='국가법령정보 공동활용 API',stage=stage,
                        effective_date=effective,published_date=published,verified=False)
