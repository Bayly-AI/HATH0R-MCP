"""
Level 1 SuperSqueeze (SuperCompressBot) context compression engine and MCP output middleware.

Governed by CR-FEATURE-WORKFLOW-STANDARD-001:
- Service: SuperSqueeze Context Compression Service
- Owning Bot: SuperSqueezeBot (SuperCompressBot)
- AgentGraph Level: L1_MCP <-> L2_CLI_MEMORY
- Declarative Workflow: cfg/factories/supersqueeze-context-workflow.yaml
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re
from typing import Any

from knowledgebase.core.feature_flags import is_feature_enabled
from knowledgebase.core.observability import timed_operation


def estimate_tokens(text: str) -> int:
    """Estimate token count using hybrid word + subword heuristic (~4 chars/token)."""
    if not text:
        return 0
    words = len(re.findall(r"\S+", text))
    char_est = math.ceil(len(text) / 4.0)
    return max(words, char_est)


@dataclass(frozen=True)
class SuperSqueezeResult:
    """Structured result from SuperSqueeze compression."""

    compressed_text: str
    original_tokens: int
    compressed_tokens: int
    savings_ratio: float
    target_ratio: float
    squeezed: bool
    owning_bot: str = "SuperSqueezeBot"
    workflow_id: str = "cfg/factories/supersqueeze-context-workflow.yaml"
    agentgraph_level: str = "L1_MCP"

    def to_dict(self) -> dict[str, Any]:
        return {
            "compressed_text": self.compressed_text,
            "original_tokens": self.original_tokens,
            "compressed_tokens": self.compressed_tokens,
            "savings_ratio": round(self.savings_ratio, 4),
            "target_ratio": round(self.target_ratio, 4),
            "squeezed": self.squeezed,
            "owning_bot": self.owning_bot,
            "workflow_id": self.workflow_id,
            "agentgraph_level": self.agentgraph_level,
        }


class SuperSqueezeEngine:
    """Query-aware semantic context compression engine for Level 1 HATH0R-MCP."""

    OWNING_BOT = "SuperSqueezeBot"
    WORKFLOW_ID = "cfg/factories/supersqueeze-context-workflow.yaml"

    def compress(
        self,
        text: str,
        query: str = "",
        target_ratio: float = 0.35,
    ) -> SuperSqueezeResult:
        """Compress input text while preserving structural headings, key facts, and query-relevant spans."""
        clamped_ratio = max(0.10, min(0.90, float(target_ratio)))
        original_tokens = estimate_tokens(text)
        if not text or not text.strip():
            return SuperSqueezeResult(
                compressed_text="",
                original_tokens=0,
                compressed_tokens=0,
                savings_ratio=0.0,
                target_ratio=clamped_ratio,
                squeezed=False,
            )

        # Normalize excessive whitespace first
        normalized = re.sub(r"[ \t]+", " ", text).strip()
        segments = [seg.strip() for seg in re.split(r"(?<=[.!?])\s+|\n+", normalized) if seg.strip()]
        if len(segments) <= 1:
            # Single long segment: slice by words to target_ratio
            words = normalized.split()
            keep_count = max(1, int(len(words) * clamped_ratio))
            compressed = " ".join(words[:keep_count])
            comp_tokens = estimate_tokens(compressed)
            savings = max(0.0, 1.0 - (comp_tokens / max(1, original_tokens)))
            return SuperSqueezeResult(
                compressed_text=compressed,
                original_tokens=original_tokens,
                compressed_tokens=comp_tokens,
                savings_ratio=savings,
                target_ratio=clamped_ratio,
                squeezed=comp_tokens < original_tokens,
            )

        query_terms = {t.lower() for t in re.findall(r"\w+", query) if len(t) > 2}
        num_segs = max(1, len(segments))
        doc_freq: Counter[str] = Counter()
        for seg in segments:
            for w in {w.lower() for w in re.findall(r"\w+", seg) if len(w) > 2}:
                doc_freq[w] += 1

        scored_segments: list[tuple[float, int, str]] = []
        for idx, seg in enumerate(segments):
            seg_words = [w.lower() for w in re.findall(r"\w+", seg) if len(w) > 2]
            if not seg_words:
                score = 0.1
            else:
                # Inverse segment frequency rewards distinct informative terms over repetitive boilerplate
                idf_score = sum(
                    math.log(1.0 + (num_segs / max(1, doc_freq[w]))) for w in set(seg_words)
                ) / (len(seg_words) ** 0.5)
                query_boost = sum(25.0 for w in set(seg_words) if w in query_terms)
                heading_boost = 50.0 if seg.startswith("#") else 0.0
                position_boost = 15.0 if idx == 0 else (8.0 if idx == len(segments) - 1 else 0.0)
                score = idf_score + query_boost + heading_boost + position_boost
            scored_segments.append((score, idx, seg))

        scored_segments.sort(key=lambda item: (-item[0], item[1]))
        target_char_budget = max(32, int(len(normalized) * clamped_ratio))

        selected_indices: list[int] = []
        accumulated_chars = 0
        for _score, idx, seg in scored_segments:
            if accumulated_chars + len(seg) <= target_char_budget or not selected_indices:
                selected_indices.append(idx)
                accumulated_chars += len(seg) + 1
            if accumulated_chars >= target_char_budget:
                break

        selected_indices.sort()
        compressed_text = "\n".join(segments[i] for i in selected_indices)
        if len(compressed_text) > target_char_budget and len(selected_indices) == 1:
            words = compressed_text.split()
            keep_words = max(1, int(len(words) * clamped_ratio))
            compressed_text = " ".join(words[:keep_words])

        compressed_tokens = estimate_tokens(compressed_text)
        savings_ratio = max(0.0, 1.0 - (compressed_tokens / max(1, original_tokens)))

        with timed_operation(
            "hath0r_supersqueeze",
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            savings_ratio=round(savings_ratio, 4),
            owning_bot=self.OWNING_BOT,
            workflow_id=self.WORKFLOW_ID,
        ):
            return SuperSqueezeResult(
                compressed_text=compressed_text,
                original_tokens=original_tokens,
                compressed_tokens=compressed_tokens,
                savings_ratio=savings_ratio,
                target_ratio=clamped_ratio,
                squeezed=compressed_tokens < original_tokens,
            )


supersqueeze_engine = SuperSqueezeEngine()


def apply_supersqueeze_middleware(
    content: str,
    *,
    query: str = "",
    target_ratio: float = 0.35,
    token_threshold: int = 1024,
) -> tuple[str, dict[str, Any]]:
    """Apply SuperSqueeze middleware to large tool payloads when OpenFeature flag mcp.supersqueeze.enabled is True."""
    enabled = is_feature_enabled("mcp.supersqueeze.enabled", default=True)
    orig_tokens = estimate_tokens(content)
    if not enabled or orig_tokens <= token_threshold:
        return content, {
            "enabled": enabled,
            "squeezed": False,
            "original_tokens": orig_tokens,
            "compressed_tokens": orig_tokens,
            "savings_ratio": 0.0,
            "owning_bot": SuperSqueezeEngine.OWNING_BOT,
        }

    res = supersqueeze_engine.compress(content, query=query, target_ratio=target_ratio)
    return res.compressed_text, {
        "enabled": True,
        "squeezed": res.squeezed,
        "original_tokens": res.original_tokens,
        "compressed_tokens": res.compressed_tokens,
        "savings_ratio": round(res.savings_ratio, 4),
        "owning_bot": res.owning_bot,
        "workflow_id": res.workflow_id,
    }
