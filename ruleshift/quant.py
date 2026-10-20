"""Deterministic, illustrative what-if calculations. Not trading or compliance orders."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import date
from io import StringIO
import csv
from decimal import Decimal, InvalidOperation
from dateutil.relativedelta import relativedelta

@dataclass(frozen=True)
class BondPosition:
    security_id: str
    maturity_date: date
    market_value_krw: Decimal


def _positive_amount(value: str) -> Decimal:
    try: x = Decimal(str(value))
    except (InvalidOperation, ValueError) as e: raise ValueError('market_value_krw 숫자 형식을 확인하세요.') from e
    if not x.is_finite() or x < 0: raise ValueError('시장가치는 0 이상 유한한 값이어야 합니다.')
    return x


def load_positions_csv(raw: str) -> list[BondPosition]:
    reader = csv.DictReader(StringIO(raw.lstrip('\ufeff')))
    required = {'security_id','maturity_date','market_value_krw'}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError('CSV 필수 열: security_id,maturity_date,market_value_krw')
    positions = []
    for row in reader:
        if not any(row.values()): continue
        try: maturity = date.fromisoformat(row['maturity_date'].strip())
        except (TypeError, ValueError) as e: raise ValueError(f"만기일 오류: {row.get('security_id','')}") from e
        positions.append(BondPosition((row['security_id'] or '').strip(),maturity,_positive_amount(row['market_value_krw'])))
        if len(positions)>100000: raise ValueError('100,000종목 초과')
    if not positions: raise ValueError('유효한 채권 포지션이 없습니다.')
    if any(not p.security_id for p in positions): raise ValueError('종목명/ID 누락')
    if len(set(p.security_id for p in positions)) != len(positions):
        raise ValueError('중복 security_id가 있습니다. 같은 종목은 먼저 합산하거나 ID를 구분하세요.')
    return positions


def simulate_limit(positions: list[BondPosition], as_of: date, old_limit_pct: str|float,
                   new_limit_pct: str|float, start_months: int = 6, end_months: int = 60,
                   forward_months: tuple[int, ...] = (0,1,3,6,12)) -> list[dict]:
    old_pct, new_pct = Decimal(str(old_limit_pct)), Decimal(str(new_limit_pct))
    if any(not x.is_finite() or not 0 <= x <= 100 for x in (old_pct,new_pct)):
        raise ValueError('한도는 0~100 사이의 %여야 합니다.')
    if not 0 <= start_months < end_months <= 1200: raise ValueError('기간 조건이 잘못되었습니다.')
    output=[]
    for m in forward_months:
        if not 0<=m<=120: raise ValueError('미래 분석은 0~120개월 범위입니다.')
        d = as_of+relativedelta(months=m)
        live=[p for p in positions if p.maturity_date>d]
        denominator=sum((p.market_value_krw for p in live),Decimal('0'))
        low=d+relativedelta(months=start_months)
        high=d+relativedelta(months=end_months)
        numerator=sum((p.market_value_krw for p in live if low<=p.maturity_date<=high),Decimal('0'))
        if not denominator:
            ratio=None; old_excess=None; new_excess=None
        else:
            ratio=float(numerator/denominator*100)
            old_excess=float(max(Decimal('0'),numerator - denominator*old_pct/100))
            new_excess=float(max(Decimal('0'),numerator - denominator*new_pct/100))
        output.append({'as_of':d.isoformat(),'months_ahead':m,
                       'position_count':len(live),'bucket_value_krw':float(numerator),
                       'total_value_krw':float(denominator),'bucket_weight_pct':ratio,
                       'old_limit_pct':float(old_pct),'new_limit_pct':float(new_pct),
                       'old_excess_krw':old_excess,'new_excess_krw':new_excess,
                       'difference_excess_krw':None if new_excess is None else new_excess-old_excess,
                       'note':'신규매매/가격변동/조달·담보·회계분류를 고려하지 않은 정적 스냅샷 가정. 한도 분모·편입대상·경계값은 사용자 확인.'})
    return output


def simulate_loan_rate(principal_krw: str|float, old_rate_pct: str|float, new_rate_pct: str|float,
                       days: int = 30) -> dict:
    principal = _positive_amount(str(principal_krw))
    try: old, new = Decimal(str(old_rate_pct)), Decimal(str(new_rate_pct))
    except InvalidOperation as e: raise ValueError('금리를 숫자로 입력하세요.') from e
    if any(not x.is_finite() or not -10<=x<=100 for x in (old,new)) or not 1<=days<=366:
        raise ValueError('금리 또는 일수 범위를 확인하세요.')
    factor = Decimal(days)/Decimal('36500')
    a, b = principal*old*factor,principal*new*factor
    return {'days':days,'old_interest_krw':round(float(a)), 'new_interest_krw':round(float(b)),
            'difference_krw':round(float(b-a)),
            'note':'ACT/365 단리, 잔액·금리 일정 가정. 실제 약정·상환방식·우대금리·이자일수계산은 별도 확인.'}
