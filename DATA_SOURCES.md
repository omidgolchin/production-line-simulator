# Data sources

This project uses **no external datasets**. Every number comes from
the project's own simulator:

| Data | Source | License / terms |
|---|---|---|
| Experiment replications | `linesim.experiments` runs of the simulator in this repo, seeds in config.yaml | Own work, MIT |
| Key-figure time series | Same simulator, recorded per-period series | Own work, MIT |
| LLM-check ground truth | 1,000 simulator replications per configuration (`linesim.groundtruth`) | Own work, MIT |
| From-data process logs | One seeded simulator run per configuration, saved in `results/logs/` | Own work, MIT |
| LLM answers | Together AI chat API calls, raw rows in `outputs/llm_runs.jsonl`, `outputs/pilot_runs.jsonl`, and the archived first pilot `outputs/pilot_runs_v1.jsonl` (superseded before the freeze; see DECISIONS.md #10) | Together AI terms of service; only derived scores are republished in results |
| Model prices | Together API `list-models` snapshot, 2026-11-13, in `outputs/pricing_snapshot.json` | Together AI public pricing |

The dice game itself is described in Goldratt & Cox, *The Goal*
(1984); no text from the book is reproduced. Playground JSON in
`docs/data/` contains only derived results (experiment means,
intervals, LLM-check scores) produced by the code in this repo.
