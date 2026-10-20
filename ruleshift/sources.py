"""Restricted source collectors. No arbitrary URLs, untrusted redirects or credential logging."""
from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, parse_qs
import re
import requests
from bs4 import BeautifulSoup
from .law_api import LawOpenClient
from .models import Document

FSC_URL = 'https://www.fsc.go.kr/po040301'
USER_AGENT = 'RuleShiftRadar/1.0 (evidence-first; personal monitoring)'

@dataclass(frozen=True)
class Notice:
    notice_id: str
    title: str
    url: str
    text: str
    stage: str = '제안/예고'
    published_date: str = ''


def _safe_get(url: str, session=None):
    u = urlparse(url)
    if u.scheme != 'https' or u.hostname != 'www.fsc.go.kr' or u.username or u.password or u.port not in (None, 443):
        raise ValueError('금융위 공식 사이트 주소만 허용합니다.')
    if not (u.path.startswith('/po040301') or u.path.startswith('/po040200')):
        raise ValueError('허용되지 않은 금융위 게시판 경로입니다.')
    caller = session or requests
    r = caller.get(url, headers={'User-Agent': USER_AGENT}, timeout=20, allow_redirects=False)
    if not 200 <= r.status_code < 300:
        raise RuntimeError(f'금융위 HTTP 상태 코드: {r.status_code}')
    if len(r.content) > 4 * 1024 * 1024:
        raise ValueError('금융위 응답 크기 제한 초과')
    return r


def parse_fsc_listing(html: str, max_items: int = 15) -> list[Notice]:
    """Find official notice links conservatively. Listing item copy is not the amendment text."""
    soup = BeautifulSoup(html, 'html.parser')
    seen, out = set(), []
    for a in soup.find_all('a', href=True):
        href = a.get('href', '').strip()
        if not ('noticeId=' in href and '/view' in href):
            continue
        full = urljoin(FSC_URL, href)
        parsed = urlparse(full)
        if parsed.hostname != 'www.fsc.go.kr' or not parsed.path.startswith('/po040301/view'):
            continue
        ids = parse_qs(parsed.query).get('noticeId', [])
        if len(ids) != 1 or not ids[0].isdigit() or ids[0] in seen:
            continue
        title = a.get_text(' ', strip=True)
        if len(title) < 5:
            parent = a.find_parent(['li', 'tr', 'div'])
            title = (parent.get_text(' ', strip=True) if parent else title)[:200]
        if len(title) < 5:
            continue
        seen.add(ids[0])
        out.append(Notice(ids[0], title[:300], f'https://www.fsc.go.kr/po040301/view?noticeId={ids[0]}', ''))
        if len(out) >= max_items:
            break
    return out


def parse_fsc_detail(html: str, item: Notice) -> Notice:
    soup = BeautifulSoup(html,'html.parser')
    for tag in soup(['script','style','nav','footer','header']):
        tag.decompose()
    candidates = []
    for selector in ['.view_content', '.board_view', '.view_cont', '.board-cont', '.bbs_view', '.detail_cont', '#contents', 'main']:
        for node in soup.select(selector):
            content = node.get_text('\n', strip=True)
            if len(content) > 100:
                candidates.append(content)
    text = min(candidates, key=len) if candidates else soup.get_text('\n', strip=True)
    text = text[:25000]
    found = re.search(r'20\d{2}[.\-/년 ]+\d{1,2}[.\-/월 ]+\d{1,2}', text[:2500])
    published = found.group(0) if found else ''
    return Notice(item.notice_id,item.title,item.url,text,stage='제안/예고',published_date=published)


class FSCNoticeClient:
    def __init__(self, session=None): self.session = session
    def recent(self, max_items: int = 10, keywords: list[str] | None = None) -> list[Notice]:
        r = _safe_get(FSC_URL, self.session)
        items = parse_fsc_listing(r.text, min(max_items*3, 40))
        terms = [w.casefold() for w in (keywords or []) if w.strip()]
        if terms:
            items = [x for x in items if any(w in x.title.casefold() for w in terms)]
        out = []
        for i in items[:max_items]:
            try:
                page = _safe_get(i.url, self.session)
                out.append(parse_fsc_detail(page.text,i))
            except (ValueError, RuntimeError, requests.RequestException):
                # Do not fabricate article content. Monitor can show title with an evidence warning.
                out.append(i)
        return out


def notice_document(notice: Notice) -> Document:
    content = notice.text or notice.title
    return Document(notice.title, f'제1조(공고문 안내)\n{content}', notice.notice_id,
                    source_url=notice.url, source_type='금융위 규정변경예고 게시판',
                    stage=notice.stage,published_date=notice.published_date,verified=False)

FSC_FINAL_URL='https://www.fsc.go.kr/po040200'

def parse_fsc_final_listing(html: str,max_items: int=15) -> list[Notice]:
    """FSC final notices have paths /po040200/<numeric>, unlike draft noticeId links."""
    soup=BeautifulSoup(html,'html.parser')
    out=[];seen=set()
    for a in soup.find_all('a',href=True):
        href=a['href']
        full=urljoin(FSC_FINAL_URL,href)
        u=urlparse(full)
        if u.hostname!='www.fsc.go.kr':continue
        m=re.fullmatch(r'/po040200/(\d+)',u.path)
        if not m or m.group(1) in seen:continue
        title=a.get_text(' ',strip=True)
        if len(title)<5:continue
        seen.add(m.group(1))
        out.append(Notice(m.group(1),title[:300],FSC_FINAL_URL+'/'+m.group(1),'',stage='공포/고시'))
        if len(out)>=max_items:break
    return out

class FSCFinalClient:
    def __init__(self,session=None):self.session=session
    def recent(self,max_items: int=10,keywords: list[str]|None=None) -> list[Notice]:
        items=parse_fsc_final_listing(_safe_get(FSC_FINAL_URL,self.session).text,min(max_items*3,40))
        terms=[x.casefold() for x in (keywords or []) if x.strip()]
        if terms: items=[x for x in items if any(t in x.title.casefold() for t in terms)]
        out=[]
        for item in items[:max_items]:
            try:
                page=_safe_get(item.url,self.session)
                detail=parse_fsc_detail(page.text,item)
                out.append(Notice(detail.notice_id,detail.title,detail.url,detail.text,'공포/고시',detail.published_date))
            except (ValueError,RuntimeError,requests.RequestException):
                out.append(item)
        return out
