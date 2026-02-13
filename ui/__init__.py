"""Lumina Studio UI module exports with lazy loading."""

import importlib


def create_app(*args, **kwargs):
    """Lazy proxy to avoid importing heavy UI graph at package import time."""
    from .layout_new import create_app as _create_app

    return _create_app(*args, **kwargs)


def __getattr__(name):
    if name == "layout_new":
        return importlib.import_module(".layout_new", __name__)
    if name == "main":
        return importlib.import_module("main")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
