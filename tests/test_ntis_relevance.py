"""NTIS A/B filtering with injected LLM decisions; no DB or API calls."""
import json
import unittest
from contextlib import ExitStack
from types import ModuleType
from unittest.mock import Mock, patch

from app.ntis_rag.pipeline import run_ntis_pipeline, run_ntis_module
from app.ntis_rag.retrieval.eligibility import TechnologyRelevanceGate


def fixtures(pairs):
    projects, decisions = [], {}
    for i, (a, b) in enumerate(pairs):
        pid = f'p{i}'
        text = f'{pid} autonomous driving and sensor fusion research with additional prediction C.'
        projects.append(dict(project_id=pid, project_title=pid, text=text, rank=i + 1))
        decisions[pid] = (a, b)

    def judge(messages, model):
        data = json.loads(messages[-1]['content'])
        def judgment(payload):
            pid = payload['project_text'].split()[0]
            relation = decisions[pid][0 if payload['role'] == 'owned' else 1]
            return dict(relation=relation, reason='LLM semantic judgment',
                        quote=payload['project_text'] if relation in {'same', 'similar'} else '')
        if 'jobs' in data:
            return model(results=[{'job_index': job['job_index'], 'judgment': judgment(job['input'])}
                                  for job in data['jobs']])
        return model(**judgment(data))

    return projects, Mock(side_effect=judge)


class NtisRelevanceTests(unittest.TestCase):
    def run_backend(self, backend, projects, judge, **options):
        analysis = ModuleType('app.ntis_rag.generation.analysis')
        analysis.structure_query = Mock(return_value={'search_query': 'rewritten query'})
        analysis.extract_all_project_tech = Mock(return_value=[])
        analysis.canonicalize_technologies = Mock(return_value=[])
        analysis.aggregate_prior_rd_axes = Mock(return_value=[])
        retriever = Mock(return_value=projects)
        kwargs = dict(owned_technologies=['A'], requested_technologies=['B'],
                      external_technologies=[], analysis_top_n=10, relevance_llm=judge)
        kwargs.update(options)
        with ExitStack() as stack:
            stack.enter_context(patch.dict('sys.modules', {analysis.__name__: analysis}))
            if backend == 'local':
                retrieval = ModuleType('app.ntis_rag.retrieval.pipeline')
                retrieval.retrieve_ntis = retriever
                stack.enter_context(patch.dict('sys.modules', {retrieval.__name__: retrieval}))
                result = run_ntis_module('original problem B', **kwargs)
            else:
                from app.common import supabase_retrieval
                stack.enter_context(patch.object(supabase_retrieval, 'retrieve_ntis', retriever))
                result = supabase_retrieval.run_ntis_module('original problem B', **kwargs)
        return result, analysis, retriever

    def test_all_nine_combinations_in_both_backends(self):
        pairs = [(a, b) for a in ('same', 'similar', 'different')
                 for b in ('same', 'similar', 'different')]
        for backend in ('local', 'supabase'):
            with self.subTest(backend=backend):
                projects, judge = fixtures(pairs)
                result, analysis, _ = self.run_backend(backend, projects, judge)
                accepted = {'ntis-p0', 'ntis-p1', 'ntis-p3', 'ntis-p4'}
                self.assertEqual({c.doc_id for c in result.candidates}, accepted)
                self.assertEqual({h.doc_id for h in result.hits}, accepted)
                extracted = analysis.extract_all_project_tech.call_args.args[0]
                self.assertEqual({p['project_id'] for p in extracted}, {'p0', 'p1', 'p3', 'p4'})
                self.assertEqual(result.extra['related_projects'], extracted)
                self.assertEqual(judge.call_count, 4)
                self.assertTrue(all(c.extra['technology_relevance']['accepted'] for c in result.candidates))

    def test_rejected_top_projects_do_not_consume_limit(self):
        projects, judge = fixtures([('same', 'different'), ('different', 'same'), ('similar', 'similar')])
        for backend in ('local', 'supabase'):
            result, _, retriever = self.run_backend(backend, projects, judge, analysis_top_n=1)
            self.assertEqual([c.doc_id for c in result.candidates], ['ntis-p2'])
            self.assertGreater(retriever.call_args.args[1], 1)

    def test_no_matches_leave_no_candidates_hits_or_expansion_elements(self):
        projects, judge = fixtures([('same', 'different'), ('different', 'similar')])
        for backend in ('local', 'supabase'):
            result, analysis, _ = self.run_backend(backend, projects, judge)
            self.assertEqual(result.candidates, [])
            self.assertEqual(result.hits, [])
            self.assertEqual(result.tech_elements, [])
            self.assertEqual(result.extra['status'], 'no_matches')
            analysis.extract_all_project_tech.assert_called_once_with([])

    def test_original_problem_is_B_when_no_external_technology_matched(self):
        projects, judge = fixtures([('similar', 'same')])
        for backend in ('local', 'supabase'):
            result, analysis, retriever = self.run_backend(
                backend, projects, judge, requested_technologies=None, external_technologies=[])
            self.assertEqual(len(result.candidates), 1)
            self.assertEqual(result.extra['diagnostics']['technology_relevance']['requested_technologies'],
                             ['original problem B'])
            self.assertIn('original problem B', retriever.call_args.args[0]['search_query'])
            analysis.structure_query.assert_called_once_with(
                problem='original problem B', owned_technologies=['A'], external_technologies=[])

    def test_external_C_cannot_replace_explicit_B(self):
        projects, judge = fixtures([('same', 'different')])
        result, _, _ = self.run_backend('local', projects, judge, external_technologies=['C'])
        self.assertEqual(result.candidates, [])
        targets = [json.loads(call.args[0][-1]['content'])['technology'] for call in judge.call_args_list]
        self.assertEqual(targets, ['A', 'B'])

    def test_additional_C_does_not_reject_project(self):
        projects, judge = fixtures([('same', 'similar')])
        result, _, _ = self.run_backend('local', projects, judge)
        self.assertEqual(len(result.candidates), 1)
        self.assertIn('additional prediction C', result.hits[0].text)

    def test_multiple_goals_can_map_to_different_projects_without_overclaiming(self):
        projects = [
            {'project_id': 'p0', 'project_title': 'p0', 'text': 'p0 owned A and goal B1 evidence', 'rank': 1},
            {'project_id': 'p1', 'project_title': 'p1', 'text': 'p1 owned A and goal B2 evidence', 'rank': 2},
        ]
        decisions = {
            'p0': {'A': 'same', 'B1': 'same', 'B2': 'different'},
            'p1': {'A': 'same', 'B1': 'different', 'B2': 'similar'},
        }
        def judge(messages, model):
            payload = json.loads(messages[-1]['content'])
            def judgment(data):
                pid = data['project_text'].split()[0]
                relation = decisions[pid][data['technology']]
                return dict(relation=relation, reason='독립 목표 판정',
                            quote=data['project_text'] if relation in {'same', 'similar'} else '')
            if 'jobs' in payload:
                return model(results=[{
                    'job_index': job['job_index'], 'judgment': judgment(job['input']),
                } for job in payload['jobs']])
            return model(**judgment(payload))
        result, _, _ = self.run_backend(
            'local', projects, Mock(side_effect=judge), requested_technologies=['B1', 'B2'])
        checks = {c.doc_id: c.extra['technology_relevance'] for c in result.candidates}
        self.assertEqual(set(checks), {'ntis-p0', 'ntis-p1'})
        self.assertEqual(checks['ntis-p0']['matched_goals'], ['B1'])
        self.assertEqual(checks['ntis-p0']['unmatched_goals'], ['B2'])
        self.assertEqual(checks['ntis-p1']['matched_goals'], ['B2'])
        self.assertEqual(checks['ntis-p1']['unmatched_goals'], ['B1'])

    def test_semantic_matching_does_not_require_keyword_overlap(self):
        project = {'text': 'laser ranging and inertial observation are jointly estimated'}
        judge = Mock(return_value={'relation': 'similar', 'reason': 'same function with different terminology',
                                   'quote': project['text']})
        check = TechnologyRelevanceGate('B', ['A'], llm=judge).check(project)
        self.assertTrue(check['accepted'])

    def test_forged_empty_or_negative_evidence_is_rejected(self):
        project = {'text': 'autonomous driving and sensor fusion research'}
        for relation, quote in [('same', 'invented evidence'), ('similar', ''),
                                ('different', project['text']), ('insufficient', project['text'])]:
            with self.subTest(relation=relation, quote=quote):
                judge = Mock(side_effect=[
                    dict(relation='same', reason='A', quote=project['text']),
                    dict(relation=relation, reason='B', quote=quote),
                ])
                self.assertFalse(TechnologyRelevanceGate('B', ['A'], llm=judge).check(project)['accepted'])

    def test_only_whitespace_differences_are_allowed_in_quotes(self):
        judge = Mock(return_value=dict(relation='similar', reason='semantic match', quote='sensor fusion'))
        self.assertTrue(TechnologyRelevanceGate('B', ['A'], llm=judge).check(
            {'text': 'sensor\nfusion'})['accepted'])

    def test_no_cross_project_evidence(self):
        judge = Mock(return_value=dict(relation='same', reason='match', quote='other project evidence'))
        self.assertFalse(TechnologyRelevanceGate('B', ['A'], llm=judge).check(
            {'text': 'current project evidence'})['accepted'])

    def test_one_owned_and_one_requested_match_accepts_only_the_matched_goal(self):
        project = {'text': 'research evidence'}
        def judge(messages, model):
            technology = json.loads(messages[-1]['content'])['technology']
            relation = 'different' if technology in {'A2', 'B2'} else 'similar'
            return model(relation=relation, reason='semantic judgment', quote=project['text'])
        gate = TechnologyRelevanceGate('problem', ['A1', 'A2'], ['B1', 'B2'], judge)
        check = gate.check(project)
        self.assertTrue(check['accepted'])
        self.assertEqual(check['matched_goals'], ['B1'])
        self.assertEqual(check['unmatched_goals'], ['B2'])

    def test_missing_inputs_or_text_never_bypass_gate(self):
        judge = Mock()
        self.assertFalse(TechnologyRelevanceGate('B', [], llm=judge).check({'text': 'research'})['accepted'])
        self.assertFalse(TechnologyRelevanceGate('B', ['A'], llm=judge).check({'text': ''})['accepted'])
        judge.assert_not_called()

    def test_malformed_judgment_rejected_and_api_failure_surfaces(self):
        gate = TechnologyRelevanceGate('B', ['A'], llm=Mock(return_value={'relation': 'unknown'}))
        self.assertFalse(gate.check({'text': 'research'})['accepted'])
        gate.llm = Mock(side_effect=RuntimeError('API failed'))
        with self.assertRaisesRegex(RuntimeError, 'API failed'):
            gate.check({'text': 'research'})

    def test_duplicate_projects_do_not_consume_slots(self):
        projects, judge = fixtures([('same', 'same'), ('same', 'similar')])
        result, _, _ = self.run_backend('local', [projects[0], projects[0], projects[1]], judge, analysis_top_n=2)
        self.assertEqual(len(result.candidates), 2)
        self.assertEqual(judge.call_count, 2)

    def test_invalid_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            run_ntis_pipeline('B', analysis_top_n=0, _retriever=Mock())


if __name__ == '__main__':
    unittest.main()
