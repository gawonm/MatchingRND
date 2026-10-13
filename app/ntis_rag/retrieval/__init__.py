"""NTIS retrieval; defer index and model loading until an operation is used."""
from importlib import import_module

def __getattr__(name):
    if name.startswith('__'):
        raise AttributeError(name)
    return getattr(import_module('.pipeline', __name__), name)
