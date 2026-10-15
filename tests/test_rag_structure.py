"""Exercise parsing -> indexing -> retrieval through reorganized entrypoints."""
import importlib
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from app.policy_rag.pipeline import search_module_result as search_policy
from app.rfp_rag.pipeline import search_module_result as search_rfp


class Document:
    def __init__(self, page_content, metadata):
        self.page_content = page_content
        self.metadata = metadata


class Tokenizer:
    def encode(self, text, **options):
        return list(text)


class Retriever:
    def __init__(self, docs):
        self.docs = docs

    def invoke(self, query):
        return self.docs[:self.k] if hasattr(self, 'k') else self.docs

    @classmethod
    def from_documents(cls, docs, preprocess_func):
        for doc in docs:
            preprocess_func(doc.page_content)
        return cls(docs)


class VectorStore:
    def __init__(self, **options):
        self.docs = {}

    def get(self, **options):
        return {'ids': list(self.docs)}

    def add_documents(self, docs, ids):
        self.docs.update(zip(ids, docs))

    def delete(self, ids):
        for cid in ids:
            self.docs.pop(cid, None)

    def as_retriever(self, **options):
        return Retriever(list(self.docs.values()))


def fake_dependencies():
    exports = {
        'langchain_huggingface': {'HuggingFaceEmbeddings': lambda **kw: SimpleNamespace(
            _client=SimpleNamespace(tokenizer=Tokenizer(), max_seq_length=5000))},
        'langchain_chroma': {'Chroma': VectorStore},
        'langchain_community.retrievers': {'BM25Retriever': Retriever},
        'kiwipiepy': {'Kiwi': lambda: SimpleNamespace(tokenize=lambda text: [
            SimpleNamespace(form=word) for word in text.split()])},
    }
    modules = {}
    for name, attributes in exports.items():
        module = ModuleType(name)
        module.__dict__.update(attributes)
        modules[name] = module
    return modules


def config(root, module):
    return {'data_dir': root, 'OUTPUT': root / 'db', 'pdf_files': [root / 'sample.pdf'],
            'EMBEDDING_MODEL' if module == 'rfp' else 'MODEL': 'fake-model',
            'CHUNK_TOKENS': 1400, 'OVERLAP_TOKENS': 100, 'KEYWORD_K': 30,
            'VECTOR_K': 30, 'TOP_K': 5, 'RRF_K': 60, 'CONTEXT_TOKENS': 3500}


class RagStructureTests(unittest.TestCase):
    def test_rfp_parse_index_search(self):
        builder = importlib.import_module('app.rfp_rag.indexing.build_index')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            meta = {'source': 'sample.pdf', 'filename': 'sample.pdf', 'document_id': 'rfp-doc',
                    'file_hash': 'hash', 'page': 1, 'bbox': [0, 0, 100, 20], 'kind': 'table_row'}
            blocks = [Document('과제명 | 센서 융합 과제', {**meta, 'cells': ['과제명', '센서 융합 과제']}),
                      Document('개발목표 | 센서 융합 정확도 향상', {**meta, 'cells': ['개발목표', '센서 융합 정확도 향상']}),
                      Document('지원기간 | 2년', {**meta, 'cells': ['지원기간', '2년']})]
            with patch.dict('sys.modules', fake_dependencies()), \
                 patch.object(builder, 'load_config', return_value=config(root, 'rfp')), \
                 patch.object(builder, '_load_notices', return_value=(
                     {'n1': {'title': '연구개발 공고', 'url': 'https://example.com/notice'}},
                     {'sample.pdf': ['n1']}, [])), \
                 patch.object(builder, 'load_documents', return_value=(blocks, [], [])):
                index = builder.build_index()
            result = search_rfp(index, '센서 융합')
            self.assertEqual(len(result.candidates), 1)
            self.assertEqual(result.candidates[0].title, '센서 융합 과제')
            self.assertIn('센서 융합 정확도 향상', result.extra['context'])
            self.assertIn('지원기간', result.extra['context'])
            self.assertEqual(result.extra['sources'][0]['notice_urls'], ['https://example.com/notice'])
            self.assertTrue(result.candidates[0].evidences[0].verified)
            self.assertEqual(set(index['chunks_by_id']), {h.chunk_id for h in result.hits})

    def test_policy_parse_index_search(self):
        builder = importlib.import_module('app.policy_rag.indexing.build_index')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            meta = {'document_id': 'law-doc', 'law_name': '연구개발법', 'law_type': '법률',
                    'law_family': '연구개발법', 'filename': 'sample.pdf', 'source': 'sample.pdf',
                    'effective_date': '2026. 1. 1.', 'publication': '공포정보',
                    'source_url': 'https://example.com/law'}
            raw = {'metadata': meta, 'pages': [{'page': 1, 'blocks': [
                {'text': '제1조(목적) 연구개발 지원 기준을 정한다.', 'bbox': [0, 0, 100, 20]},
                {'text': '제2조(지원) 기술 개발을 지원한다.', 'bbox': [0, 30, 100, 50]},
                {'text': '[별표 1]\n별표 내용', 'bbox': [0, 60, 100, 80]},
            ]}]}
            with patch.dict('sys.modules', fake_dependencies()), \
                 patch.object(builder, 'load_config', return_value=config(root, 'policy')), \
                 patch.object(builder, 'load_documents', return_value=([raw], [], [])):
                index = builder.build_index()
            result = search_policy(index, '연구개발 지원')
            self.assertEqual(len(result.candidates), 2)
            self.assertEqual(result.candidates[0].evidences[0].page, 0)
            self.assertEqual(result.candidates[0].evidences[0].bbox.as_tuple(), (0, 0, 100, 20))
            self.assertTrue(result.candidates[0].evidences[0].verified)
            self.assertNotIn('별표 내용', result.extra['context'])
            self.assertEqual(result.extra['diagnostics']['excluded_section_count'], 2)
            self.assertEqual(result.candidates[0].extra['validity_status'], 'not_verified')

    def test_ntis_excel_parsing(self):
        import pandas as pd
        from app.ntis_rag.parsing.excel_loader import load_documents

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'ntis.xlsx'
            pd.DataFrame([{'과제번호': '001', '과제명': '센서 과제', '연구목표': '융합 정확도 향상',
                           '연구내용': '데이터이관 글자수 검증', '기대효과': '', '키워드': '센서',
                           '연구수행기관': '연구소'}]).to_excel(path, index=False)
            docs = load_documents(path, Document)
            self.assertEqual(docs[0].metadata['project_id'], '001')
            self.assertEqual(docs[0].metadata['research_agency'], '연구소')
            self.assertIn('연구목표: 융합 정확도 향상', docs[0].page_content)
            self.assertNotIn('데이터이관', docs[0].page_content)

    def test_ntis_pipeline_orchestration(self):
        from app.ntis_rag.pipeline import run_ntis_module
        analysis = ModuleType('app.ntis_rag.generation.analysis')
        analysis.structure_query = lambda **kw: {'search_query': '센서 질문'}
        analysis.extract_all_project_tech = lambda projects: []
        analysis.canonicalize_technologies = lambda analyses: []
        analysis.aggregate_prior_rd_axes = lambda technologies: []
        retrieval = ModuleType('app.ntis_rag.retrieval.pipeline')
        retrieval.retrieve_ntis = lambda query, limit: []
        with patch.dict('sys.modules', {analysis.__name__: analysis, retrieval.__name__: retrieval}):
            result = run_ntis_module('질문', analysis_top_n=2)
        self.assertEqual(result.module, 'ntis')
        self.assertIn('센서 질문', result.query)
        self.assertIn('질문', result.query)
        self.assertEqual(result.candidates, [])

    def test_legacy_imports_reference_new_implementations(self):
        from app.rfp_rag import rfp_rag
        from app.rfp_rag.pipeline import build_index, search
        from app.policy_rag import law_rag
        from app.policy_rag.pipeline import search as law_search
        self.assertIs(rfp_rag.build_index, build_index)
        self.assertIs(rfp_rag.search, search)
        self.assertIs(law_rag.search, law_search)


if __name__ == '__main__':
    unittest.main()
