"""Compatibility access to generation.analysis."""
from importlib import import_module

def __getattr__(name):
    if name.startswith('__'):
        raise AttributeError(name)
    return getattr(import_module('.generation.analysis', __package__), name)
