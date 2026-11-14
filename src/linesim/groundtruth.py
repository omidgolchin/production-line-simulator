"""Ground truth for the LLM check, from the simulator itself.

For each of the 12 configurations in config.yaml: the bottleneck is
the station with the lowest mean capacity ("none" if all means are
equal), and the throughput truth is the mean output per period over
1,000 replications. Also writes the 50-period process log used by the
from-data mode to ``results/logs/<config>.csv`` (one seeded run:
per-station output and the input buffers of stations 2..N).

Run:  PYTHONPATH=src python -m linesim.groundtruth
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from .experiments import load_config
from .simulate import LineConfig, NumpyRNG, simulate, simulate_counts
from .stats import mean_ci

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
TRUTH_PATH = RESULTS / "ground_truth.json"


def main() -> None:
    cfg = load_config()
    llm = cfg["llm_check"]
    gt_cfg = llm["ground_truth"]
    # Checkpointed: keep any configs already computed (same frozen
    # design) and fill in the rest, rewriting the file per config.
    truth: dict[str, dict] = {}
    if TRUTH_PATH.exists():
        truth = json.loads(TRUTH_PATH.read_text())
    logs_dir = RESULTS / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    for cid, spec in llm["configs"].items():
        if cid in truth and (logs_dir / f"{cid}.csv").exists():
            print(f"{cid}: already done, skipping")
            continue
        line = LineConfig.from_dict({"stations": spec["stations"],
                                      "release": {"mode": "infinite"}})
        ths = []
        for r in range(gt_cfg["replications"]):
            res = simulate_counts(line, gt_cfg["horizon"],
                                  NumpyRNG(gt_cfg["seed_base"] + r),
                                  warmup=gt_cfg["warmup"])
            ths.append(res["throughput"])
        mean, lo, hi = mean_ci(ths)
        bn = line.bottleneck_index()
        truth[cid] = {
            "bottleneck": (bn + 1) if bn is not None else "none",
            "bottleneck_mean_capacity": (
                line.stations[bn].mean if bn is not None else None),
            "throughput": mean,
            "throughput_ci": [lo, hi],
            "stations": [s.describe() for s in line.stations],
        }
        print(f"{cid}: bottleneck={truth[cid]['bottleneck']} "
              f"TH={mean:.3f} [{lo:.3f}, {hi:.3f}]", flush=True)

        # 50-period log for the from-data mode (single seeded run).
        res = simulate(line, llm["log_periods"],
                       NumpyRNG(llm["log_seed"]), record=True)
        n = line.n
        with open(logs_dir / f"{cid}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["period"]
                       + [f"out_{i + 1}" for i in range(n)]
                       + [f"wip_before_{i + 2}" for i in range(n - 1)])
            for t in range(llm["log_periods"]):
                w.writerow([t + 1] + res["series_station_output"][t]
                           + res["series_buffers"][t])

        with open(TRUTH_PATH, "w") as f:
            json.dump(truth, f, indent=1)

    print("wrote results/ground_truth.json and results/logs/")


if __name__ == "__main__":
    main()
