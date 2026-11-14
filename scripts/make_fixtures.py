"""Generate the Python/JavaScript agreement fixtures.

Writes tests/fixtures/agreement.json: fixed-seed cases run through the
Python engine. tests/test_js_agreement.py runs the same cases through
docs/engine.js under node and compares every recorded series exactly.

Run:  PYTHONPATH=src python scripts/make_fixtures.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from linesim.simulate import LCG, LineConfig, simulate  # noqa: E402

DIE5 = [{"kind": "die"}] * 5
BN = [{"kind": "die"}, {"kind": "die"}, {"kind": "uniform", "lo": 1, "hi": 4},
      {"kind": "die"}, {"kind": "die"}]

CASES = [
    {"name": "fixed_534", "seed": 1, "periods": 50,
     "config": {"stations": [{"kind": "fixed", "value": 5},
                             {"kind": "fixed", "value": 3},
                             {"kind": "fixed", "value": 4}],
                "buffer_limits": None, "release": {"mode": "infinite"}}},
    {"name": "die_line", "seed": 12345, "periods": 200,
     "config": {"stations": DIE5, "buffer_limits": None,
                "release": {"mode": "infinite"}}},
    {"name": "die_line_cap4", "seed": 999, "periods": 200,
     "config": {"stations": DIE5, "buffer_limits": [4, 4, 4, 4],
                "release": {"mode": "infinite"}}},
    {"name": "bn_dbr", "seed": 777, "periods": 200,
     "config": {"stations": BN, "buffer_limits": None,
                "release": {"mode": "dbr", "bottleneck": 2,
                            "time_buffer": 10}}},
    {"name": "uniform_push", "seed": 31337, "periods": 200,
     "config": {"stations": [{"kind": "uniform", "lo": 2, "hi": 5}] * 4,
                "buffer_limits": None,
                "release": {"mode": "push", "rate": 5}}},
]


def main() -> None:
    out = []
    for case in CASES:
        cfg = LineConfig.from_dict(case["config"])
        res = simulate(cfg, case["periods"], LCG(case["seed"]), record=True)
        out.append({**case, "expected": {
            "series_output": res["series_output"],
            "series_wip": res["series_wip"],
            "series_buffers": res["series_buffers"],
            "series_station_output": res["series_station_output"],
            "series_caps": res["series_caps"],
        }})
    path = ROOT / "tests" / "fixtures" / "agreement.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    print(f"wrote {path} ({len(out)} cases)")


if __name__ == "__main__":
    main()
