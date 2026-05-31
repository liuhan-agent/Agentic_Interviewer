"""Compatibility wrapper for the renamed ``turn_finalize`` node.

The real LangGraph node is now ``turn_finalize``. This module remains
only for old Python imports during the development rename window.
"""
from __future__ import annotations

from .turn_finalize import compress_context_node, turn_finalize_node

__all__ = ["turn_finalize_node", "compress_context_node"]
