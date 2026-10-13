"""Shared ModuleResult adapter for rfp_rag."""
from app.common.adapters import adapt_pdf_result

def to_module_result(result, index):
    return adapt_pdf_result(result, index, "rfp")
