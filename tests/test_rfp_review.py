import json
import tempfile
import unittest
from pathlib import Path

from langchain_core.documents import Document
from app.rfp_rag.review import apply_review


def fragment(text, page=1, kind='text', bbox=None):
    return Document(page_content=text, metadata={'kind': kind, 'page': page,
                    'bbox': bbox or [0, 0, 100, 10], 'block_id': str(page) + ':1'})


def task(identity='a'):
    return {'task_id': identity, 'filename': 'test.pdf', 'source': 'test.pdf',
            'file_hash': 'hash', 'document_id': 'doc', 'title': '센서 개발',
            'task_number': '01', 'task_type': 'standalone', 'parent_task_id': None,
            'parent_title': None, 'fields': {'개발내용': [fragment('센서 융합 개발')]},
            'metrics': [], 'boundary_pages': [1]}


class RfpReviewTests(unittest.TestCase):
    def run_review(self, tasks, issues, decision=None):
        with tempfile.TemporaryDirectory() as tmp:
            policy = Path(tmp) / 'policy.json'
            policy.write_text(json.dumps({'files': {'test.pdf': decision} if decision else {}},
                                        ensure_ascii=False), encoding='utf-8')
            return apply_review(tasks, issues, Path(tmp), Document, policy)

    def test_unreviewed_ambiguous_task_is_not_searchable(self):
        safe, outcomes = self.run_review([task()], [{'filename': 'test.pdf', 'page': 1,
                                                    'reason': '제목·과제 경계 검수 필요'}])
        self.assertFalse(safe)
        self.assertEqual(outcomes[0]['status'], 'hold')

    def test_merged_metric_values_cannot_leak_through_duplicate_text_or_payload(self):
        t = task()
        t['fields']['성능지표'] = [fragment('정확도 | 99', 2, 'metric_table', [0, 20, 100, 60])]
        t['fields']['기타 원문'] = [fragment('목표 99', 2, bbox=[10, 30, 90, 40])]
        t['metrics'] = [{'page': 2, 'indicator': '정확도', 'goals': ['99']}]
        safe, _ = self.run_review([t], [{'filename': 'test.pdf', 'page': 2,
                                         'reason': '병합 성능표 헤더 확인 필요'}],
                                  {'file_hash': 'hash', 'action': 'approve', 'reason': '본문 확인'})
        self.assertEqual(len(safe), 1)
        self.assertFalse(safe[0]['metrics'])
        self.assertFalse(safe[0]['fields']['기타 원문'])
        self.assertIn('센서 융합', safe[0]['fields']['개발내용'][0].page_content)

    def test_stale_source_requires_review(self):
        with self.assertRaisesRegex(ValueError, '원본이 변경'):
            self.run_review([task()], [], {'file_hash': 'old', 'action': 'approve', 'reason': '확인'})

    def test_held_parent_and_child_are_removed_but_sibling_survives(self):
        parent, child, sibling = task('parent'), task('child'), task('sibling')
        child['parent_task_id'] = 'parent'
        safe, _ = self.run_review([parent, child, sibling], [], {'file_hash': 'hash',
                       'action': 'approve', 'reason': '확인', 'hold_tasks': ['parent']})
        self.assertEqual([t['task_id'] for t in safe], ['sibling'])

    def test_application_form_is_not_in_reviewed_page_range(self):
        records = [{'block_id': '3:0', 'page': 3, 'bbox': [0, 0, 100, 10],
                    'text': '과제명 | 센서 개발', 'role': 'quarantine'},
                   {'block_id': '3:1', 'page': 3, 'bbox': [0, 20, 100, 30],
                    'text': '개발내용\n센서 융합 개발', 'role': 'quarantine'},
                   {'block_id': '4:0', 'page': 4, 'bbox': [0, 0, 100, 10],
                    'text': '신청서 이름 생년월일', 'role': 'quarantine'}]
        safe, _ = self.run_review([task()], [{'filename': 'test.pdf', 'audit': True,
                                                'blocks': records}], {'file_hash': 'hash',
            'action': 'approve', 'reason': 'RFP 페이지 확인', 'replacement_tasks': [
                {'title': '센서 개발', 'page_start': 3, 'page_end': 3}]})
        text = ' '.join(f.page_content for fs in safe[0]['fields'].values() for f in fs)
        self.assertIn('센서 융합', text)
        self.assertNotIn('생년월일', text)

    def test_changed_task_ids_do_not_silently_ignore_decision(self):
        with self.assertRaisesRegex(ValueError, '파싱 결과가 변경'):
            self.run_review([task()], [], {'file_hash': 'hash', 'action': 'approve',
                           'reason': '확인', 'hold_tasks': ['old-id']})

    def test_runtime_payload_keeps_evidence_without_repeated_table_copies(self):
        from app.common.supabase_ingestion import retrieval_tasks, retrieval_metadata, unpack
        t = task()
        f = t['fields']['개발내용'][0]
        f.metadata['cells'] = ['large full table repeated in each sentence']
        f.metadata['original_text'] = '센서 융합 개발'
        packed = retrieval_tasks([t])
        restored = unpack(packed)[0]['fields']['개발내용'][0]
        self.assertEqual(restored.page_content, f.page_content)
        self.assertEqual(restored.metadata['bbox'], f.metadata['bbox'])
        self.assertEqual(restored.metadata['block_id'], f.metadata['block_id'])
        self.assertNotIn('cells', restored.metadata)
        self.assertIn('cells', f.metadata)  # Raw audit is untouched.
        slim = retrieval_metadata({'sources': [f.metadata]})
        self.assertNotIn('cells', slim['sources'][0])


if __name__ == '__main__':
    unittest.main()
