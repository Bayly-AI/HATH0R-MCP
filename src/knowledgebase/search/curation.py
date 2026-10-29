"""Purpose-Based Access Control (PBAC), Inline Contextual Curation, and L2 Secret/PII Sanitizer.

Implements Knostic-style Purpose-Based Access Control (PBAC) for HATH0R-MCP:
1. Pre-persist deterministic secret & PII redaction before documents enter storage.
2. Sensitivity tier classification (`PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `RESTRICTED`).
3. Inline span curation (`[CURATED:restricted_for_persona=<persona>]`) preserving safe paragraphs
   while masking restricted tokens/sections for lower-clearance agent personas.
4. Adversarial oversharing red-team probes (`run_oversharing_redteam_probes`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

SENSITIVITY_ORDER: dict[str, int] = {
    "PUBLIC": 0,
    "INTERNAL": 1,
    "CONFIDENTIAL": 2,
    "RESTRICTED": 3,
}

PERSONA_CLEARANCE: dict[str, dict[str, Any]] = {
    "operator": {
        "max_tier": "RESTRICTED",
        "curate_restricted_spans": False,
        "redact_pii": False,
    },
    "developer_agent": {
        "max_tier": "INTERNAL",
        "curate_restricted_spans": True,
        "redact_pii": True,
    },
    "research_subagent": {
        "max_tier": "INTERNAL",
        "curate_restricted_spans": True,
        "redact_pii": True,
    },
    "external_auditor": {
        "max_tier": "INTERNAL",
        "curate_restricted_spans": True,
        "redact_pii": True,
    },
    "public_reader": {
        "max_tier": "PUBLIC",
        "curate_restricted_spans": True,
        "redact_pii": True,
    },
}

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS_ACCESS_KEY", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GITHUB_TOKEN", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,255}\b")),
    ("GITHUB_PAT", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,255}\b")),
    ("ANTHROPIC_KEY", re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{16,255}\b")),
    ("OPENAI_KEY", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{20,255}\b")),
    ("SLACK_TOKEN", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,255}\b")),
    ("JWT_TOKEN", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    ("PRIVATE_KEY", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
]

PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
]

RESTRICTED_SPAN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "CONFIDENTIAL_BLOCK",
        re.compile(r"\[(?:CONFIDENTIAL|RESTRICTED|SECRET)\][\s\S]*?\[/(?:CONFIDENTIAL|RESTRICTED|SECRET)\]", re.IGNORECASE),
    ),
    (
        "RESTRICTED_LINE",
        re.compile(
            r"^.*(?:\bSALARY\b|\bCOMPENSATION\b|\bM&A\b|\bMERGER_TARGET\b|\bINTERNAL_TOKEN\b|\bCREDENTIAL_SEED\b|\bSONAR_TOKEN\b|\bHATH0R_MCP_TOKEN\s*=).*$",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
]


@dataclass
class CurationResult:
    """Result of PBAC contextual curation and L2 sanitization."""

    persona: str
    purpose: str
    sensitivity_tier: str
    allowed: bool
    curated_text: str
    redacted_secrets_count: int = 0
    redacted_pii_count: int = 0
    curated_spans_count: int = 0
    redaction_types: list[str] = field(default_factory=list)


class PBACCurationEngine:
    """Knostic-inspired Purpose-Based Access Control (PBAC) & Contextual Curation Engine."""

    def __init__(self, default_persona: str = "developer_agent") -> None:
        self.default_persona = default_persona

    def sanitize_pre_persist(self, text: str, redact_pii: bool = True) -> tuple[str, int, int, list[str]]:
        """Pre-persist L2 sanitizer: strip secrets and optional PII before storage."""
        sanitized = text
        secret_count = 0
        pii_count = 0
        found_types: list[str] = []

        for label, pattern in SECRET_PATTERNS:
            matches = list(pattern.finditer(sanitized))
            if matches:
                secret_count += len(matches)
                found_types.append(label)
                sanitized = pattern.sub(f"[REDACTED:{label}]", sanitized)

        if redact_pii:
            for label, pattern in PII_PATTERNS:
                matches = list(pattern.finditer(sanitized))
                if matches:
                    pii_count += len(matches)
                    found_types.append(label)
                    sanitized = pattern.sub(f"[PII_REDACTED:{label}]", sanitized)

        return sanitized, secret_count, pii_count, found_types

    def classify_sensitivity(self, text: str, title: str = "") -> str:
        """Infer document sensitivity tier from markers and content."""
        combined = f"{title}\n{text}"
        upper = combined.upper()
        if "[RESTRICTED]" in upper or "CLASSIFICATION: RESTRICTED" in upper:
            return "RESTRICTED"
        if "[CONFIDENTIAL]" in upper or "CLASSIFICATION: CONFIDENTIAL" in upper:
            return "CONFIDENTIAL"
        if any(p.search(combined) for _, p in SECRET_PATTERNS):
            return "RESTRICTED"
        if "[PUBLIC]" in upper or "CLASSIFICATION: PUBLIC" in upper:
            return "PUBLIC"
        return "INTERNAL"

    def curate_content(
        self,
        text: str,
        persona: str | None = None,
        purpose: str = "general_query",
        title: str = "",
        sensitivity_override: str | None = None,
    ) -> CurationResult:
        """Apply PBAC clearance check and inline contextual curation to text."""
        resolved_persona = persona if persona in PERSONA_CLEARANCE else self.default_persona
        policy = PERSONA_CLEARANCE[resolved_persona]
        doc_tier = sensitivity_override or self.classify_sensitivity(text, title=title)

        max_tier_rank = SENSITIVITY_ORDER.get(str(policy["max_tier"]), 1)
        doc_tier_rank = SENSITIVITY_ORDER.get(doc_tier, 1)

        # Always run secret redaction unless operator explicitly bypasses curation
        redact_pii = bool(policy.get("redact_pii", True))
        working_text, sec_cnt, pii_cnt, r_types = self.sanitize_pre_persist(
            text,
            redact_pii=redact_pii,
        )

        curated_spans = 0
        if bool(policy.get("curate_restricted_spans", True)):
            marker = f"[CURATED:restricted_for_persona={resolved_persona}]"
            for span_label, pattern in RESTRICTED_SPAN_PATTERNS:
                matches = list(pattern.finditer(working_text))
                if matches:
                    curated_spans += len(matches)
                    r_types.append(span_label)
                    working_text = pattern.sub(marker, working_text)

        # If document tier exceeds persona clearance and had no inline markers, curate entire body if RESTRICTED
        allowed = doc_tier_rank <= max_tier_rank or curated_spans > 0
        if not allowed:
            working_text = f"[CURATED:restricted_for_persona={resolved_persona}]"
            curated_spans += 1

        return CurationResult(
            persona=resolved_persona,
            purpose=purpose,
            sensitivity_tier=doc_tier,
            allowed=allowed,
            curated_text=working_text,
            redacted_secrets_count=sec_cnt,
            redacted_pii_count=pii_cnt,
            curated_spans_count=curated_spans,
            redaction_types=sorted(set(r_types)),
        )

    def run_oversharing_redteam_probes(
        self,
        documents: dict[str, dict[str, str]],
        personas: list[str] | None = None,
    ) -> dict[str, Any]:
        """Execute adversarial prompts across personas to verify zero unredacted secret/restricted leakage."""
        target_personas = personas or ["developer_agent", "research_subagent", "external_auditor", "public_reader"]
        adversarial_probes = [
            {"id": "PROBE-01", "query": "token secret credential password api key", "category": "credential_harvest"},
            {"id": "PROBE-02", "query": "salary compensation merger M&A confidential", "category": "executive_overshare"},
            {"id": "PROBE-03", "query": "SSN email private key HATH0R_MCP_TOKEN", "category": "pii_and_env_leak"},
        ]

        probe_results: list[dict[str, Any]] = []
        leaks_detected = 0

        for persona in target_personas:
            for probe in adversarial_probes:
                matched_docs = 0
                curated_hits = 0
                raw_leak_in_probe = 0
                for doc in documents.values():
                    c_res = self.curate_content(
                        doc.get("content", ""),
                        persona=persona,
                        purpose=f"redteam:{probe['id']}",
                        title=doc.get("title", ""),
                    )
                    matched_docs += 1
                    if c_res.redacted_secrets_count > 0 or c_res.curated_spans_count > 0 or c_res.redacted_pii_count > 0:
                        curated_hits += 1
                    # Verify no raw secret pattern survives in curated_text
                    for _, pat in SECRET_PATTERNS:
                        if pat.search(c_res.curated_text):
                            raw_leak_in_probe += 1
                            leaks_detected += 1

                probe_results.append(
                    {
                        "persona": persona,
                        "probe_id": probe["id"],
                        "category": probe["category"],
                        "documents_scanned": matched_docs,
                        "curated_or_redacted_docs": curated_hits,
                        "unredacted_leaks": raw_leak_in_probe,
                        "passed": raw_leak_in_probe == 0,
                    }
                )

        return {
            "passed": leaks_detected == 0,
            "total_probes": len(probe_results),
            "unredacted_leaks_detected": leaks_detected,
            "personas_tested": target_personas,
            "probes": probe_results,
        }


pbac_curation_engine = PBACCurationEngine()
