#!/usr/bin/env python3
"""Pure routing decisions for impact-routed verification (issue #22).

decide_2a / decide_3a are pure functions over canonical on-disk state. Same
inputs produce byte-identical decisions across runs and hosts. The module
holds no I/O — callers (writer, reader CLI, status renderer) read state and
round files into dicts before invoking these functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class RouteDecision:
    """The result of decide_2a / decide_3a.

    selected_slices is sorted and unique. fallback_reasons is sorted, unique,
    and empty iff scope == "narrow".
    """

    scope: Literal["broad", "narrow"]
    selected_slices: tuple[int, ...]
    fallback_reasons: tuple[str, ...]


def identify_mandatory_slices(slice_plan: list[dict]) -> dict:
    """Return {'global_coherence_slice': int|None, 'cross_artifact_slice': int|None}.

    `global_coherence_slice` is the agent_id of the highest-numbered slice
    with is_fixed=False, or None when no non-fixed slice exists (caller
    treats this as `mandatory_slice_undetectable`).

    `cross_artifact_slice` is the agent_id of the single is_fixed=True slice,
    or None when none is present.

    Raises ValueError when more than one is_fixed=True slice exists (the
    schema already enforces this; the writer treats >1 as defence-in-depth).
    """
    fixed = [s for s in slice_plan if s.get("is_fixed")]
    if len(fixed) > 1:
        raise ValueError(
            f"multiple is_fixed=True slices in slice_plan: {sorted(s['agent_id'] for s in fixed)}"
        )
    cross = fixed[0]["agent_id"] if fixed else None
    non_fixed = [s["agent_id"] for s in slice_plan if not s.get("is_fixed")]
    global_coh = max(non_fixed) if non_fixed else None
    return {"global_coherence_slice": global_coh, "cross_artifact_slice": cross}
