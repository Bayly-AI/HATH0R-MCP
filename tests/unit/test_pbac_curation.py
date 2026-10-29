"""Unit tests for PBAC Contextual Curation, Pre-Persist Sanitizer, and Oversharing Red-Team Probes (#84)."""

from __future__ import annotations

from knowledgebase.search.curation import PBACCurationEngine


def test_pre_persist_sanitizer_strips_secrets_and_pii() -> None:
    engine = PBACCurationEngine()
    raw = (
        "Architecture note for jane.doe@example.com (SSN 123-45-6789).\n"
        "Temp token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789\n"
        "AWS key: AKIAIOSFODNN7EXAMPLE"
    )
    sanitized, sec_cnt, pii_cnt, r_types = engine.sanitize_pre_persist(raw, redact_pii=True)
    assert sec_cnt == 2
    assert pii_cnt == 2
    assert "[REDACTED:GITHUB_TOKEN]" in sanitized
    assert "[REDACTED:AWS_ACCESS_KEY]" in sanitized
    assert "[PII_REDACTED:EMAIL]" in sanitized
    assert "[PII_REDACTED:SSN]" in sanitized
    assert "ghp_" not in sanitized
    assert "AKIAIOSFODNN7EXAMPLE" not in sanitized


def test_inline_contextual_curation_preserves_safe_spans_and_masks_restricted() -> None:
    engine = PBACCurationEngine()
    doc_text = (
        "Public architecture overview: Hath0r uses a Tri-Graph substrate.\n"
        "[CONFIDENTIAL] Merger target valuation is $45M. [/CONFIDENTIAL]\n"
        "HATH0R_MCP_TOKEN = super_secret_value_12345\n"
        "Standard developer setup uses `make test`."
    )

    # Developer agent gets curated spans
    dev_res = engine.curate_content(doc_text, persona="developer_agent", purpose="code_review")
    assert dev_res.allowed is True
    assert dev_res.curated_spans_count >= 2
    assert "Public architecture overview" in dev_res.curated_text
    assert "Standard developer setup" in dev_res.curated_text
    assert "Merger target valuation" not in dev_res.curated_text
    assert "super_secret_value_12345" not in dev_res.curated_text
    assert "[CURATED:restricted_for_persona=developer_agent]" in dev_res.curated_text

    # Operator retains restricted inline spans
    op_res = engine.curate_content(doc_text, persona="operator", purpose="incident_response")
    assert op_res.allowed is True
    assert op_res.curated_spans_count == 0
    assert "Merger target valuation" in op_res.curated_text


def test_oversharing_redteam_probes_zero_unredacted_leaks() -> None:
    engine = PBACCurationEngine()
    docs = {
        "doc-1": {
            "id": "doc-1",
            "title": "Runbook",
            "content": "Safe content with leaked token ghp_1234567890abcdefghijklmnopqrstuvwx and SALARY: $200k",
        }
    }
    report = engine.run_oversharing_redteam_probes(docs)
    assert report["passed"] is True
    assert report["unredacted_leaks_detected"] == 0
    assert report["total_probes"] == 12
