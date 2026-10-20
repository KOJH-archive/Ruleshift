import io
import json
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock,patch

from ruleshift.applicability import evaluate_applicability
from ruleshift.quant import load_positions_csv,simulate_limit,simulate_loan_rate
from ruleshift.parser import parse_bytes
from ruleshift.sources import FSCNoticeClient,Notice,parse_fsc_listing,parse_fsc_detail
from ruleshift.monitor import MonitorStore,monitor_once
from ruleshift.storage import SnapshotStore
from ruleshift.models import Document
from ruleshift.notify import send_ntfy
from ruleshift.ollama_agent import get_ollama_notes
from ruleshift.workflow import run_analysis
from ruleshift.number_extract import limit_suggestions
from ruleshift.sources import parse_fsc_final_listing

SAMPLE='''security_id,maturity_date,market_value_krw\nA,2027-10-20,6000000\nB,2033-01-01,4000000\n'''

class QuantTests(unittest.TestCase):
    def test_parses_valid_and_denominator(self):
        positions=load_positions_csv(SAMPLE)
        rows=simulate_limit(positions,date(2026,10,20),35,30,6,60,forward_months=(0,))
        self.assertAlmostEqual(rows[0]['bucket_weight_pct'],60)
        self.assertEqual(rows[0]['old_excess_krw'],2500000)
        self.assertEqual(rows[0]['new_excess_krw'],3000000)
        self.assertEqual(rows[0]['difference_excess_krw'],500000)
    def test_matured_bond_excluded(self):
        p=load_positions_csv('''security_id,maturity_date,market_value_krw\nA,2027-02-01,9000000\nB,2030-01-01,1000000\n''')
        rows=simulate_limit(p,date(2026,10,20),90,80,6,60,forward_months=(0,6))
        self.assertEqual(rows[1]['total_value_krw'],1000000)
    def test_zero_portfolio_future_denominator(self):
        p=load_positions_csv('''security_id,maturity_date,market_value_krw\nA,2026-11-01,10\n''')
        self.assertIsNone(simulate_limit(p,date(2026,10,20),35,30,forward_months=(3,))[0]['bucket_weight_pct'])
    def test_reject_duplicates(self):
        with self.assertRaises(ValueError):load_positions_csv(SAMPLE+'A,2027-10-20,10\n')
    def test_reject_negative(self):
        with self.assertRaises(ValueError):load_positions_csv('security_id,maturity_date,market_value_krw\nA,2027-01-01,-1')
    def test_loan_interest(self):
        d=simulate_loan_rate('36500000',4,5,365)
        self.assertEqual(d['difference_krw'],365000)

class ProfileTests(unittest.TestCase):
    def test_match(self):
        self.assertIn('조건 일치',evaluate_applicability({'team':'RP'},{'team':['RP','FICC']}).status)
    def test_missing_blocks_match(self):
        self.assertIn('자료 부족',evaluate_applicability({'team':'RP'},{'team':'RP','license':'broker'}).status)
    def test_mismatch(self):
        self.assertIn('불일치',evaluate_applicability({'team':'nonbank'},{'team':'RP'}).status)
    def test_expression_rejected(self):
        with self.assertRaises(ValueError):evaluate_applicability({}, {'team':{'$ne':'RP'}})

class FormatTests(unittest.TestCase):
    def test_hwpx_sections(self):
        b=io.BytesIO()
        xml='<hp:section xmlns:hp="urn:hwpx"><hp:p><hp:run><hp:t>제1조(목적)</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>이 지침은 위험을 관리한다.</hp:t></hp:run></hp:p></hp:section>'.encode('utf-8')
        with zipfile.ZipFile(b,'w') as z:z.writestr('Contents/section0.xml',xml)
        result=parse_bytes(b.getvalue(),'a.hwpx')
        self.assertIn('위험을 관리한다',result)
    def test_invalid_hwpx(self):
        with self.assertRaises(ValueError):parse_bytes(b'notzip','a.hwpx')
    def test_hwp_rejected(self):
        with self.assertRaises(ValueError):parse_bytes(b'anything','a.hwp')

class FSCParsingTests(unittest.TestCase):
    def test_filters_and_deduplicates(self):
        html='''<a href="/po040301/view?noticeId=123">금융투자업규정 변경예고</a>
              <a href="/po040301/view?noticeId=123">중복 제목</a>
              <a href="https://evil.com/po040301/view?noticeId=444">가짜 링크</a>'''
        items=parse_fsc_listing(html)
        self.assertEqual(len(items),1)
        self.assertEqual(items[0].notice_id,'123')
    def test_detail_extract(self):
        sample='<html><div class="view_content">'+'개정안은 아직 시행되지 않습니다. '*9+'</div></html>'
        item=Notice('123','변경예고','https://www.fsc.go.kr/po040301/view?noticeId=123','')
        self.assertIn('개정안',parse_fsc_detail(sample,item).text)
    def test_official_endpoint_restriction(self):
        from ruleshift.sources import _safe_get
        with self.assertRaises(ValueError):_safe_get('https://example.com/po040301')

class MockLaw:
    version='100'
    def search(self,query):
        return [{'title':query,'mst':self.version,'promulgated':'20261020'}]
    def fetch(self,mst):
        suffix='35' if mst=='100' else '30'
        return Document('금융투자업규정',f'제1조(한도)\n환매조건부 매매와 채권 한도 {suffix}퍼센트 이하로 한다.\n부칙\n2027년부터 시행.',mst,
                       source_url='https://www.law.go.kr/법령/금융투자업규정',source_type='국가법령정보 공동활용 API',stage='공포/고시')

class MockFSC:
    items=[Notice('11','금융투자업규정 변경 예고','https://www.fsc.go.kr/po040301/view?noticeId=11','변경예고')]
    def recent(self,max_items=12,keywords=None):return list(self.items)

class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=MonitorStore(Path(self.tmp.name)/'m.db')
        self.snaps=SnapshotStore(Path(self.tmp.name)/'s.db')
    def tearDown(self):self.tmp.cleanup()
    def test_law_new_version_generates_only_once(self):
        self.store.add_watch('law','금융투자업규정')
        law=MockLaw()
        self.assertEqual(monitor_once(self.store,self.snaps,law_client=law)['new_events'],0)
        law.version='101'
        self.assertEqual(monitor_once(self.store,self.snaps,law_client=law)['new_events'],1)
        self.assertEqual(monitor_once(self.store,self.snaps,law_client=law)['new_events'],0)
        self.assertEqual(len(self.store.list_events()),1)
        self.store.mark_reviewed(self.store.list_events()[0]['id'])
        self.assertTrue(self.store.list_events()[0]['reviewed'])
    def test_fsc_baseline_seed_and_second_notice_alert(self):
        self.store.add_watch('fsc','금융투자업규정')
        client=MockFSC()
        self.assertEqual(monitor_once(self.store,self.snaps,fsc_client=client)['seeded'],1)
        client.items.append(Notice('12','금융투자업규정 규정변경예고','https://www.fsc.go.kr/po040301/view?noticeId=12','내용 변경'))
        s=monitor_once(self.store,self.snaps,fsc_client=client)
        self.assertEqual(s['new_events'],1)
        event=self.store.list_events()[0]
        self.assertEqual(event['payload']['stage'],'제안/예고')
        self.assertIn('확정 아님',event['payload']['category'])
    def test_missing_auth_persists_error(self):
        self.store.add_watch('law','금융투자업규정')
        s=monitor_once(self.store,self.snaps)
        self.assertTrue(s['errors'])
        self.assertTrue(self.store.errors())
    def test_idempotent_notice_event(self):
        id=self.store.add_watch('fsc','금융투자업규정')
        self.assertTrue(self.store.record_event(id,'hello','제목',{}))
        self.assertFalse(self.store.record_event(id,'hello','제목',{}))

class NotifyTests(unittest.TestCase):
    def test_reject_short_topic(self):
        with self.assertRaises(ValueError):send_ntfy('short','title',1)
    @patch('ruleshift.notify.requests.post')
    def test_sends_generic_message(self,post):
        post.return_value.status_code=200
        self.assertTrue(send_ntfy('UnpredictableXYZ123','검토항목',1))
        self.assertNotIn('법적 확정',post.call_args.kwargs['data'].decode('utf-8'))
        self.assertTrue(post.call_args.kwargs['allow_redirects'] is False)

class OllamaGroundingTests(unittest.TestCase):
    @patch('ruleshift.ollama_agent.requests.post')
    def test_drops_hallucinated_quote(self,post):
        old=Document('금융투자업규정','제1조(한도)\n채권 편입한도는 35퍼센트이다.','old')
        new=Document('금융투자업규정','제1조(한도)\n채권 편입한도는 30퍼센트이다.','new')
        rpt=run_analysis(old,new)
        post.return_value.json.return_value={'message':{'content':json.dumps({'items':[{'clause_id':'제1조','source_quote':'법이 이미 확정 시행되었다','analysis':'법률 적용 확정'}]})}}
        post.return_value.raise_for_status.return_value=None
        self.assertFalse(get_ollama_notes(rpt))
    @patch('ruleshift.ollama_agent.requests.post')
    def test_grounded_output(self,post):
        old=Document('금융투자업규정','제1조(한도)\n채권 편입한도는 35퍼센트이다.','old')
        new=Document('금융투자업규정','제1조(한도)\n채권 편입한도는 30퍼센트이다.','new')
        rpt=run_analysis(old,new)
        post.return_value.json.return_value={'message':{'content':json.dumps({'items':[{'clause_id':'제1조','source_quote':'채권 편입한도는 30퍼센트이다.','analysis':'추가 확인이 필요합니다.'}]})}}
        post.return_value.raise_for_status.return_value=None
        self.assertIn('제1조',get_ollama_notes(rpt))

if __name__=='__main__':unittest.main()

class ExtraIntegrationTests(unittest.TestCase):
    def test_suggest_limit_from_comparison(self):
        old=Document('RP 규정','제1조(한도)\n편입비율은 35퍼센트 이하로 한다.','v1')
        new=Document('RP 규정','제1조(한도)\n편입비율은 30퍼센트 이하로 한다.','v2')
        candidates=limit_suggestions(run_analysis(old,new))
        self.assertEqual((candidates[0]['old_pct'],candidates[0]['new_pct']),(35,30))
        self.assertTrue(candidates[0]['review_required'])
    def test_ambiguous_multinumbers_not_suggested(self):
        old=Document('규정','제1조(비율)\n비율 35퍼센트와 한도 40퍼센트.','v1')
        new=Document('규정','제1조(비율)\n비율 30퍼센트와 한도 20퍼센트.','v2')
        self.assertEqual(limit_suggestions(run_analysis(old,new)),[])
    def test_final_fsc_path(self):
        html='<a href="/po040200/87816?curPage=1">금융투자업규정 일부개정 고시</a>'
        items=parse_fsc_final_listing(html)
        self.assertEqual(len(items),1)
        self.assertEqual(items[0].stage,'공포/고시')
    def test_saved_profile_and_conditions(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=MonitorStore(Path(tmp)/'s.db')
            watch_id=s.add_watch('law','금융투자업규정')
            s.save_profile('default',{'team':'RP'})
            s.save_conditions(watch_id,{'team':'RP'})
            self.assertIn('조건 일치',s.applicability(watch_id)['status'])
