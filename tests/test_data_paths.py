"""Path resolution and relocated RFP workbook linking regressions."""
import os
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app.common.paths import PROJECT_ROOT, RFP_PDF_DIR, POLICY_RAW_DIR, resolve_project_path
from app.orchestrator import RagOrchestrator
from app.rfp_rag.parsing.notices import _load_notices


class DataPathTests(unittest.TestCase):
    def test_relative_paths_are_independent_of_working_directory(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temp:
            try:
                os.chdir(temp)
                self.assertEqual(resolve_project_path('data/raw/ntis'), PROJECT_ROOT / 'data/raw/ntis')
            finally:
                os.chdir(original)

    def test_orchestrator_uses_module_specific_inputs(self):
        orchestrator = RagOrchestrator()
        self.assertEqual(orchestrator.rfp_data_dir, RFP_PDF_DIR)
        self.assertEqual(Path(orchestrator.rfp_notice_path).parent, RFP_PDF_DIR.parent)

    def test_notice_workbook_in_pdf_parent_keeps_filename_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf_dir = root / 'pdf'
            pdf_dir.mkdir()
            pdf = pdf_dir / 'original.pdf'
            pdf.touch()
            with pd.ExcelWriter(root / 'RFP_공고목록.xlsx') as writer:
                pd.DataFrame([{'공고 UID': 'notice-1', '공고명': '연구개발 공고',
                               '원 공고기관 URL': 'https://example.com/notice'}]).to_excel(
                                   writer, sheet_name='공고목록', index=False)
                pd.DataFrame([{'공고 UID': 'notice-1', '파일명': 'original.pdf'}]).to_excel(
                    writer, sheet_name='파일매칭', index=False)
            notices, links, issues = _load_notices(pdf_dir, [pdf])
            self.assertEqual(links, {'original.pdf': ['notice-1']})
            self.assertEqual(notices['notice-1']['title'], '연구개발 공고')
            self.assertEqual(issues, [])


if __name__ == '__main__':
    unittest.main()
