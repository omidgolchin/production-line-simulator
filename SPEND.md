# Spend

Cap for this project: **$4** of model calls (program cap $60).
Prices are the Together list prices fetched on 2026-11-13
(`outputs/pricing_snapshot.json`); cost is computed from the token
usage returned with each call. All calls are recorded in
`outputs/pilot_runs_v1.jsonl`, `outputs/pilot_runs.jsonl` and
`outputs/llm_runs.jsonl`.

| Model | Calls (pilots + main) | Cost |
|---|---|---|
| openai/gpt-oss-120b | 66 | $0.070 |
| MiniMaxAI/MiniMax-M3.1-Flash | 66 | $0.211 |
| zai-org/GLM-5.3-Flash | 66 | $0.235 |
| deepseek-ai/DeepSeek-V4.1-Flash | 30 (pilots only) | $0.132 |
| Qwen/Qwen3.5-9B | 30 (pilots only) | $0.065 |
| mistralai/Mistral-Small-24B-Instruct-2501 | 30 (all calls HTTP 400, non-serverless) | $0.000 |
| **Total** | **288** | **$0.714** |

By stage: pilot v1 (superseded by the token-budget correction,
DECISIONS.md #10) $0.132; pilot v2 $0.253; main run $0.329.
Local simulation (experiments, ground truth) costs nothing.

2026-11-16: structural-variation restructure (diagram-first layout; page structure only, no engine or results changes) — $0.00 API spend.
- 2026-11-16: guide sections (start here, situations, when to use, where it comes from) — $0.00 API spend; all work local.
