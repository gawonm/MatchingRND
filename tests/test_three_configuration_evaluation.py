import unittest

from app.scripts.evaluate_three_configurations import retrieval_metrics, CONFIGS


def qrel(doc, gain, status='JUDGED_RELEVANT', evidence='E01-01'):
    return {'문서 ID': doc, 'gain': gain, '판정 상태': status, 'Evidence ID': evidence}


class RetrievalEvaluationTests(unittest.TestCase):
    def test_unjudged_and_unknown_keep_ranks(self):
        result = retrieval_metrics(['unjudged', 'unknown', 'answer'],
                                   [qrel('unknown', 0, 'KNOWN_UNKNOWN'), qrel('answer', 3)])
        self.assertAlmostEqual(result['mrr_at_10'], 1/3)
        self.assertEqual(result['ranked'], ['unjudged', 'unknown', 'answer'])

    def test_adjacent_is_not_recall_positive_but_has_evidence_gain(self):
        result = retrieval_metrics(['adjacent'], [qrel('adjacent', 1), qrel('answer', 3, evidence='E01-02')])
        self.assertEqual(result['recall_at_10'], 0)
        self.assertEqual(result['doc_evidence_recall_at_10'], .5)
        self.assertGreater(result['ndcg_at_10'], 0)

    def test_duplicate_chunks_do_not_consume_ranks(self):
        result = retrieval_metrics(['a', 'a', 'answer'], [qrel('answer', 2)])
        self.assertEqual(result['mrr_at_10'], .5)

    def test_perfect_retrieval_is_100(self):
        self.assertEqual(retrieval_metrics(['answer'], [qrel('answer', 3)])['score_100'], 100)

    def test_no_positive_labels_are_na(self):
        result = retrieval_metrics(['unknown'], [qrel('unknown', 0, 'KNOWN_UNKNOWN')])
        self.assertIsNone(result['score_100'])
        self.assertIsNone(result['mrr_at_10'])

    def test_three_arms(self):
        self.assertEqual(CONFIGS['A'], set())
        self.assertEqual(CONFIGS['B'], {'rfp'})
        self.assertEqual(CONFIGS['C'], {'rfp', 'technology', 'ntis'})


if __name__ == '__main__':
    unittest.main()
