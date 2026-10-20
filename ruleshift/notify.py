"""Opt-in notification. Text deliberately avoids original clauses and sensitive portfolios."""
from __future__ import annotations
import re
from urllib.parse import urlparse
import requests


def send_ntfy(topic: str, title: str, count: int, base_url: str='https://ntfy.sh', token: str='', session=None) -> bool:
    parsed=urlparse(base_url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('ntfy HTTPS 서버 주소 형식이 올바르지 않습니다.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{12,100}',topic):
        raise ValueError('추측하기 어려운 12~100자 알림 토픽을 사용하세요.')
    safe_title = re.sub(r'[\r\n\t]',' ', title)[:80]
    headers={'Title':'RuleShift 변경 감지', 'Priority':'3', 'Tags':'information'}
    if token: headers['Authorization']='Bearer '+token
    s=session or requests
    response=s.post(base_url.rstrip('/')+'/'+topic,
                    data=f'{safe_title}: 검토할 신규 항목 {count}건. 로컬 대시보드에서 근거를 확인하세요.'.encode('utf-8'),
                    headers=headers,timeout=10,allow_redirects=False)
    if not 200<=response.status_code<300:
        raise RuntimeError(f'알림 전송 실패 HTTP {response.status_code}')
    return True
