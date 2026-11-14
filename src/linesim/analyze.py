"""Turn the saved outputs into results/summary.md and the figures.

Inputs (all saved by earlier steps; no API calls here):
  results/experiments_raw.json   per-replication metrics per arm
  results/timeseries.json        key-figure time series
  results/ground_truth.json      LLM-check truth
  outputs/llm_runs.jsonl         main LLM-check calls (if present)
  outputs/pilot_runs.jsonl       pilot calls (spend only)
  outputs/pricing_snapshot.json  Together prices at run time

Run:  PYTHONPATH=src python -m linesim.analyze   (or: make reproduce)
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .experiments import ROOT  # noqa: E402
from .score import score_row  # noqa: E402
from .stats import mean_ci, paired_diff_ci, wilson_ci  # noqa: E402

RESULTS = ROOT / "results"
FIGURES = RESULTS / "figures"
OUTPUTS = ROOT / "outputs"


def _fmt(ci) -> str:
    return f"{ci[0]:.2f} [{ci[1]:.2f}, {ci[2]:.2f}]"


def _load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines()
            if l.strip()]


def spend_by_model(rows: list, prices: dict) -> dict:
    out: dict[str, dict] = {}
    for r in rows:
        u = r.get("usage") or {}
        p = prices.get(r["model"], {})
        cost = (u.get("prompt_tokens", 0) * (p.get("input") or 0)
                + u.get("completion_tokens", 0)
                * (p.get("output") or 0)) / 1e6
        d = out.setdefault(r["model"], {"calls": 0, "cost": 0.0,
                                        "prompt_tokens": 0,
                                        "completion_tokens": 0})
        d["calls"] += 1
        d["cost"] += cost
        d["prompt_tokens"] += u.get("prompt_tokens", 0)
        d["completion_tokens"] += u.get("completion_tokens", 0)
    return out


# ------------------------------------------------------------ figures


def fig_key(series: dict) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
    labels = {"e1_die": "Balanced line, dice (push, endless supply)",
              "e4_dbr": "Bottleneck line, drum-buffer-rope"}
    for arm, s in series.items():
        t = np.arange(1, len(s["cum_output"]) + 1)
        axes[0].plot(t, s["cum_output"], label=labels[arm])
        axes[0].plot(t, s["plan_rate"] * t, "--", alpha=0.6,
                     label=f"plan at {s['plan_rate']}/period")
        axes[1].plot(t, s["mean_wip_end"], label=labels[arm])
    axes[0].set_xlabel("period")
    axes[0].set_ylabel("cumulative output (units)")
    axes[0].set_title("Output vs plan")
    axes[0].legend(fontsize=7)
    axes[1].set_xlabel("period")
    axes[1].set_ylabel("mean WIP at end of period (units)")
    axes[1].set_title("Work in progress")
    axes[1].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(FIGURES / "key_figure.png", dpi=150)
    plt.close(fig)


def fig_experiments(raw: dict) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(10, 7))
    panels = [
        ("E1: variability on a balanced line", "throughput",
         [("e1_fixed", "fixed 4"), ("e1_die", "dice (mean 3.5)"),
          ("e1_uni34", "uniform 3-4 (mean 3.5)")], 3.5),
        ("E2: buffer size (dice line)", "throughput",
         [("e1_die", "unlimited"), ("e2_cap10", "cap 10"),
          ("e2_cap4", "cap 4"), ("e2_cap2", "cap 2")], None),
        ("E3: adding capacity (bottleneck line)", "throughput",
         [("e3_base", "base"), ("e3_bn_up", "+1 at bottleneck"),
          ("e3_s1_up", "+1 at station 1")], 2.5),
        ("E4: push vs drum-buffer-rope (WIP)", "mean_wip",
         [("e4_push", "push 5/period"), ("e4_dbr", "drum-buffer-rope")],
         None),
    ]
    for ax, (title, metric, arms, ref) in zip(axes.flat, panels):
        means, los, his = [], [], []
        for arm, _ in arms:
            m, lo, hi = mean_ci(raw[arm][metric])
            means.append(m); los.append(m - lo); his.append(hi - m)
        ax.bar([a[1] for a in arms], means,
               yerr=[los, his], capsize=4)
        if ref is not None:
            ax.axhline(ref, color="grey", linestyle="--", linewidth=1)
        ax.set_title(title, fontsize=10)
        ax.set_ylabel("units / period" if metric == "throughput"
                      else "units")
        ax.tick_params(axis="x", labelrotation=15, labelsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "experiments.png", dpi=150)
    plt.close(fig)


def fig_llm(scored: list, models: list) -> None:
    modes = ["direct", "code", "fromdata"]
    fig, ax = plt.subplots(figsize=(8, 3.8))
    x = np.arange(len(models))
    width = 0.26
    for j, mode in enumerate(modes):
        accs = []
        for model in models:
            rows = [s for s in scored
                    if s["model"] == model and s["mode"] == mode]
            k = sum(1 for s in rows if s["bottleneck_correct"])
            accs.append(k / len(rows) if rows else 0.0)
        ax.bar(x + (j - 1) * width, accs, width, label=mode)
    ax.set_xticks(x)
    ax.set_xticklabels([m.split("/")[-1] for m in models], fontsize=8)
    ax.set_ylabel("bottleneck accuracy")
    ax.set_ylim(0, 1.05)
    ax.set_title("Can an LLM find the bottleneck? (12 configurations)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIGURES / "llm_check.png", dpi=150)
    plt.close(fig)


# ------------------------------------------------------------- summary


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    prices = {}
    snap = OUTPUTS / "pricing_snapshot.json"
    if snap.exists():
        prices = json.loads(snap.read_text())["prices_per_million_tokens"]

    raw = json.loads((RESULTS / "experiments_raw.json").read_text())
    series = json.loads((RESULTS / "timeseries.json").read_text())
    fig_key(series)
    fig_experiments(raw)

    L = []
    L.append("# Results\n")
    L.append("All numbers come from the frozen design in PLAN.md and "
             "config.yaml. Experiments: 48 paired replications per arm "
             "(seeds shared across arms), 250 periods each, the first "
             "50 excluded. Intervals are 95% t-intervals; contrasts "
             "are per-seed paired differences.\n")

    def arm_table(arms, metrics=("throughput", "mean_wip", "mean_ct")):
        names = {"throughput": "Throughput", "mean_wip": "Mean WIP",
                 "mean_ct": "Mean cycle time"}
        rows = ["| Arm | " + " | ".join(names[m] for m in metrics)
                + " |", "|---|" + "---|" * len(metrics)]
        for arm in arms:
            cells = [_fmt(mean_ci(raw[arm][m])) for m in metrics]
            rows.append(f"| {arm} | " + " | ".join(cells) + " |")
        return "\n".join(rows)

    def contrast(a, b, metric):
        m, lo, hi = paired_diff_ci(raw[a][metric], raw[b][metric])
        return f"{m:+.2f} [{lo:+.2f}, {hi:+.2f}]"

    L.append("## Experiment 1 — variability on a balanced line\n")
    L.append(arm_table(["e1_fixed", "e1_die", "e1_uni34"]))
    die = mean_ci(raw["e1_die"]["throughput"])
    uni = mean_ci(raw["e1_uni34"]["throughput"])
    L.append(f"\nWith no variability the line delivers its capacity "
             f"exactly (4.00 per period). With dice — mean capacity "
             f"3.5 — throughput is {_fmt(die)}, a loss of "
             f"{3.5 - die[0]:.2f} units per period "
             f"({100 * (3.5 - die[0]) / 3.5:.0f}%) against the "
             f"stations' own average. Even the mild uniform 3–4 "
             f"variability loses output: {_fmt(uni)}. The stations are "
             f"dependent, so a slow period upstream cannot be made up "
             f"downstream — the game's lesson, with an interval on "
             f"it.\n")

    L.append("## Experiment 2 — buffer size (dice line)\n")
    L.append(arm_table(["e1_die", "e2_cap10", "e2_cap4", "e2_cap2"]))
    L.append(f"\nPaired throughput change vs unlimited buffers: "
             f"cap 10: {contrast('e2_cap10', 'e1_die', 'throughput')}; "
             f"cap 4: {contrast('e2_cap4', 'e1_die', 'throughput')}; "
             f"cap 2: {contrast('e2_cap2', 'e1_die', 'throughput')}. "
             f"Buffers buy throughput with WIP: capping at 2 cuts mean "
             f"WIP by {contrast('e2_cap2', 'e1_die', 'mean_wip')} units "
             f"but costs output.\n")

    L.append("## Experiment 3 — where to add capacity\n")
    L.append(arm_table(["e3_base", "e3_bn_up", "e3_s1_up"]))
    L.append(f"\nThe bottleneck is station 3 (mean capacity 2.5; the "
             f"rest average 3.5). Adding +1 mean capacity at the "
             f"bottleneck changes throughput by "
             f"{contrast('e3_bn_up', 'e3_base', 'throughput')}; the "
             f"same money at station 1 changes it by "
             f"{contrast('e3_s1_up', 'e3_base', 'throughput')} — while "
             f"still piling up WIP in front of the bottleneck "
             f"({contrast('e3_s1_up', 'e3_base', 'mean_wip')} mean "
             f"WIP).\n")

    L.append("## Experiment 4 — push vs drum-buffer-rope\n")
    L.append(arm_table(["e4_push", "e4_dbr"]))
    lr_p = mean_ci([x for x in raw["e4_push"]["littles_ratio"]])
    lr_d = mean_ci([x for x in raw["e4_dbr"]["littles_ratio"]])
    L.append(f"\nSame bottleneck line, two release policies. Paired "
             f"differences (DBR − push): throughput "
             f"{contrast('e4_dbr', 'e4_push', 'throughput')}, mean WIP "
             f"{contrast('e4_dbr', 'e4_push', 'mean_wip')}, mean cycle "
             f"time {contrast('e4_dbr', 'e4_push', 'mean_ct')}. "
             f"Little's Law in the simulator's own counters: ratio "
             f"{_fmt(lr_p)} under push, {_fmt(lr_d)} under DBR "
             f"(1.00 = exact). The push ratio is not a failure of the "
             f"law: Little's Law is a steady-state statement, and "
             f"under push this line's queue in front of the bottleneck "
             f"grows all run long, so the units completing inside the "
             f"window entered when the queue was shorter than the "
             f"window's average WIP implies. Where the line is stable "
             f"(balanced line, capped buffers, DBR), the ratio sits "
             f"at 1.00–1.06 in these experiments, and exactly 1 on "
             f"the fixed-capacity line.\n")

    # ---------------------------------------------------- LLM check
    runs = _load_jsonl(OUTPUTS / "llm_runs.jsonl")
    pilot = (_load_jsonl(OUTPUTS / "pilot_runs.jsonl")
             + _load_jsonl(OUTPUTS / "pilot_runs_v1.jsonl"))
    if runs:
        truth = json.loads((RESULTS / "ground_truth.json").read_text())
        scored = []
        for r in runs:
            if r.get("status") != "ok":
                continue
            s = score_row(r["parsed"], truth[r["config"]], r["mode"])
            s.update({"model": r["model"], "mode": r["mode"],
                      "config": r["config"]})
            scored.append(s)
        models = sorted({s["model"] for s in scored})
        fig_llm(scored, models)
        L.append("## LLM check — can a model find the bottleneck?\n")
        L.append("12 line configurations, three ways of answering: "
                 "*direct* (from the configuration), *code* (the model "
                 "writes a simulation; its printed answer is scored), "
                 "and *from data* (from a 50-period process log). "
                 "Ground truth: 1,000 replications of the simulator "
                 "per configuration. Accuracy intervals are Wilson "
                 "intervals over the 12 configurations.\n")
        L.append("| Model | Mode | Bottleneck accuracy | Throughput "
                 "MAE | Mean |rel. error| |")
        L.append("|---|---|---|---|---|")
        for model in models:
            for mode in ("direct", "code", "fromdata"):
                rows = [s for s in scored if s["model"] == model
                        and s["mode"] == mode]
                if not rows:
                    continue
                k = sum(1 for s in rows if s["bottleneck_correct"])
                p, lo, hi = wilson_ci(k, len(rows))
                mae = [s["throughput_abs_error"] for s in rows
                       if "throughput_abs_error" in s]
                rel = [s["throughput_rel_error"] for s in rows
                       if "throughput_rel_error" in s]
                mae_s = (f"{np.mean(mae):.2f} (n={len(mae)})"
                         if mae else "—")
                rel_s = f"{np.mean(rel):.2f}" if rel else "—"
                L.append(f"| {model} | {mode} | {k}/{len(rows)} = "
                         f"{p:.2f} [{lo:.2f}, {hi:.2f}] | {mae_s} | "
                         f"{rel_s} |")
        fails = [r for r in runs if r.get("status") != "ok"]
        bad_code = [r for r in runs if r["mode"] == "code"
                    and r.get("status") == "ok"
                    and not r.get("sandbox", {}).get("ok")]
        L.append(f"\nFailed calls: {len(fails)} of {len(runs)}. "
                 f"Code-mode programs that failed to run: "
                 f"{len(bad_code)} of "
                 f"{sum(1 for r in runs if r['mode'] == 'code')}.\n")
        L.append("\nReading the table: asked directly, all three "
                 "models name the bottleneck on all 12 configurations "
                 "and estimate throughput closely — the lowest-mean-"
                 "capacity rule is easy to state. Code mode separates "
                 "them. MiniMax's programs run and reproduce the "
                 "bottleneck on all 12; gpt-oss's programs all run and "
                 "its simulated throughputs are usually close, but "
                 "its bottleneck pick is wrong on 3 (its simulation "
                 "can be right about output and wrong about which "
                 "station limits it). GLM returns no program at all "
                 "on 8 of 12 configurations — all of them ones with "
                 "variable capacities: it spends the entire "
                 "16,000-token budget reasoning and the reply is "
                 "empty. Where its programs do run (the fixed-"
                 "capacity and simplest lines), they are the most "
                 "accurate in the table. One shared miss: on the "
                 "balanced dice line, both other models' written "
                 "simulations report 3.47–3.49 units per period — "
                 "near the naive average of 3.5 and above the true "
                 "3.29 — so their simulators understate the very "
                 "dependency loss the dice game is about. Reading a "
                 "log is the hardest mode for every model "
                 "(6–9 of 12).\n")

    # --------------------------------------------------------- spend
    all_rows = runs + pilot
    if all_rows:
        spend = spend_by_model(all_rows, prices)
        total = sum(v["cost"] for v in spend.values())
        L.append("## Spend\n")
        L.append("| Model | Calls (pilot + main) | Cost |")
        L.append("|---|---|---|")
        for model, v in sorted(spend.items()):
            L.append(f"| {model} | {v['calls']} | ${v['cost']:.3f} |")
        L.append(f"| **Total** | **{sum(v['calls'] for v in spend.values())}** "
                 f"| **${total:.3f}** |")
        L.append("\nPrices: Together list prices on 2026-11-13 "
                 "(outputs/pricing_snapshot.json); cost computed from "
                 "returned token usage.\n")

    (RESULTS / "summary.md").write_text("\n".join(L) + "\n")
    print("wrote results/summary.md and figures")


if __name__ == "__main__":
    main()
