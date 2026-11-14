"""Engine tests, including the three the spec names:

* fixed capacities -> output is exactly the minimum station capacity
  per period;
* Little's Law holds in steady state (in the simulator's own
  counters);
* Python/JavaScript agreement on fixed seeds (test_js_agreement.py).
"""

import numpy as np
import pytest

from linesim.simulate import LCG, LineConfig, NumpyRNG, StationSpec, simulate


def fixed_line(caps):
    return LineConfig(stations=[StationSpec(kind="fixed", value=c)
                                for c in caps])


def die_line(n=5):
    return LineConfig(stations=[StationSpec(kind="die") for _ in range(n)])


def test_fixed_capacities_give_min_capacity_per_period():
    res = simulate(fixed_line([5, 3, 4]), 40, NumpyRNG(1), record=True)
    assert res["series_output"] == [3] * 40
    assert res["throughput"] == 3.0


def test_fixed_bottleneck_first_station():
    res = simulate(fixed_line([2, 5, 3]), 25, NumpyRNG(1), record=True)
    assert res["series_output"] == [2] * 25


def test_fixed_line_littles_law_exact():
    # Every unit flows through in the period it enters: CT = 1,
    # WIP during a period = 4, TH = 4 -> ratio exactly 1.
    res = simulate(fixed_line([4, 4, 4, 4, 4]), 60, NumpyRNG(1))
    assert res["throughput"] == 4.0
    assert res["mean_ct"] == 1.0
    assert res["littles_ratio"] == pytest.approx(1.0)


def test_littles_law_die_line_steady_state():
    res = simulate(die_line(), 3000, NumpyRNG(7), warmup=300)
    assert abs(res["littles_ratio"] - 1.0) < 0.08


def test_determinism_same_seed():
    a = simulate(die_line(), 100, LCG(42), record=True)
    b = simulate(die_line(), 100, LCG(42), record=True)
    assert a["series_output"] == b["series_output"]
    assert a["series_buffers"] == b["series_buffers"]
    c = simulate(die_line(), 100, LCG(43), record=True)
    assert a["series_output"] != c["series_output"]


def test_lcg_die_distribution():
    rng = LCG(123)
    draws = [rng.die() for _ in range(60000)]
    assert min(draws) == 1 and max(draws) == 6
    assert abs(np.mean(draws) - 3.5) < 0.05


def test_buffer_cap_reduces_throughput():
    capped = LineConfig(stations=[StationSpec(kind="die")
                                   for _ in range(5)],
                        buffer_limits=[2, 2, 2, 2])
    th_free, th_cap = [], []
    for s in range(20):
        th_free.append(simulate(die_line(), 250, NumpyRNG(s),
                                warmup=50)["throughput"])
        th_cap.append(simulate(capped, 250, NumpyRNG(s),
                               warmup=50)["throughput"])
    assert np.mean(th_cap) < np.mean(th_free)


def test_dbr_cuts_wip_at_similar_throughput():
    stations = [StationSpec(kind="die"), StationSpec(kind="die"),
                StationSpec(kind="uniform", lo=1, hi=4),
                StationSpec(kind="die"), StationSpec(kind="die")]
    push = LineConfig(stations=stations, release={"mode": "push",
                                                  "rate": 5})
    dbr = LineConfig(stations=stations,
                     release={"mode": "dbr", "bottleneck": 2,
                              "time_buffer": 10})
    wip_p, wip_d, th_p, th_d = [], [], [], []
    for s in range(24):
        rp = simulate(push, 250, NumpyRNG(100 + s), warmup=50)
        rd = simulate(dbr, 250, NumpyRNG(100 + s), warmup=50)
        wip_p.append(rp["mean_wip"]); wip_d.append(rd["mean_wip"])
        th_p.append(rp["throughput"]); th_d.append(rd["throughput"])
    assert np.mean(wip_d) < 0.6 * np.mean(wip_p)
    assert np.mean(th_d) > 0.85 * np.mean(th_p)


def test_counts_fast_path_matches_full_engine():
    from linesim.simulate import simulate_counts
    cfgs = [die_line(),
            LineConfig(stations=[StationSpec(kind="die"),
                                 StationSpec(kind="uniform", lo=1, hi=4),
                                 StationSpec(kind="die")],
                       buffer_limits=[3, 3],
                       release={"mode": "push", "rate": 5}),
            LineConfig(stations=[StationSpec(kind="die"),
                                 StationSpec(kind="uniform", lo=1, hi=4),
                                 StationSpec(kind="die")],
                       release={"mode": "dbr", "bottleneck": 1,
                                "time_buffer": 10})]
    for cfg in cfgs:
        for seed in (3, 17, 42):
            full = simulate(cfg, 200, NumpyRNG(seed), warmup=50)
            fast = simulate_counts(cfg, 200, NumpyRNG(seed), warmup=50)
            assert fast["throughput"] == full["throughput"]
            assert fast["output"] == full["output"]


def test_bottleneck_index():
    cfg = LineConfig(stations=[StationSpec(kind="die"),
                               StationSpec(kind="uniform", lo=1, hi=4),
                               StationSpec(kind="die")])
    assert cfg.bottleneck_index() == 1
    assert die_line().bottleneck_index() is None
