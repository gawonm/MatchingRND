import unittest

from app.scripts.finetune_ntis_embedding import window,clean_validation
from app.scripts.prepare_ntis_training_data import validate_draft, select_projects


class CharacterTokenizer:
    def encode(self,text,add_special_tokens=True):
        return list(range(len(text)+(2 if add_special_tokens else 0)))

    def __call__(self,text,**kwargs):
        return {'offset_mapping':[(i,i+1) for i in range(len(text))]}


class NTISFinetuningTests(unittest.TestCase):
    def test_training_window_keeps_evidence_instead_of_blind_prefix(self):
        quote='required evidence near the end'
        text='a'*900+quote+'b'*30
        result=window(text,'project',quote,CharacterTokenizer())
        self.assertIn(quote,result)
        self.assertLessEqual(len(result)+2,384)
        self.assertFalse(result.endswith('a'*100))
        with self.assertRaises(ValueError): window('a'*800,'project','a'*500,CharacterTokenizer())

    def test_source_anchor_copied_and_unknown_negatives_rejected(self):
        job={'split':'train','job_id':'train-p','source_group_id':'g',
             'positive':{'document_id':'ntis-1','anchors':[{'anchor_id':'anchor','text':'exact source quote'}]},
             'negative_candidates':[{'document_id':'ntis-2','anchors':[{'text':'actual negative quote'}]}]}
        raw={'questions':[dict(style=s,query='a source-grounded retrieval query of sufficient length',
            anchor_id='anchor',negative_document_ids=['ntis-2']) for s in ('technical','scenario')]}
        result=validate_draft(job,raw)
        self.assertEqual(result[0]['evidence'][0]['text'],'exact source quote')
        raw['questions'][0]['negative_document_ids']=['unknown']
        with self.assertRaises(ValueError):validate_draft(job,raw)

    def test_sampling_keeps_one_representative_per_family(self):
        docs=[dict(document_id='ntis-'+str(i),group_id=str(i//2),metadata={'science_medium':'m'},
                   full_text='연구목표: '+'구체적인 기술 연구목표와 내용입니다. '*10) for i in range(10)]
        chosen=select_projects(docs,4,123)
        self.assertEqual(len({d['group_id'] for d in chosen}),4)
        self.assertEqual(chosen,select_projects(docs,4,123))

    def test_decontamination_removes_entire_validation_project(self):
        docs={i:dict(document_id=i,full_text='연구목표: '+body) for i,body in
              [('t','shared research detail '*10),('v','shared research detail '*10),('other','different technical subject '*10)]}
        train=[dict(query='same question',relevant_document_ids=['t'])]
        validation=[dict(query='same question',relevant_document_ids=['v']),
                    dict(query='another question',relevant_document_ids=['v']),
                    dict(query='independent',relevant_document_ids=['other'])]
        kept,removed=clean_validation(train,validation,docs)
        self.assertEqual(kept,[validation[-1]])
        self.assertEqual(removed[0]['document_id'],'v')


if __name__=='__main__':unittest.main()
