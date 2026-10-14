import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import nullcontext
from types import SimpleNamespace
from langchain_core.documents import Document
from app.rfp_rag.parsing.pdf_parser import parse_tasks
from app.rfp_rag.indexing.chunker import build_chunks


class CharacterTokenizer:
    def encode(self,text,**kwargs):
        return list(text)

def block(text,page=1,cells=None,kind='text'):
    return Document(page_content=text,metadata=dict(source='test.pdf',filename='test.pdf',page=page,
        bbox=[0,100,500,120],document_id='doc',file_hash='hash',kind=kind,**({'cells':cells} if cells else {})))

def row(label,value,page=1):
    return block(label+' | '+value,page,[label,value],'table_row')

def parse(blocks):
    return parse_tasks(blocks,[Path('test.pdf')],Path('.'),[],Document)


class RfpPreprocessingTests(unittest.TestCase):
    def test_preamble_is_preserved_as_context_not_first_task_content(self):
        blocks=[block('공고문: 접수는 온라인으로 진행합니다.',1),
                row('품목번호','2026-01',8),row('품목명','모터 제어 기술',8),block('□ 개발내용',8),block('고토크 모터 제어 기술',9)]
        tasks,issues,excluded=parse(blocks)
        self.assertFalse(excluded)
        self.assertEqual(tasks[0]['task_number'],'2026-01')
        self.assertNotIn('온라인',' '.join(f.page_content for fs in tasks[0]['fields'].values() for f in fs))
        audit=next(i for i in issues if i.get('audit'))
        self.assertEqual(len(audit['blocks']),len(blocks))
        self.assertEqual(audit['blocks'][0]['role'],'context')

    def test_total_and_children_do_not_mix_and_keep_numbers(self):
        blocks=[row('품목번호','2026-07'),row('총괄 품목명','(총괄) 항만 플랫폼'),block('□ 개발내용'),block('총괄 연계 기술'),
                row('품목번호','2026-07-01',2),row('총괄 품목명','(총괄) 항만 플랫폼',2),
                row('세부 품목명','(1세부) 자율주행 기술',2),block('□ 개발내용',2),block('자율주행 센서 기술',2),
                row('품목번호','2026-07-02',3),row('총괄 품목명','(총괄) 항만 플랫폼',3),
                row('세부 품목명','(2세부) 전동화 기술',3),block('□ 개발내용',3),block('저속 고토크 구동시스템',4)]
        tasks,issues,excluded=parse(blocks)
        self.assertEqual(len(tasks),3)
        self.assertEqual(tasks[2]['parent_task_id'],tasks[0]['task_id'])
        self.assertEqual(tasks[2]['task_number'],'2026-07-02')
        self.assertTrue(any('저속 고토크' in f.page_content for fs in tasks[2]['fields'].values() for f in fs))
        self.assertFalse(any('저속 고토크' in f.page_content for fs in tasks[1]['fields'].values() for f in fs))

    def test_unknown_title_quarantines_only_that_region(self):
        blocks=[row('과제명','정상 과제'),block('개발내용'),block('센서 융합'),
                block('품목명',2),block('소속이 불명확한 기술',2),
                row('품목번호','03',3),row('품목명','다음 정상 과제',3),block('개발내용',3),block('모터 제어',3)]
        tasks,issues,excluded=parse(blocks)
        self.assertEqual(len(tasks),2)
        self.assertFalse(excluded)
        self.assertFalse(any('불명확' in f.page_content for t in tasks for fs in t['fields'].values() for f in fs))
        audit=next(i for i in issues if i.get('audit'))
        self.assertEqual(len(audit['blocks']),len(blocks))
        self.assertTrue(any(r['role']=='quarantine' for r in audit['blocks']))

    def test_supplementary_text_survives_chunking_with_source_locations(self):
        tasks,_,_=parse([row('과제명','모터 개발'),block('개발내용'),block('고토크 모터'),block('기대효과'),block('실증 원문 유지')])
        chunks,_=build_chunks(tasks,{'test.pdf':[]},CharacterTokenizer(),1000,10,Document)
        self.assertIn('실증 원문 유지',' '.join(c.page_content for c in chunks))
        self.assertTrue(all(s.get('block_id') for c in chunks for s in c.metadata['sources']))

    def test_unknown_attachment_does_not_bleed_into_last_task(self):
        tasks,issues,_=parse([row('과제명','모터'),block('개발내용'),block('모터 제어'),
                             block('붙임 2 개인정보 동의서',2),block('개인정보 수집 동의',2)])
        self.assertFalse(any('개인정보' in f.page_content for fs in tasks[0]['fields'].values() for f in fs))

    def test_proposal_development_title_and_circled_sections(self):
        tasks,_,_=parse([row('① 개발과제명','소재 제조 기술'),block('⑦ 개발목표 및 개발필요성'),
                         block('고강도 소재 제조'),block('⑪ 개발내용'),block('공정 제어 기술')])
        self.assertEqual(tasks[0]['title'],'소재 제조 기술')
        self.assertTrue(any('공정 제어' in f.page_content for f in tasks[0]['fields']['개발내용']))

    def test_empty_metric_table_is_not_lost(self):
        metric=block('항목 | 목표',kind='metric_table')
        metric.metadata.update(headers=['항목','목표'],rows=[])
        tasks,_,_=parse([row('과제명','센서'),block('개발내용'),block('센서 개발'),metric])
        chunks,_=build_chunks(tasks,{'test.pdf':[]},CharacterTokenizer(),1000,10,Document)
        self.assertIn('항목 | 목표',' '.join(c.page_content for c in chunks))

    def test_repeated_task_header_continues_same_numbered_task(self):
        tasks,_,_=parse([row('품목번호','2026-01'),row('품목명','센서'),block('개발내용'),block('첫 원문'),
                         row('품목번호','2026-01',2),row('품목명','센서',2),block('개발내용',2),block('다음 원문',2)])
        self.assertEqual(len(tasks),1)
        self.assertTrue(any('다음 원문' in f.page_content for fs in tasks[0]['fields'].values() for f in fs))

    def test_request_name_and_support_target_stay_separate(self):
        tasks,_,_=parse([row('제안요청서명','연구 지원'),block('▶지원목적'),block('치료 가능성 연구'),
                        block('▶지원대상'),block('참여 연구기관')])
        self.assertIn('개발목표',tasks[0]['fields'])
        self.assertTrue(any('참여 연구기관' in f.page_content for f in tasks[0]['fields']['지원조건·특이사항']))

    def test_word_recovery_keeps_same_word_at_another_position(self):
        from app.rfp_rag.parsing.layout_recovery import recover_layout
        existing=block('센서')
        existing.metadata['bbox']=[0,0,100,20]
        words=[dict(text='센서',x0=10,x1=30,top=5,bottom=15),
               dict(text='센서',x0=10,x1=30,top=50,bottom=60)]
        page=SimpleNamespace(height=842,extract_words=lambda **kwargs:words)
        page.dedupe_chars=lambda **kwargs:page
        issues=[]
        with patch('pdfplumber.open',return_value=nullcontext(SimpleNamespace(pages=[page]))):
            result=recover_layout(Path('test.pdf'),[existing],issues,Document)
        self.assertEqual(len(result),2)
        self.assertTrue(result[1].metadata['recovered_layout'])

    def test_page_marker_is_audited_but_not_embedded_as_requirement(self):
        tasks,issues,_=parse([row('과제명','센서'),block('개발내용'),block('센서 개발'),block('99',kind='page_marker')])
        self.assertFalse(any(f.page_content=='99' for fs in tasks[0]['fields'].values() for f in fs))
        audit=next(i for i in issues if i.get('audit'))
        self.assertEqual(audit['blocks'][-1]['role'],'context')

    def test_bottom_table_numeric_target_is_preserved(self):
        number=block('95')
        number.metadata.update(bbox=[490,805,510,820],recovered_layout=True,page_height=842,page_width=595)
        tasks,_,_=parse([row('과제명','센서'),block('성능지표'),number])
        self.assertTrue(any(f.page_content=='95' for f in tasks[0]['fields']['성능지표']))

if __name__=='__main__':
    unittest.main()
