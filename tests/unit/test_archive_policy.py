"""Unit tests for Phase 4 archive exclusion policy and search routing helpers."""

from __future__ import annotations

from knowledgebase.api.main import _resolve_target_indices_for_search
from knowledgebase.search.archive_policy import (
    DOMAIN_INDICES,
    apply_default_archive_filters,
    default_search_indices_from_config,
    is_excluded_default_index,
    metadata_indicates_archive,
    should_exclude_archive_document,
)


def test_metadata_indicates_archive_by_source_type() -> None:
    assert metadata_indicates_archive({"source_type": "archive"})
    assert metadata_indicates_archive({"source_type": "mirror"})
    assert not metadata_indicates_archive({"source_type": "file"})


def test_metadata_indicates_archive_by_path_and_id() -> None:
    assert metadata_indicates_archive(
        {"path": "/Volumes/BaylyAI-External/knowledge-archive/knowledgebase/foo.md"}
    )
    assert metadata_indicates_archive({}, doc_id="archive__knowledge__chunk-1")
    assert not metadata_indicates_archive({"path": "./knowledgebase/canonical/rules/cr.md"})


def test_should_exclude_respects_include_archive_flag() -> None:
    meta = {"source_type": "archive"}
    assert should_exclude_archive_document(metadata=meta, include_archive=False)
    assert not should_exclude_archive_document(metadata=meta, include_archive=True)


def test_default_search_indices_from_config_prefer_explicit() -> None:
    cfg = {
        "default_search_indices": ["rules", "runbooks", "reference"],
        "indices": [{"name": "plans"}],
    }
    # reference is excluded even if listed explicitly
    assert default_search_indices_from_config(cfg) == ["rules", "runbooks"]


def test_default_search_indices_fallback_domain_set() -> None:
    assert set(default_search_indices_from_config({})) == set(DOMAIN_INDICES)


def test_is_excluded_default_index() -> None:
    assert is_excluded_default_index("reference")
    assert is_excluded_default_index("archive-knowledge")
    assert not is_excluded_default_index("rules")


def test_apply_default_archive_filters() -> None:
    assert apply_default_archive_filters(None, include_archive=True) is None
    filtered = apply_default_archive_filters({"tags": ["x"]}, include_archive=False)
    assert filtered is not None
    assert filtered["_exclude_archive"] is True
    assert filtered["tags"] == ["x"]


def test_resolve_target_indices_unscoped_uses_allowlist() -> None:
    config = {
        "default_search_indices": ["rules", "runbooks", "knowledge"],
        "aliases": {"knowledgebase": "knowledge"},
        "indices": [
            {"name": "rules", "taxonomy": {"domain": "rules"}},
            {"name": "runbooks", "taxonomy": {"domain": "runbooks"}},
            {"name": "knowledge", "taxonomy": {"domain": "knowledge"}},
            {"name": "reference", "taxonomy": {"domain": "reference"}},
        ],
    }
    targets = _resolve_target_indices_for_search(
        config=config,
        aliases={"knowledgebase": "knowledge"},
        index_name=None,
        group=None,
        domain=None,
        subgroup=None,
        include_archive=False,
    )
    assert targets == ["rules", "runbooks", "knowledge"]


def test_resolve_target_indices_blocks_archive_index_without_opt_in() -> None:
    config = {"default_search_indices": ["rules"], "aliases": {}}
    blocked = _resolve_target_indices_for_search(
        config=config,
        aliases={},
        index_name="reference",
        group=None,
        domain=None,
        subgroup=None,
        include_archive=False,
    )
    assert blocked == []

    allowed = _resolve_target_indices_for_search(
        config=config,
        aliases={},
        index_name="reference",
        group=None,
        domain=None,
        subgroup=None,
        include_archive=True,
    )
    assert allowed == ["reference"]


