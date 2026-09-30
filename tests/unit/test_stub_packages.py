"""Smoke tests for placeholder package modules.

These modules currently contain documentation and an ``__all__`` definition
only. Importing them in tests ensures they remain syntactically valid and are
counted towards code coverage.
"""

from __future__ import annotations

from knowledgebase import aws, search, sync


def test_stub_packages_define_all_lists() -> None:
    """The stub packages should expose an ``__all__`` list attribute."""

    assert isinstance(aws.__all__, list)
    assert isinstance(search.__all__, list)
    assert isinstance(sync.__all__, list)
