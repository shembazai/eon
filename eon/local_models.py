"""Local GGUF discovery and deterministic best-fit recommendation.

Models are replaceable tools for optional Local AI. Core EON stays
deterministic-first and never downloads models.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


# Vocab / projector / tiny sidecar GGUFs are not runnable chat models.
# Hugging Face split shards (…-00001-of-00002.gguf) must be merged first.
_EXCLUDE_NAME_RE = re.compile(
    r"(^ggml-vocab|vocab|mmproj|projector|embedding|embed[-_]|"
    r"rerank|-\d{5}-of-\d{5})",
    re.IGNORECASE,
)
_MIN_MODEL_BYTES = 50 * 1024 * 1024  # 50 MiB — excludes vocab stubs

# Acquisition guidance only. This is not a required filename or an automatic
# download: once GGUFs exist locally, EON ranks and suggests from those tools.
DEFAULT_MODEL_SUGGESTION = "Qwen2.5-7B-Instruct Q5_K_M GGUF"
DEFAULT_MODEL_SUGGESTION_REASON = (
    "instruction-following 7B model; Q5_K_M balances grounded-answer quality "
    "with the latency and memory budget of EON's optional local fallback"
)

_PARAM_RE = re.compile(r"(?<![a-z0-9])(\d{1,3})b(?![a-z0-9])", re.IGNORECASE)
_QUANT_RE = re.compile(
    r"(q[2-8](?:_[0-9a-z_]+)?|iq[1-4]_[0-9a-z_]+|f16|f32|bf16)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LocalModelInfo:
    path: Path
    size_bytes: int
    score: int
    reasons: tuple[str, ...]

    @property
    def name(self) -> str:
        return self.path.name

    def size_label(self) -> str:
        gib = self.size_bytes / (1024**3)
        if gib >= 1.0:
            return f"{gib:.1f} GiB"
        mib = self.size_bytes / (1024**2)
        return f"{mib:.0f} MiB"


def _name_tokens(name: str) -> str:
    return name.lower().replace(".gguf", "")


def score_model_for_eon(path: Path, size_bytes: int) -> tuple[int, tuple[str, ...]]:
    """Deterministic fitness score for grounded personal-finance Local AI.

    Heuristic evidence (filename + size only — no network, no download):
    - Prefer instruction/chat-tuned mid-size (≈7–8B) Q4/Q5 quants for local
      grounded assistants under EON's DEFAULT_CTX / local-first constraints.
    - Penalize vocab/embed stubs, huge parameter counts, and heavy unquantized
      weights that fight optional Local AI graceful degradation.
    """
    name = _name_tokens(path.name)
    score = 0
    reasons: list[str] = []

    if _EXCLUDE_NAME_RE.search(name) or size_bytes < _MIN_MODEL_BYTES:
        return -10_000, ("excluded: not a runnable chat GGUF",)

    if any(tok in name for tok in ("instruct", "chat", "assistant", "-it-", "_it_", ".it.")):
        score += 40
        reasons.append("instruction/chat-tuned name")

    param_match = _PARAM_RE.search(name)
    if param_match:
        params = int(param_match.group(1))
        if params in (7, 8):
            score += 25
            reasons.append(f"{params}B fits local grounded assistant size")
        elif params in (3, 4):
            score += 15
            reasons.append(f"{params}B is light for local inference")
        elif params in (12, 13, 14):
            score += 10
            reasons.append(f"{params}B usable but heavier locally")
        elif params >= 70:
            score -= 50
            reasons.append(f"{params}B exceeds typical local EON budget")
        elif params >= 30:
            score -= 30
            reasons.append(f"{params}B is heavy for optional Local AI")

    quant_match = _QUANT_RE.search(name)
    if quant_match:
        quant = quant_match.group(1).lower()
        if quant in ("q4_k_m", "q5_k_m"):
            score += 20
            reasons.append(f"{quant} balances quality and local footprint")
        elif quant.startswith(("q4", "q5", "iq3", "iq4")):
            score += 10
            reasons.append(f"{quant} is a practical local quant")
        elif quant in ("f16", "f32", "bf16", "q8_0"):
            score -= 15
            reasons.append(f"{quant} is heavy for local optional AI")

    family_hits = [
        ("mistral", "Mistral-class instruct models suit grounded Q&A"),
        ("llama", "Llama-class chat models suit grounded Q&A"),
        ("qwen", "Qwen-class instruct models suit grounded Q&A"),
        ("phi", "Phi-class small instruct models suit local assistants"),
        ("gemma", "Gemma-class instruct models suit grounded Q&A"),
    ]
    for token, reason in family_hits:
        if token in name:
            score += 12
            reasons.append(reason)
            break

    if any(tok in name for tok in ("coder", "code", "starcoder", "codellama")) and "instruct" not in name:
        score -= 20
        reasons.append("code-specialized weights are a weaker PF fit")

    # Soft size band: ~2–8 GiB typical for 7B Q4/Q5 on local hosts.
    gib = size_bytes / (1024**3)
    if 2.0 <= gib <= 8.0:
        score += 10
        reasons.append(f"file size {gib:.1f} GiB matches local 7B-class quants")
    elif gib > 20.0:
        score -= 20
        reasons.append(f"file size {gib:.1f} GiB is large for optional Local AI")

    if not reasons:
        reasons.append("no strong filename signals; ranked by residual score")

    return score, tuple(reasons)


def discover_gguf_models(models_dir: Path | None) -> list[LocalModelInfo]:
    """Scan a directory for replaceable local GGUF tools (non-recursive)."""
    if models_dir is None or not models_dir.is_dir():
        return []

    found: list[LocalModelInfo] = []
    for path in sorted(models_dir.glob("*.gguf")):
        if not path.is_file():
            continue
        try:
            size_bytes = path.stat().st_size
        except OSError:
            continue
        score, reasons = score_model_for_eon(path, size_bytes)
        if score <= -10_000:
            continue
        found.append(
            LocalModelInfo(
                path=path.resolve(),
                size_bytes=size_bytes,
                score=score,
                reasons=reasons,
            )
        )

    found.sort(key=lambda m: (-m.score, m.name.lower()))
    return found


def recommend_best_model(models: Iterable[LocalModelInfo]) -> Optional[LocalModelInfo]:
    """Return the single highest-scoring model, or None if the list is empty."""
    ranked = list(models)
    if not ranked:
        return None
    return max(ranked, key=lambda m: (m.score, -m.size_bytes, m.name.lower()))


def resolve_model_path(
    models_dir: Path,
    *,
    env_override: str | None = None,
) -> Path:
    """Resolve active model path with env override, then best local GGUF.

    Compatibility:
    - ``EON_PFA_MODEL_PATH`` always wins when set (even if missing — caller
      reports absence without inventing a download).
    - Otherwise pick the deterministic best-fit among discovered GGUFs.
    - If none exist, return a non-hardcoded sentinel under ``models_dir`` so
      health/UI can say "no GGUF discovered" instead of a brittle filename.
    """
    override = env_override if env_override is not None else os.getenv("EON_PFA_MODEL_PATH")
    if override:
        return Path(override)

    recommended = recommend_best_model(discover_gguf_models(models_dir))
    if recommended is not None:
        return recommended.path

    return models_dir / ".no_gguf_discovered"


def format_model_choice_menu(
    models: list[LocalModelInfo],
    suggested: LocalModelInfo | None,
) -> str:
    """Human-readable list for interactive Local AI model selection."""
    lines = [
        "Local AI models are replaceable tools. Available GGUF files:",
        "",
    ]
    if not models:
        lines.append("  (none found)")
        lines.append("")
        lines.append(f"Suggested model to add: {DEFAULT_MODEL_SUGGESTION}")
        lines.append(f"Why: {DEFAULT_MODEL_SUGGESTION_REASON}")
        return "\n".join(lines)

    for index, model in enumerate(models, start=1):
        marker = "  ← suggested best fit" if suggested and model.path == suggested.path else ""
        lines.append(f"  {index}. {model.name} ({model.size_label()}){marker}")

    if suggested is not None:
        lines.append("")
        lines.append(f"Suggested: {suggested.name}")
        lines.append("Why: " + "; ".join(suggested.reasons))
    return "\n".join(lines)
