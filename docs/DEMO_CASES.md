# EON PFA Demo Cases

These cases reflect validated deterministic flows from the personal-only branch.
Run with `eon query "<prompt>"` or pytest (`tests/test_engine.py`).

## Case 1 — Deterministic monthly expense query

**Prompt:** `what are my monthly expenses?`

**Expected:** Deterministic answer from profile (no model).

**Example:** `Estimated monthly expenses: $3090.00.` (regression seed profile)

## Case 2 — Income ratio query

**Prompt:** `what percentage of my income goes to rent?`

**Expected:** Category-to-income ratio from profile values.

## Case 3 — Deterministic advice, mutation, and undo

**Prompt A:** `give me actionable advice`  
**Prompt B:** `replace rent with 1810`  
**Prompt C:** `undo last change`

**Expected:** Advice from decision layer; mutation journaled; undo restores backup without new journal row.

## Notes

- Core deterministic behavior works without AI or chart extras.
- Current branch is personal-only and deterministic-first by design.
