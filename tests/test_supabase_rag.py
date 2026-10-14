import unittest
from unittest.mock import Mock, patch

from app.common.embedding import DIMENSION, MODEL, require_model
from app.common.supabase_store import SupabaseRepository, vector_literal, corpus_fingerprint
from app.common.supabase_ingestion import pack, unpack
from app.common.supabase_retrieval import flat_filter, DatabaseVectorStore
from app.orchestrator import RagOrchestrator


class SupabaseTests(unittest.TestCase):
    def test_reject_incompatible_or_invalid_vectors(self):
        for vector in ([1.0]*1536, [float('nan')]*DIMENSION, [0.0]*DIMENSION):
            with self.assertRaises(ValueError):
                vector_literal(vector)
        self.assertTrue(vector_literal([1.0]+[0.0]*(DIMENSION-1)).startswith('[1.0,'))
        with self.assertRaises(ValueError):
            require_model('BAAI/bge-m3')
        self.assertEqual(require_model(MODEL),MODEL)

    def test_fingerprint_detects_same_count_content_and_metadata_changes(self):
        a = corpus_fingerprint([{'title':'열교환기'}],[{'content':'설계'}],{})
        self.assertNotEqual(a,corpus_fingerprint([{'title':'열교환기'}],[{'content':'터빈'}],{}))
        self.assertNotEqual(a,corpus_fingerprint([{'title':'열교환기','institution':'기관'}],[{'content':'설계'}],{}))

    def test_pdf_requirements_survive_json_roundtrip(self):
        import json
        from langchain_core.documents import Document
        original = {'fields':{'개발목표':[Document(page_content='열교환기 설계',metadata={'page':2,'bbox':[1,2,3,4]})]}}
        restored = unpack(json.loads(json.dumps(pack(original))))['fields']['개발목표'][0]
        self.assertEqual(restored.page_content,'열교환기 설계')
        self.assertEqual(restored.metadata,original['fields']['개발목표'][0].metadata)

    def test_metadata_filter_semantics(self):
        self.assertEqual(flat_filter({'$and':[{'task_id':'t1'},{'item':'개발목표'}]}),{'task_id':'t1','item':'개발목표'})
        with self.assertRaises(ValueError):
            flat_filter({'$and':[{'item':'a'},{'item':'b'}]})
        with self.assertRaises(ValueError):
            flat_filter({'$or':[{'item':'a'}]})

    def test_dense_adapter_preserves_full_metadata_and_distance(self):
        repo = Mock()
        repo.search.return_value = [{'content':'요구기술','metadata':{'chunk_id':'c','pages':[1,2]},'similarity':0.75}]
        with patch('app.common.supabase_retrieval.get_embedder') as embedder:
            embedder.return_value.encode_query.return_value = [1.0]*DIMENSION
            store = DatabaseVectorStore('rfp',repo)
            doc,distance = store.similarity_search_with_score('질문',filter={'$and':[{'task_id':'t'}]})[0]
        self.assertEqual(doc.metadata['pages'],[1,2])
        self.assertEqual(distance,0.25)
        self.assertEqual(repo.search.call_args.args[-1],{'task_id':'t'})

    def test_cloud_orchestrator_does_not_build_pdf_index(self):
        coordinator = RagOrchestrator(backend='supabase')
        with patch('app.common.supabase_retrieval.load_pdf_index',return_value={'cloud':True}) as loader, \
             patch('app.rfp_rag.pipeline.build_index',side_effect=AssertionError('must not rebuild')), \
             patch('app.rfp_rag.pipeline.search_module_result',return_value='result') as search:
            self.assertEqual(coordinator._rfp_search('query'),'result')
            self.assertEqual(coordinator._rfp_search('again'),'result')
        loader.assert_called_once_with('rfp')
        self.assertEqual(search.call_count,2)

    def test_pdf_grouping_retains_task_order_with_many_blocks(self):
        from pathlib import Path
        from langchain_core.documents import Document
        from app.rfp_rag.parsing.pdf_parser import parse_tasks
        files = [Path('first.pdf'),Path('second.pdf')]
        blocks = []
        for file in files:
            meta = {'source':file.name,'filename':file.name,'document_id':file.stem,'file_hash':'hash',
                    'page':1,'bbox':[0,0,100,20],'kind':'table_row'}
            blocks.append(Document(page_content='과제명 | '+file.stem,metadata={**meta,'cells':['과제명',file.stem]}))
            blocks.extend(Document(page_content='개발목표 | 열교환기 설계',metadata={**meta,'cells':['개발목표','열교환기 설계']}) for _ in range(100))
        with patch('app.rfp_rag.parsing.pdf_parser._source_key',side_effect=lambda p,r:p.name) as key:
            tasks,_,_ = parse_tasks(blocks,files,Path('.'),[],Document)
        self.assertEqual([task['title'] for task in tasks],['first','second'])
        self.assertEqual(len(tasks[0]['fields']['개발목표']),100)
        self.assertLessEqual(key.call_count,len(files))


if __name__ == '__main__':
    unittest.main()
