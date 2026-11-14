"""Build docs/data/results.json for the playground from the saved
results (experiments + LLM check). Display strings are formatted
here so docs/app.js only injects them.

Run after analyze inputs exist:
  PYTHONPATH=src python scripts/make_docs_data.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from linesim.score import score_row  # noqa: E402
from linesim.stats import mean_ci, paired_diff_ci  # noqa: E402

RESULTS = ROOT / "results"
OUTPUTS = ROOT / "outputs"


def fmt(ci) -> str:
    return f"{ci[0]:.2f} [{ci[1]:.2f}, {ci[2]:.2f}]"


def signed(ci) -> str:
    return f"{ci[0]:+.2f} [{ci[1]:+.2f}, {ci[2]:+.2f}]"


def main() -> None:
    raw = json.loads((RESULTS / "experiments_raw.json").read_text())

    def arm(arm_id, label):
        return {"label": label,
                "throughput": fmt(mean_ci(raw[arm_id]["throughput"])),
                "wip": fmt(mean_ci(raw[arm_id]["mean_wip"])),
                "ct": fmt(mean_ci(raw[arm_id]["mean_ct"]))}

    die = mean_ci(raw["e1_die"]["throughput"])
    uni = mean_ci(raw["e1_uni34"]["throughput"])
    experiments = {
        "e1": [arm("e1_fixed", "Fixed capacity 4 (no variability)"),
               arm("e1_die", "Dice, mean capacity 3.5"),
               arm("e1_uni34", "Uniform 3–4, mean capacity 3.5")],
        "e1_text": (
            f"A line with no variability delivers its capacity exactly. "
            f"Give every station a die (mean 3.5) and throughput falls "
            f"to {fmt(die)} — about {100 * (3.5 - die[0]) / 3.5:.0f}% "
            f"below the stations' own average. Even mild uniform 3–4 "
            f"variability loses output ({fmt(uni)}). A station that had "
            f"a bad period cannot be caught up by the next one: the "
            f"events are dependent."),
        "e2_text": (
            f"Capping the buffers between stations at 10 changes "
            f"throughput by "
            f"{signed(paired_diff_ci(raw['e2_cap10']['throughput'], raw['e1_die']['throughput']))}; "
            f"at 4, by "
            f"{signed(paired_diff_ci(raw['e2_cap4']['throughput'], raw['e1_die']['throughput']))}; "
            f"at 2, by "
            f"{signed(paired_diff_ci(raw['e2_cap2']['throughput'], raw['e1_die']['throughput']))}. "
            f"Buffers are where variability is absorbed: tighter "
            f"buffers mean less WIP and less output."),
        "e3_text": (
            f"On a line whose third station averages 2.5 against "
            f"everyone else's 3.5, adding +1 mean capacity at the "
            f"bottleneck changes throughput by "
            f"{signed(paired_diff_ci(raw['e3_bn_up']['throughput'], raw['e3_base']['throughput']))}. "
            f"The same addition at station 1 changes it by "
            f"{signed(paired_diff_ci(raw['e3_s1_up']['throughput'], raw['e3_base']['throughput']))} "
            f"— capacity away from the bottleneck only piles up "
            f"inventory in front of it."),
        "e4_text": (
            f"Releasing work at the bottleneck's pace "
            f"(drum-buffer-rope) instead of pushing 5 units a period "
            f"changes throughput by "
            f"{signed(paired_diff_ci(raw['e4_dbr']['throughput'], raw['e4_push']['throughput']))}, "
            f"mean WIP by "
            f"{signed(paired_diff_ci(raw['e4_dbr']['mean_wip'], raw['e4_push']['mean_wip']))} units, "
            f"and mean cycle time by "
            f"{signed(paired_diff_ci(raw['e4_dbr']['mean_ct'], raw['e4_push']['mean_ct']))} periods. "
            f"Same output, far less inventory sitting in the line."),
    }

    llm = {"rows": [], "text": ""}
    runs_path = OUTPUTS / "llm_runs.jsonl"
    if runs_path.exists():
        truth = json.loads((RESULTS / "ground_truth.json").read_text())
        rows = [json.loads(l) for l in runs_path.read_text().splitlines()
                if l.strip()]
        scored = []
        for r in rows:
            if r.get("status") != "ok":
                continue
            s = score_row(r["parsed"], truth[r["config"]], r["mode"])
            s.update({"model": r["model"], "mode": r["mode"]})
            scored.append(s)
        for model in sorted({s["model"] for s in scored}):
            for mode in ("direct", "code", "fromdata"):
                sub = [s for s in scored if s["model"] == model
                       and s["mode"] == mode]
                if not sub:
                    continue
                k = sum(1 for s in sub if s["bottleneck_correct"])
                mae = [s["throughput_abs_error"] for s in sub
                       if "throughput_abs_error" in s]
                llm["rows"].append({
                    "model": model.split("/")[-1], "mode": mode,
                    "accuracy": f"{k}/{len(sub)}",
                    "mae": (f"{sum(mae) / len(mae):.2f}" if mae else "—"),
                })
        by_mode = {}
        for mode in ("direct", "code", "fromdata"):
            sub = [s for s in scored if s["mode"] == mode]
            if sub:
                by_mode[mode] = (sum(1 for s in sub
                                     if s["bottleneck_correct"])
                                 / len(sub))
        llm["text"] = (
            "Across all models, bottleneck accuracy by mode: "
            + ", ".join(f"{m} {v:.0%}" for m, v in by_mode.items())
            + ". Full intervals and per-configuration detail are in "
              "the repository's results/summary.md.")

    data = {"experiments": experiments, "llm": llm}
    out = ROOT / "docs" / "data" / "results.json"
    out.write_text(json.dumps(data, indent=1))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
