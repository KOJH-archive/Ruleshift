import json
import tempfile
import unittest
from pathlib import Path
from ruleshift.models import Document
from ruleshift.compare import compare
from ruleshift.parser import parse_clauses, parse_bytes
from ruleshift.impact import assess
from ruleshift.storage import SnapshotStore
from ruleshift.workflow import run_analysis

BASE=Path(__file__).resolve().parents[1]

def make(text,title='규정',version='1'):
    return Document(title,text,version)

class ParserTests(unittest.TestCase):
    def test_articles_with_subnumbers(self):
        result=parse_clauses('제1조(목적)\n가나다\n제2조의2(예외)\n내용')
        self.assertEqual([x.id for x in result],['제1조','제2조의2'])
    def test_unnumbered_contract(self):
        self.assertEqual(parse_clauses('계약 조건 안내문')[0].id,'전체문서')
    def test_empty_raises(self):
        with self.assertRaises(ValueError):parse_clauses('  ')
    def test_cp949(self):
        self.assertIn('금리',parse_bytes('금리 관련'.encode('cp949'),'file.txt'))
    def test_unsupported_type(self):
        with self.assertRaises(ValueError):parse_bytes(b'anything','file.hwp')
    def test_oversize(self):
        with self.assertRaises(ValueError):parse_bytes(b'a'*(12*1024*1024+1),'file.txt')

class CompareTests(unittest.TestCase):
    def test_changed_clause(self):
        old=make('제1조(편입한도)\n편입비율은 35퍼센트 이하로 한다.')
        new=make('제1조(편입한도)\n편입비율은 30퍼센트 이하로 한다.')
        self.assertEqual(compare(old,new)[0].kind,'수정')
    def test_whitespace_ignored(self):
        old=make('제1조(목적)\n이 문서는 기준을 설명한다.')
        new=make('제1조(목적)\n이  문서는   기준을 설명한다.')
        self.assertEqual(compare(old,new),[])
    def test_added_removed(self):
        old=make('제1조(목적)\n내용\n제2조(삭제)\n없어진 조문')
        new=make('제1조(목적)\n내용\n제3조(신설)\n새로운 조문')
        self.assertEqual(set(ch.kind for ch in compare(old,new)),{'삭제','신설'})
    def test_renumber_detected(self):
        body='정보보호 조치의 내용은 관계 법령에서 정한 기준에 따르며 보호책임자를 지정한다.'
        old=make('제1조(책임)\n'+body)
        new=make('제9조(책임)\n'+body)
        r=compare(old,new)
        self.assertEqual(len(r),1)
        self.assertEqual(r[0].kind,'조문 이동/번호변경')
    def test_renumber_short_not_confused(self):
        old=make('제1조(책임)\n책임진다.')
        new=make('제9조(책임)\n책임진다.')
        self.assertEqual(len(compare(old,new)),2)
    def test_title_mismatch(self):
        with self.assertRaises(ValueError):compare(make('기준',title='가'),make('내용',title='나'))

class ImpactTests(unittest.TestCase):
    def test_generic_analysis_never_assumes_user_field(self):
        old=make('제1조(의무)\n신고하여야 한다.',title='일반법')
        new=make('제1조(의무)\n등록하여야 한다.',title='일반법',version='2')
        assessment=run_analysis(old,new).assessments[0]
        self.assertEqual(assessment.relevance,'미평가')
        self.assertEqual(assessment.impact,'판단 보류')

    def test_rp_high_and_review(self):
        old=make('제1조(운용 비율)\n채권 운용비율 한도는 35퍼센트 이하로 한다.',title='RP 지침')
        new=make('제1조(운용 비율)\n채권 운용비율 한도는 30퍼센트 이하로 한다.',title='RP 지침',version='2')
        a=run_analysis(old,new,profiles=['금융·채권·RP 업무']).assessments[0]
        self.assertEqual(a.relevance,'높음')
        self.assertEqual(a.impact,'높음')
        self.assertTrue(a.review_required)
    def test_renumber_low_impact(self):
        body='계약자는 개인정보를 수집하고 보관할 때 필요한 안전조치를 마련하고 책임자를 지정한다.'
        old=make('제1조(개인정보)\n'+body,title='약관')
        new=make('제9조(개인정보)\n'+body,title='약관',version='2')
        self.assertEqual(run_analysis(old,new).assessments[0].impact,'낮음')
    def test_proposal_warning(self):
        old=make('제1조(한도)\nRP 운용비율 한도 30%.')
        new=Document('규정','제1조(한도)\nRP 운용비율 한도 20%.','2',stage='제안/예고')
        r=run_analysis(old,new)
        self.assertTrue(any('예고' in w for w in r.warnings))
        self.assertTrue(any('즉시 반영하지' in x for x in r.assessments[0].actions))
    def test_evidence_present(self):
        old=make('제1조(요건)\n비율은 35%.')
        new=make('제1조(요건)\n비율은 30%.',version='2')
        self.assertIn('30%',run_analysis(old,new).assessments[0].evidence)

class StorageTests(unittest.TestCase):
    def test_snapshots_deduplicated(self):
        with tempfile.TemporaryDirectory() as d:
            store=SnapshotStore(Path(d)/'s.db')
            doc=make('본문')
            self.assertTrue(store.save(doc))
            self.assertFalse(store.save(doc))
            self.assertEqual(len(store.list_versions('규정')),1)
            self.assertEqual(store.list_titles(),['규정'])
    def test_revised_same_version_stored_by_hash(self):
        with tempfile.TemporaryDirectory() as d:
            store=SnapshotStore(Path(d)/'s.db')
            store.save(make('본문 1'))
            store.save(make('본문 2'))
            self.assertEqual(len(store.list_versions('규정')),2)

class DemoTests(unittest.TestCase):
    def test_three_end_to_end_fixtures(self):
        for case in ('rp_limit','loan_terms','privacy'):
            with self.subTest(case=case):
                folder=BASE/'samples'/case
                meta=json.loads((folder/'metadata.json').read_text(encoding='utf-8'))
                old=Document(meta['title'],(folder/'before.txt').read_text(encoding='utf-8'),'old',**meta['old'])
                new=Document(meta['title'],(folder/'after.txt').read_text(encoding='utf-8'),'new',**meta['new'])
                report=run_analysis(old,new)
                self.assertGreaterEqual(len(report.assessments),1)
                self.assertTrue(report.warnings)
                self.assertEqual(report.title,meta['title'])
                self.assertIn('assessments', report.to_dict())
    def test_fixture_renumber(self):
        folder=BASE/'samples'/'privacy'
        old=make((folder/'before.txt').read_text(encoding='utf-8'))
        new=make((folder/'after.txt').read_text(encoding='utf-8'))
        kinds={a.kind for a in compare(old,new)}
        self.assertIn('조문 이동/번호변경',kinds)

if __name__ == '__main__':
    unittest.main()

# Added at module level; picked up by test discovery despite placement after main guard.
from unittest.mock import patch
from ruleshift.law_api import LawOpenClient
from ruleshift.reporting import markdown_report

class ExternalAdapterContractTests(unittest.TestCase):
    def test_oc_missing(self):
        with self.assertRaises(ValueError):LawOpenClient('test')

    @patch('ruleshift.law_api.requests.get')
    def test_search_xml_parser(self,mock_get):
        mock_get.return_value.status_code=200
        mock_get.return_value.content='''<LawSearch><법령><법령명한글>테스트법</법령명한글><법령일련번호>12345</법령일련번호><공포일자>20261020</공포일자></법령></LawSearch>'''.encode('utf-8')
        mock_get.return_value.raise_for_status.return_value=None
        results=LawOpenClient('valid-oc').search('테스트법')
        self.assertEqual(results[0]['mst'],'12345')
        self.assertEqual(mock_get.call_args.kwargs['params']['target'],'law')

    @patch('ruleshift.law_api.requests.get')
    def test_search_live_law_tag(self,mock_get):
        mock_get.return_value.status_code=200
        mock_get.return_value.content='''<LawSearch><law><법령일련번호>12345</법령일련번호><법령명한글>실서버 법령</법령명한글><공포일자>20261020</공포일자></law></LawSearch>'''.encode('utf-8')
        mock_get.return_value.raise_for_status.return_value=None
        results=LawOpenClient('valid-oc').search('실서버 법령')
        self.assertEqual(results[0]['mst'],'12345')

    @patch('ruleshift.law_api.requests.get')
    def test_body_xml_parser(self,mock_get):
        mock_get.return_value.status_code=200
        mock_get.return_value.content='''<법령><기본정보><법령명_한글>테스트법</법령명_한글><공포일자>20261020</공포일자><시행일자>20270101</시행일자></기본정보><조문><조문단위><조문번호>1</조문번호><조문제목>한도</조문제목><조문내용>제1조(한도) 채권 한도는 20퍼센트 이하로 한다.</조문내용></조문단위></조문></법령>'''.encode('utf-8')
        mock_get.return_value.raise_for_status.return_value=None
        doc=LawOpenClient('valid-oc').fetch('12345')
        self.assertEqual(doc.title,'테스트법')
        self.assertIn('채권 한도',doc.text)
        self.assertFalse(doc.verified)
        self.assertEqual(doc.stage,'공포/고시')

    @patch('ruleshift.law_api.requests.get')
    def test_nested_official_sections_are_compared_without_false_article_additions(self, mock_get):
        from ruleshift.compare import compare
        def xml(changed: bool) -> bytes:
            ending = '개정' if changed else '종전'
            new_side = ('<부칙단위><부칙공포일자>20260908</부칙공포일자>'
                        '<부칙공포번호>99</부칙공포번호><부칙내용>부칙 제1조(시행일) 2027년부터 시행한다.</부칙내용></부칙단위>') if changed else ''
            return (f'<법령><기본정보><법령명_한글>일반법</법령명_한글></기본정보><조문>'
                    f'<조문단위><조문번호>1</조문번호><조문내용>제1조(목적)</조문내용>'
                    f'<항><항내용>① {ending} 목적</항내용><호><호내용>1. {ending} 세부 기준</호내용>'
                    f'<목><목내용>가. {ending} 목록</목내용></목></호></항></조문단위>'
                    f'<조문단위><조문번호>2</조문번호><조문내용>제2조(정의) 동일</조문내용></조문단위>'
                    f'</조문><부칙><부칙단위><부칙공포일자>20240101</부칙공포일자>'
                    f'<부칙공포번호>1</부칙공포번호><부칙내용>부칙 제1조(시행일) 기존 내용</부칙내용>'
                    f'</부칙단위>{new_side}</부칙></법령>').encode('utf-8')
        mock_get.return_value.status_code=200
        mock_get.return_value.content=xml(False)
        before=LawOpenClient('valid-oc').fetch('100')
        mock_get.return_value.content=xml(True)
        after=LawOpenClient('valid-oc').fetch('101')
        self.assertIn('세부 기준', after.text)
        self.assertIn('목록', after.text)
        changes=compare(before,after)
        self.assertEqual([(c.kind,c.clause_id) for c in changes],
                         [('수정','제1조'),('신설','부칙(20260908-99)')])

    @patch('ruleshift.law_api.requests.get')
    def test_request_failure_never_exposes_oc(self, mock_get):
        import requests
        mock_get.side_effect=requests.ConnectionError('URL contains private-oc-value')
        with self.assertRaises(RuntimeError) as error:
            LawOpenClient('private-oc-value').search('일반법')
        self.assertNotIn('private-oc-value',str(error.exception))

    def test_markdown_report(self):
        old=make('제1조(한도)\n채권 운용비율 한도는 35퍼센트 이하로 한다.')
        new=make('제1조(한도)\n채권 운용비율 한도는 30퍼센트 이하로 한다.',version='2')
        result=markdown_report(run_analysis(old,new))
        self.assertIn('변경 전',result)
        self.assertIn('검증 경고',result)
