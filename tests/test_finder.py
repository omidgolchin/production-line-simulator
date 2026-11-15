"""Tests for the Bottleneck Finder analysis layer (src/linesim/finder.py):
the five built-in checks' engines, the verdict rules, and log parsing."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from linesim.finder import (analyze_line, analyze_log, improvement_options,
                            kingman, parse_log, release_comparison,
                            tool_config, verdict, verdict_data)
from linesim.simulate import LineConfig, StationSpec


def fixed(v):
    return StationSpec(kind="fixed", value=v)


def norm(mu, cv):
    return StationSpec(kind="normal", mu=mu, sigma=cv * mu)


def die():
    return StationSpec(kind="die")


# ------------------------------------------------------------ throughput

def test_deterministic_line_throughput_is_min_capacity():
    stations = [fixed(5), fixed(3), fixed(4)]
    for release in ({"mode": "push", "rate": 3},
                    {"mode": "push", "rate": 9},
                    {"mode": "conwip", "wip": 10},
                    {"mode": "infinite"}):
        cfg = LineConfig(stations=stations, buffer_limits=[6, 6],
                         release=release)
        agg = analyze_line(cfg, reps=4, periods=200, warmup=40, seed=5)
        assert agg["throughput"] == 3.0, release


def test_tool_config_mapping():
    tool = {"stations": [
                {"name": "A", "mean": 5, "cv": 0, "buffer": None},
                {"name": "B", "mean": 3.5, "cv": 0.49, "buffer": 8,
                 "die": True},
                {"name": "C", "mean": 2.5, "cv": 0, "buffer": None}],
            "release": {"mode": "dbr", "stock": 6}}
    cfg = tool_config(tool)
    assert cfg.stations[0].kind == "fixed"
    assert cfg.stations[1].kind == "die"
    assert cfg.stations[2].kind == "normal" and cfg.stations[2].sigma == 0
    assert cfg.buffer_limits == [8, 10 ** 6]
    assert cfg.release == {"mode": "rope", "bottleneck": 2, "time_buffer": 6}
    tool["stations"][1]["buffer"] = None
    assert tool_config(tool).buffer_limits is None


# ------------------------------------------------------------ Little's law

@pytest.mark.parametrize("cfg", [
    LineConfig(stations=[fixed(5), fixed(3), fixed(4)], buffer_limits=[6, 6],
               release={"mode": "conwip", "wip": 10}),
    LineConfig(stations=[norm(5, .3), norm(3.6, .2), norm(5, .3)],
               buffer_limits=None, release={"mode": "conwip", "wip": 60}),
    LineConfig(stations=[die() for _ in range(5)], buffer_limits=[50] * 4,
               release={"mode": "push", "rate": 3}),
])
def test_littles_law_within_one_percent(cfg):
    agg = analyze_line(cfg, reps=16, periods=400, warmup=60, seed=11)
    assert agg["littles_ratio"] is not None
    assert abs(agg["littles_ratio"] - 1.0) <= 0.01


# ------------------------------------------------------------ Kingman

# The heavy-traffic form runs high in this batch-period model. On the
# three settings below (bottleneck utilization 0.85 to 0.95, measured
# with seed 11) the predicted queue is 1.32x, 1.95x and 1.45x the
# simulated one, so the stated known error is a factor of 0.7 to 2.1.
# Above utilization ~0.98 the formula's denominator (capacity minus
# throughput) is knife-edge and no factor is stated.
@pytest.mark.parametrize("cfg,bi", [
    (LineConfig(stations=[die() for _ in range(5)], buffer_limits=[50] * 4,
                release={"mode": "push", "rate": 3}), 2),
    (LineConfig(stations=[norm(5, .25), norm(3.4, .3), norm(5, .25)],
                buffer_limits=None, release={"mode": "push", "rate": 3}), 1),
    (LineConfig(stations=[norm(6, .2), norm(4.2, .3), norm(6, .2)],
                buffer_limits=None, release={"mode": "push", "rate": 4}), 1),
])
def test_kingman_within_stated_factor(cfg, bi):
    agg = analyze_line(cfg, reps=24, periods=400, warmup=60, seed=11)
    row = kingman(cfg, agg["throughput"])[bi]
    assert row["queue"] is not None
    assert 0.8 <= row["util"] <= 0.97
    sim = agg["mean_buffers"][bi]
    assert sim > 0.5
    assert 0.7 <= row["queue"] / sim <= 2.1


# ------------------------------------------------- improvement options

def test_top_option_is_capacity_at_the_bottleneck():
    tool = {"stations": [
                {"name": "Cut", "mean": 5.5, "cv": 0.25, "buffer": None},
                {"name": "Weld", "mean": 4.6, "cv": 0.30, "buffer": 8},
                {"name": "Paint", "mean": 3.4, "cv": 0.35, "buffer": 8},
                {"name": "Pack", "mean": 5.2, "cv": 0.20, "buffer": 8}],
            "release": {"mode": "dbr", "stock": 8}}
    cfg = tool_config(tool)
    opts = improvement_options(cfg, reps=12, periods=300, warmup=50, seed=3)
    assert opts[0]["kind"] == "capacity" and opts[0]["station"] == 2
    assert opts[0]["gain"] > 0.2
    gains = [o["gain"] for o in opts]
    assert gains == sorted(gains, reverse=True)


def test_release_comparison_pull_is_leaner_at_the_same_output():
    """Every rule is run at 95% of what the line passes fed without
    limit, and then with its setting 20% too high: push releases faster
    than the line can work and its queues grow all run, while CONWIP
    holds only the extra units it was allowed (Hopp & Spearman)."""
    cfg = LineConfig(stations=[die() for _ in range(5)],
                     buffer_limits=[50] * 4,
                     release={"mode": "push", "rate": 4})
    rows = {r["rule"]: r for r in release_comparison(
        cfg, reps=10, periods=300, warmup=50, seed=3)}
    target = rows["push"]["target"]
    for r in rows.values():
        assert r["throughput"] >= 0.97 * target, r
    # set 20% too high, push outruns the line; CONWIP holds a few more
    assert rows["push"]["wip_if_high"] > 3 * rows["push"]["mean_wip"]
    assert rows["conwip"]["wip_if_high"] < 1.3 * rows["conwip"]["mean_wip"]
    assert rows["push"]["wip_if_high"] > 3 * rows["conwip"]["wip_if_high"]


# ------------------------------------------------------------ data mode

def _planted_log(periods=60):
    names = ["Saw", "Mill", "Oven", "Pack"]
    breaks = {0: {7, 19, 26, 38, 47, 55}, 1: {11, 23, 34, 44, 52},
              3: {9, 21, 31, 42, 51}}
    lines = ["period," + ",".join(names)]
    for t in range(1, periods + 1):
        row = []
        for i in range(4):
            if i == 2:
                row.append("busy")
            elif t in breaks[i]:
                row.append("blocked" if i < 2 else "starved")
            else:
                row.append("busy")
        lines.append(str(t) + "," + ",".join(row))
    return "\n".join(lines)


def test_active_period_finds_planted_bottleneck():
    a = analyze_log(_planted_log())
    assert a["names"] == ["Saw", "Mill", "Oven", "Pack"]
    assert a["top"] == 2
    assert a["bottleneck_share"][2] > 0.5
    v = verdict_data(a)
    assert (v["state"], v["reason"]) == ("good", "dominant")


def test_active_period_balanced_log_ties():
    text = "\n".join(["A,B,C"] + ["busy,busy,busy"] * 20)
    a = analyze_log(text)
    assert a["bottleneck_share"] == pytest.approx([1 / 3, 1 / 3, 1 / 3])


def test_parse_log_variants():
    names, outputs, states = parse_log(
        "busy,idle\nbusy,busy\nidle,busy\nbusy,busy\nbusy,idle\nbusy,busy")
    assert names == ["Station 1", "Station 2"]
    assert len(states) == 6
    names, outputs, states = parse_log("Cut;Weld\n4;0\n5;3\n4;2\n6;3\n5;2\n4;3")
    assert names == ["Cut", "Weld"]
    assert outputs[0] == [4.0, 0.0]
    with pytest.raises(Exception):
        analyze_log("Cut,Weld\n4,zz\n5,zz\n4,2\n6,zz\n5,2\n4,3\n3,2\n2,2")
    with pytest.raises(Exception):
        analyze_log("Cut,Weld\n4,3\n5,2")


# ------------------------------------------------------------ verdicts

def _summary(**kw):
    base = {"names": ["A", "B", "C"], "means": [5.0, 3.0, 5.0],
            "limiting": [0.05, 0.9, 0.05], "blocked": [0.0, 0.0, 0.0],
            "th": 2.9, "capability": None, "plan": None,
            "release_mode": "dbr", "push_rate": None,
            "best_gain": 0.4, "best_station": 1, "best_kind": "capacity"}
    base.update(kw)
    return base


@pytest.mark.parametrize("kw,state,reason", [
    ({"means": [4.0, 0.0, 5.0]}, "bad", "zero"),
    ({"release_mode": "push", "push_rate": 7,
      "means": [4.2, 3.8, 4.5], "limiting": [0.3, 0.5, 0.2]}, "bad", "release"),
    ({"release_mode": "push", "push_rate": 3, "capability": 3.4, "th": 2.95,
      "means": [5.0, 3.6, 4.4], "limiting": [0.2, 0.6, 0.2]},
     "warn", "release-limited"),
    ({"plan": 3.8, "th": 3.35, "means": [6.0, 3.6, 4.4],
      "limiting": [0.2, 0.6, 0.2]}, "warn", "plan"),
    ({"blocked": [0.9, 0.1, 0.0], "best_gain": 1.57, "th": 1.85,
      "best_kind": "buffer"}, "good", "buffer"),
    ({"blocked": [0.9, 0.1, 0.0], "best_gain": 0.02, "th": 3.0,
      "best_kind": "buffer"}, "warn", "buffer"),
    ({"means": [3.5, 3.5, 3.5], "limiting": [0.21, 0.19, 0.2], "th": 3.27},
     "accent", "balanced"),
    ({"means": [5.5, 3.4, 3.55], "limiting": [0.1, 0.42, 0.34], "th": 3.3},
     "warn", "wandering"),
    ({"best_gain": 0.02}, "warn", "small-gains"),
    ({}, "good", "clear"),
])
def test_verdict_states(kw, state, reason):
    v = verdict(_summary(**kw))
    assert (v["state"], v["reason"]) == (state, reason)


@pytest.mark.parametrize("log,state,reason", [
    ({"bottleneck_share": [0.6, 0.4, 0.0], "active_share": [1.0, 0.9, 0.0]},
     "bad", "never-active"),
    ({"bottleneck_share": [0.7, 0.2, 0.1], "active_share": [1.0, 0.8, 0.9]},
     "good", "dominant"),
    ({"bottleneck_share": [0.42, 0.38, 0.2], "active_share": [0.9, 0.95, 0.8]},
     "warn", "wandering"),
    ({"bottleneck_share": [0.28, 0.25, 0.24, 0.23],
      "active_share": [0.9, 0.85, 0.8, 0.95]}, "accent", "wandering-wide"),
])
def test_verdict_data_states(log, state, reason):
    v = verdict_data(log)
    assert (v["state"], v["reason"]) == (state, reason)


def test_buffer_verdict_names_the_starved_station():
    v = verdict(_summary(blocked=[0.9, 0.1, 0.0], best_gain=1.57, th=1.85,
                         best_kind="buffer"))
    assert v["blocked_station"] == 0
    assert v["bottleneck"] == 1
