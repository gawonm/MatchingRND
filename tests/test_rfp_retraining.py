import unittest

import numpy as np

from app.scripts.retrain_rfp_embedding import rank_metrics


class RankingTests(unittest.TestCase):
    def test_max_chunk_score_and_confirmed_duplicate_collapse(self):
        corpus=[{'task_id':'a'}, {'task_id':'a'}, {'task_id':'b'}, {'task_id':'c'}, {'task_id':'d'}]
        scores=np.array([[.9,.8,.85,.7,.6],[.1,.2,.9,.8,.7]])
        questions=[{'query_id':'one','relevant_task_ids':['c']},
                   {'query_id':'two','relevant_task_ids':['b']}]
        result=rank_metrics(scores,corpus,questions,[['a','b']])
        self.assertEqual([r['first_relevant_rank'] for r in result['results']],[2,1])
        self.assertEqual(result['aggregate']['hit_at_1'],.5)
        self.assertEqual(result['aggregate']['mrr_at_10'],.75)
        self.assertEqual(result['results'][0]['top_10_task_ids'],['a','c','d'])

    def test_outside_top_ten_has_zero_mrr(self):
        corpus=[{'task_id':str(i)} for i in range(12)]
        scores=np.array([list(range(12,0,-1))],dtype=float)
        result=rank_metrics(scores,corpus,[{'query_id':'one','relevant_task_ids':['11']}],[])
        self.assertEqual(result['results'][0]['first_relevant_rank'],12)
        self.assertEqual(result['aggregate']['mrr_at_10'],0)

    def test_technology_ids_preserved_without_family_collapse(self):
        corpus=[{'document_id':'pub-1','group_id':'family'},
                {'document_id':'pub-1','group_id':'family'},
                {'document_id':'pub-2','group_id':'family'}]
        result=rank_metrics(np.array([[.9,.8,.7]]),corpus,
            [{'query_id':'tech-one','relevant_document_ids':['pub-2']}],[])
        row=result['results'][0]
        self.assertEqual(row['first_relevant_rank'],2)
        self.assertEqual(row['top_10_document_ids'],['pub-1','pub-2'])
        self.assertNotIn('top_10_task_ids',row)


if __name__=='__main__':
    unittest.main()
