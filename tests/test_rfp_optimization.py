import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.rfp_rag.retrieval.context_selection import select_sections, filter_candidates
from app.rfp_rag.retrieval.eligibility import TechnologyRelevanceGate, _quote_sections


class SourceSelectionTests(unittest.TestCase):
    def test_default_token_packing_combines_sources_that_exceed_char_budget(self):
        def respond(messages, model):
            payload = json.loads(messages[-1]['content'])
            def judgment(data):
                return {'matches': [dict(technology_index=t['index'], reason='no match',
                                         relation='insufficient', section_index=-1, quote='')
                                    for t in data['technologies']]}
            if 'jobs' in payload:
                return model.model_validate({'results': [dict(job_index=j['job_index'],
                    judgment=judgment(j['input'])) for j in payload['jobs']]})
            return model.model_validate(judgment(payload))

        tasks = [{'fields': {'요구기술': [SimpleNamespace(page_content='source ' * 2400,
                    metadata={'page': 1})]}} for _ in range(2)]
        with patch.dict('os.environ', {}, clear=True), \
             patch('app.rfp_rag.retrieval.eligibility._count_tokens', side_effect=lambda s: len(s)//5):
            token_llm, char_llm = Mock(side_effect=respond), Mock(side_effect=respond)
            default = TechnologyRelevanceGate({'owned_technologies':['A'],'unmet_elements':['B']}, token_llm)
            chars = TechnologyRelevanceGate({'owned_technologies':['A'],'unmet_elements':['B']}, char_llm,
                                             batch_mode='chars')
            self.assertEqual(default.check_many(tasks), chars.check_many(tasks))
            self.assertEqual(token_llm.call_count, 1)
            self.assertEqual(char_llm.call_count, 2)

    def test_whole_fragments_and_original_indices_are_preserved(self):
        sections = [dict(text=('turbine ' if i == 0 else 'wasteheat ' if i == 8 else 'unrelated ')*20,
                         item='개발내용',page=1,source='rfp') for i in range(10)]
        selected, changed = select_sections(sections,['turbine','wasteheat'],max_chars=800)
        self.assertTrue(changed)
        self.assertTrue({0,8}.issubset(r['_original_index'] for r in selected))
        for row in selected:
            self.assertEqual(row['text'], sections[row['_original_index']]['text'])
        self.assertEqual([r['_original_index'] for r in selected],sorted(r['_original_index'] for r in selected))

    def test_omitted_fragment_cannot_be_joined_into_a_quote(self):
        sections = [dict(text='first',item='x',page=1,source='rfp',_original_index=0),
                    dict(text='last',item='x',page=1,source='rfp',_original_index=2)]
        self.assertEqual(_quote_sections(sections,0,'firstlast'),[])

    def test_insufficient_excerpt_retries_full_source_once(self):
        task={'fields':{'요구기술':[SimpleNamespace(page_content='source'+str(i),metadata={'page':1}) for i in range(3)]}}
        gate=TechnologyRelevanceGate({'owned_technologies':['A'],'unmet_elements':['B']},llm=Mock(),context_mode='excerpt')
        checked=[{'accepted':False,'reason':'uncertain','matches':[
            dict(technology_index=0,verified=True,relation='same'),
            dict(technology_index=1,verified=False,relation='insufficient')]}]
        full=[{'accepted':True,'reason':'full source','matches':[]}]
        with patch('app.rfp_rag.retrieval.eligibility.select_sections',return_value=([{'text':'excerpt'}],True)), \
             patch.object(gate,'_judge_sections',side_effect=[checked,full]) as judge:
            self.assertTrue(gate.check(task)['accepted'])
        self.assertEqual(judge.call_count,2)
        self.assertEqual(len(judge.call_args_list[1].args[0][0]),3)
        self.assertEqual(gate.stats['full_fallback_tasks'],1)


class CandidateBudgetTests(unittest.TestCase):
    def fixture(self,n=20):
        candidates=[(str(i),1/(i+1)) for i in range(n)]
        chunks={str(i):SimpleNamespace(metadata={'task_id':str(i)}) for i in range(n)}
        tasks={str(i):{'id':i,'title':'turbine wasteheat' if i==19 else 'unrelated','fields':{}} for i in range(n)}
        gate=SimpleNamespace(active=True,owned=['wasteheat'],requested=['turbine'],runner=SimpleNamespace(batch_size=5))
        return candidates,chunks,tasks,gate

    def test_budget_does_not_stop_when_there_are_no_matches(self):
        candidates,chunks,tasks,gate=self.fixture()
        gate.check_many=Mock(side_effect=lambda batch:[{'accepted':False} for _ in batch])
        selected,checks,diag=filter_candidates(candidates,chunks,tasks,gate,3,window=10)
        self.assertEqual(selected,[])
        self.assertEqual(len(checks),20)
        self.assertEqual(diag['stop_reason'],'exhausted')

    def test_balanced_order_promotes_both_sides_and_reports_unexamined_tail(self):
        candidates,chunks,tasks,gate=self.fixture()
        gate.check_many=Mock(side_effect=lambda batch:[{'accepted':t['id']==19} for t in batch])
        selected,checks,diag=filter_candidates(candidates,chunks,tasks,gate,3,order='balanced',window=10)
        self.assertEqual(selected[0][0],'19')
        self.assertEqual(len(checks),10)
        self.assertEqual(diag['unexamined'],10)
        self.assertEqual(diag['stop_reason'],'budget_with_matches')


if __name__ == '__main__':
    unittest.main()
