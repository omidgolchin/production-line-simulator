"""Parse model answers and score them against the ground truth.

Answer formats (see prompts/):
    BOTTLENECK: <station number, or none>
    THROUGHPUT: <number>            (direct and code modes only)

The last occurrence of each line in the text wins (models sometimes
restate their answer). For code mode, the text parsed is the
program's stdout.
"""

from __future__ import annotations

import re

_BN = re.compile(r"BOTTLENECK\s*:\s*(none|\d+)", re.IGNORECASE)
_TH = re.compile(r"THROUGHPUT\s*:\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_CODE_BLOCK = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def parse_answer(text: str) -> dict:
    """Return {bottleneck: int | 'none' | None, throughput: float | None}."""
    if not text:
        return {"bottleneck": None, "throughput": None}
    bn = None
    for m in _BN.finditer(text):
        v = m.group(1).lower()
        bn = "none" if v == "none" else int(v)
    th = None
    for m in _TH.finditer(text):
        th = float(m.group(1))
    return {"bottleneck": bn, "throughput": th}


def extract_code(text: str) -> str | None:
    """Pull the simulation program out of a code-mode reply."""
    if not text:
        return None
    blocks = _CODE_BLOCK.findall(text)
    if blocks:
        return blocks[-1]
    if "import " in text and "print" in text:
        return text
    return None


def score_row(parsed: dict, truth: dict, mode: str) -> dict:
    """Score one parsed answer against one configuration's truth."""
    bn_ok = (parsed["bottleneck"] is not None
             and parsed["bottleneck"] == truth["bottleneck"])
    out = {"bottleneck_correct": bool(bn_ok),
           "bottleneck_parsed": parsed["bottleneck"] is not None}
    if mode in ("direct", "code"):
        out["throughput_parsed"] = parsed["throughput"] is not None
        if parsed["throughput"] is not None:
            err = parsed["throughput"] - truth["throughput"]
            out["throughput_error"] = err
            out["throughput_abs_error"] = abs(err)
            out["throughput_rel_error"] = abs(err) / truth["throughput"]
    return out
