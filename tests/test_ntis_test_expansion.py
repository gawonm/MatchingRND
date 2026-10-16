import tempfile
import unittest
from pathlib import Path

import numpy as np

from app.scripts.expand_ntis_test import proportional_sample,validate,assert_frozen,score_vectors,clustered_delta
from app.scripts.retrain_rfp_embedding import dump,digest


def document(i,field):
    return dict(document_id=f'ntis-{i}',group_id=f'g{i}',metadata={'science_medium':field},
                full_text='연구내용: '+'고유 기술 설계와 분석 평가를 수행합니다. '*8)


class ExpansionTests(unittest.TestCase):
    def test_sampling_preserves_field_shares_and_is_order_independent(self):
        docs=[document(i,'large' if i<16 else 'small') for i in range(20)]
        chosen=proportional_sample(docs,10,123)
        self.assertEqual(chosen,proportional_sample(list(reversed(docs)),10,123))
        self.assertEqual(sum(d['metadata']['science_medium']=='large' for d in chosen),8)
        self.assertEqual(len({d['group_id'] for d in chosen}),10)

    def test_validation_copies_fixed_evidence_and_rejects_unknown_anchor(self):
        job=dict(job_id='j',source_document_id='ntis-1234567890',source_group_id='g',
            science_medium='engineering',title='title',anchors=[dict(anchor_id='a',text='literal source evidence',
                relevant_document_ids=['ntis-1234567890','ntis-1234567891'])])
        raw=dict(questions=[dict(style=s,need_statement='We need reliable technical capability for this scenario '+s,anchor_id='a',context_id='c0',source_term='literal')
                             for s in ('technical','scenario','constraint')])
        accepted,rejected=validate(job,raw)
        self.assertEqual(len(accepted),3)
        self.assertFalse(rejected)
        self.assertEqual(accepted[0]['relevant_document_ids'],['ntis-1234567890','ntis-1234567891'])
        self.assertTrue(all(e['text']=='literal source evidence' for e in accepted[0]['evidence']))
        raw['questions'][0]['anchor_id']='invented'
        accepted,rejected=validate(job,raw)
        self.assertEqual(len(accepted),2)
        self.assertEqual(rejected[0]['reason'],'unknown source anchor')

    def test_freeze_detects_modified_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.json';source.write_text('original',encoding='utf8')
            dump(root/'frozen_inputs.json',{str(source):digest(source)})
            assert_frozen(root)
            source.write_text('changed',encoding='utf8')
            with self.assertRaises(ValueError):assert_frozen(root)

    def test_scoring_uses_document_ids_and_any_recorded_positive(self):
        corpus=[dict(document_id='a'),dict(document_id='b'),dict(document_id='c')]
        result=score_vectors(np.array([[.3,.9,.8]]),corpus,
            [dict(query_id='q',relevant_document_ids=['b','c'])])
        self.assertEqual(result['aggregate']['hit_at_1'],1)
        self.assertEqual(result['results'][0]['top_10_document_ids'],['b','c','a'])

    def test_bootstrap_clusters_questions_from_same_source(self):
        questions=[dict(query_id=i,relevant_document_ids=[d]) for i,d in [('q1','a'),('q2','a'),('q3','b')]]
        assignment={'a':{'group_id':'ga'},'b':{'group_id':'gb'}}
        base={'results':[dict(query_id=q['query_id'],first_relevant_rank=2 if q['query_id']!='q3' else 1) for q in questions]}
        tuned={'results':[dict(query_id=q['query_id'],first_relevant_rank=1) for q in questions]}
        result=clustered_delta(questions,base,tuned,assignment,repeats=200,seed=5)
        self.assertEqual(result['clusters'],2)
        self.assertAlmostEqual(result['metrics']['hit_at_1']['delta'],2/3)
        self.assertEqual(result['metrics']['hit_at_1']['ci95_low'],0)
        self.assertEqual(result['metrics']['hit_at_1']['ci95_high'],1)


if __name__=='__main__':unittest.main()
