"""The Python and JavaScript engines must agree exactly on fixed
seeds (die, uniform and fixed distributions; see DECISIONS.md for why
normal capacities are excluded from exact agreement), and the
JavaScript analysis layer must agree with the Python finder on the
fixture cases."""

import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "agreement.json"
FINDER_FIXTURES = ROOT / "tests" / "fixtures" / "finder_cases.json"
sys.path.insert(0, str(ROOT / "src"))

from linesim import finder  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")


def _run(script):
    proc = subprocess.run(["node", str(ROOT / "scripts" / script)],
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_js_engine_agrees_with_python():
    cases = json.loads(FIXTURES.read_text())
    js_results = {r["name"]: r for r in _run("run_js_engine.js")}
    for case in cases:
        js = js_results[case["name"]]
        exp = case["expected"]
        for key in ("series_output", "series_wip", "series_buffers",
                    "series_station_output", "series_caps"):
            assert js[key] == exp[key], f"{case['name']}: {key} differs"


def _approx(a, b, path=""):
    if isinstance(a, dict):
        assert isinstance(b, dict), path
        ka = {k for k in a if k not in ("rep_throughputs", "runs")}
        kb = {k for k in b if k not in ("rep_throughputs", "runs")}
        assert ka == kb, f"{path}: keys differ: {ka ^ kb}"
        for k in ka:
            _approx(a[k], b[k], f"{path}/{k}")
    elif isinstance(a, list):
        assert isinstance(b, list) and len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            _approx(x, y, f"{path}[{i}]")
    elif isinstance(a, float) or isinstance(b, float):
        if a is None or b is None:
            assert a == b, f"{path}: {a} != {b}"
        else:
            assert math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6), \
                f"{path}: {a} != {b}"
    else:
        assert a == b, f"{path}: {a!r} != {b!r}"


@pytest.fixture(scope="module")
def js_finder():
    return _run("run_js_finder.js")


def test_js_finder_analyze_agrees(js_finder):
    cases = json.loads(FINDER_FIXTURES.read_text())
    js = {r["name"]: r for r in js_finder["analyze"]}
    for case in cases["analyze"]:
        cfg = finder.tool_config(case["tool"])
        agg = finder.analyze_line(cfg, **case["opts"])
        agg.pop("rep_throughputs", None)
        expected = {
            "agg": agg,
            "kingman": finder.kingman(cfg, agg["throughput"]),
            "options": finder.improvement_options(cfg, **case["opts"]),
            "release": finder.release_comparison(cfg, **case["opts"]),
        }
        got = {k: v for k, v in js[case["name"]].items() if k != "name"}
        _approx(expected, got, case["name"])


def test_js_finder_logs_agree(js_finder):
    cases = json.loads(FINDER_FIXTURES.read_text())
    js = {r["name"]: r for r in js_finder["logs"]}
    for case in cases["logs"]:
        _approx(finder.analyze_log(case["text"]), js[case["name"]]["analysis"],
                case["name"])


def test_js_finder_verdicts_agree(js_finder):
    cases = json.loads(FINDER_FIXTURES.read_text())
    js = {r["name"]: r for r in js_finder["verdicts"]}
    for case in cases["verdicts"]:
        _approx(finder.verdict(case["summary"]), js[case["name"]]["verdict"],
                case["name"])
    jsd = {r["name"]: r for r in js_finder["data_verdicts"]}
    for case in cases["data_verdicts"]:
        _approx(finder.verdict_data(case["log"]), jsd[case["name"]]["verdict"],
                case["name"])
