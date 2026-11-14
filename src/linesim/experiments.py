"""Run the four pre-registered experiments and the key-figure time
series, exactly as specified in config.yaml and PLAN.md.

Arms are paired by replication seed (common random numbers): rep r of
every arm uses seed ``seed_base + r``. Raw per-replication metrics go
to ``results/experiments_raw.json``; the time series go to
``results/timeseries.json``. ``python -m linesim.analyze`` turns them
into the summary and figures, so nothing here formats results.

Run:  PYTHONPATH=src python -m linesim.experiments
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import yaml

from .simulate import LineConfig, NumpyRNG, simulate

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"


def load_config() -> dict:
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def run_experiments(cfg: dict) -> dict:
    exp = cfg["experiments"]
    horizon, warmup = exp["horizon"], exp["warmup"]
    reps, base = exp["replications"], exp["seed_base"]
    out: dict[str, dict[str, list]] = {}
    for arm, spec in exp["arms"].items():
        line = LineConfig.from_dict(spec)
        rows = {"throughput": [], "mean_wip": [], "mean_ct": [],
                "littles_ratio": []}
        for r in range(reps):
            res = simulate(line, horizon, NumpyRNG(base + r),
                           warmup=warmup)
            for k in rows:
                rows[k].append(res[k])
        out[arm] = rows
        print(f"{arm}: TH={np.mean(rows['throughput']):.3f} "
              f"WIP={np.mean(rows['mean_wip']):.2f} "
              f"CT={np.mean(rows['mean_ct']):.2f} "
              f"L-ratio={np.nanmean(rows['littles_ratio']):.3f}")
    return out


def run_timeseries(cfg: dict) -> dict:
    ts = cfg["timeseries"]
    arms = {a: cfg["experiments"]["arms"][a] for a in ts["arms"]}
    out: dict[str, dict] = {}
    for arm, spec in arms.items():
        line = LineConfig.from_dict(spec)
        outs, wips = [], []
        for r in range(ts["replications"]):
            res = simulate(line, ts["horizon"],
                           NumpyRNG(ts["seed_base"] + r), record=True)
            outs.append(res["series_output"])
            wips.append(res["series_wip"])
        mean_out = np.mean(outs, axis=0)
        out[arm] = {
            "mean_output": [float(x) for x in mean_out],
            "cum_output": [float(x) for x in np.cumsum(mean_out)],
            "mean_wip_end": [float(x) for x in np.mean(wips, axis=0)],
            "plan_rate": ts["plan_rate"][arm],
        }
        print(f"timeseries {arm}: final cum output "
              f"{out[arm]['cum_output'][-1]:.1f} vs plan "
              f"{ts['plan_rate'][arm] * ts['horizon']:.0f}")
    return out


def main() -> None:
    cfg = load_config()
    RESULTS.mkdir(parents=True, exist_ok=True)
    raw = run_experiments(cfg)
    with open(RESULTS / "experiments_raw.json", "w") as f:
        json.dump(raw, f)
    series = run_timeseries(cfg)
    with open(RESULTS / "timeseries.json", "w") as f:
        json.dump(series, f)
    print("wrote results/experiments_raw.json and results/timeseries.json")


if __name__ == "__main__":
    main()
