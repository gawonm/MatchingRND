import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.ntis_rag.generation import analysis


def projects(n):
    return [dict(project_id=str(i), project_title=f'project {i}', text=f'UNIQUE_{i} source evidence')
            for i in range(n)]


def response(prompt):
    if '\nprojects:\n' in prompt:
        payload = json.loads(prompt.split('\nprojects:\n', 1)[1])
        return {'projects': [dict(project_index=p['project_index'], research_topic='topic',
                                 technology_elements=[dict(element='technology', evidence=p['text'])])
                             for p in reversed(payload)]}
    text = prompt.split('[과제 원문]\n', 1)[1].split('\n\n다음 JSON', 1)[0]
    return dict(research_topic='topic', technology_elements=[dict(element='technology', evidence=text)])


class NtisBatchExtractionTests(unittest.TestCase):
    def run_extraction(self, ps, respond=response, **env):
        llm = Mock()
        llm.invoke.side_effect = lambda prompt: SimpleNamespace(content=json.dumps(respond(prompt)))
        settings = {'NTIS_EXTRACTION_BATCH_SIZE': '5', 'NTIS_EXTRACTION_MAX_CHARS': '24000', **env}
        with patch.object(analysis, 'llm', llm), patch.dict('os.environ', settings):
            with analysis.track_llm_calls() as counts:
                result = analysis.extract_all_project_tech(ps)
        return result, llm, counts

    def test_ten_sources_use_two_calls_and_keep_source_order_and_evidence(self):
        ps = projects(10)
        rows, llm, counts = self.run_extraction(ps)
        self.assertEqual(llm.invoke.call_count, 2)
        self.assertEqual(counts['technology_extraction'], 2)
        self.assertEqual([r['project_id'] for r in rows], [p['project_id'] for p in ps])
        self.assertTrue(all(r['technology_elements'][0]['evidence'] == p['text'] for r,p in zip(rows,ps)))

    def test_cross_project_quote_retries_only_the_affected_source(self):
        ps = projects(3)
        def respond(prompt):
            value = response(prompt)
            if 'projects' in value:
                value['projects'][0]['technology_elements'][0]['evidence'] = ps[0]['text']
            return value
        rows, llm, _ = self.run_extraction(ps, respond)
        self.assertEqual(llm.invoke.call_count, 2)
        self.assertTrue(all(r['error'] is None for r in rows))
        self.assertEqual(rows[2]['technology_elements'][0]['evidence'], ps[2]['text'])

    def test_duplicate_indices_retry_all_and_do_not_reassign_sources(self):
        def respond(prompt):
            value = response(prompt)
            if 'projects' in value:
                value['projects'][0]['project_index'] = value['projects'][1]['project_index']
            return value
        rows, llm, _ = self.run_extraction(projects(3), respond)
        self.assertEqual(llm.invoke.call_count, 4)
        self.assertEqual([r['project_id'] for r in rows], ['0','1','2'])

    def test_failed_evidence_is_not_silently_accepted(self):
        def respond(prompt):
            value = response(prompt)
            entries = value['projects'] if 'projects' in value else [value]
            for row in entries:
                row['technology_elements'][0]['evidence'] = 'not present in any source'
            return value
        rows, llm, counts = self.run_extraction(projects(2), respond)
        self.assertEqual(llm.invoke.call_count, 5)
        self.assertEqual(counts['technology_extraction'], 5)
        self.assertTrue(all(r['error'] and not r['technology_elements'] for r in rows))

    def test_oversized_source_is_kept_whole_and_single_mode_is_available(self):
        ps = projects(2)
        ps[0]['text'] += ' X'*200
        rows, llm, _ = self.run_extraction(ps, NTIS_EXTRACTION_MAX_CHARS='100')
        self.assertEqual(llm.invoke.call_count, 2)
        self.assertEqual(rows[0]['technology_elements'][0]['evidence'], ps[0]['text'])
        _, single, _ = self.run_extraction(projects(6), NTIS_EXTRACTION_BATCH_SIZE='1')
        self.assertEqual(single.invoke.call_count, 6)

    def test_empty_input_has_no_calls_and_invalid_budget_raises(self):
        rows, llm, _ = self.run_extraction([])
        self.assertEqual(rows, [])
        llm.invoke.assert_not_called()
        with self.assertRaises(ValueError):
            self.run_extraction(projects(2), NTIS_EXTRACTION_BATCH_SIZE='0')


if __name__ == '__main__':
    unittest.main()
