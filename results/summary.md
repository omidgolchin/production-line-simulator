# Results

All numbers come from the frozen design in PLAN.md and config.yaml. Experiments: 48 paired replications per arm (seeds shared across arms), 250 periods each, the first 50 excluded. Intervals are 95% t-intervals; contrasts are per-seed paired differences.

## Experiment 1 — variability on a balanced line

| Arm | Throughput | Mean WIP | Mean cycle time |
|---|---|---|---|
| e1_fixed | 4.00 [4.00, 4.00] | 4.00 [4.00, 4.00] | 1.00 [1.00, 1.00] |
| e1_die | 3.27 [3.24, 3.30] | 58.12 [53.20, 63.04] | 16.75 [15.39, 18.11] |
| e1_uni34 | 3.43 [3.43, 3.44] | 18.88 [17.64, 20.12] | 5.41 [5.06, 5.76] |

With no variability the line delivers its capacity exactly (4.00 per period). With dice — mean capacity 3.5 — throughput is 3.27 [3.24, 3.30], a loss of 0.23 units per period (6%) against the stations' own average. Even the mild uniform 3–4 variability loses output: 3.43 [3.43, 3.44]. The stations are dependent, so a slow period upstream cannot be made up downstream — the game's lesson, with an interval on it.

## Experiment 2 — buffer size (dice line)

| Arm | Throughput | Mean WIP | Mean cycle time |
|---|---|---|---|
| e1_die | 3.27 [3.24, 3.30] | 58.12 [53.20, 63.04] | 16.75 [15.39, 18.11] |
| e2_cap10 | 2.96 [2.93, 2.98] | 17.23 [16.77, 17.70] | 5.84 [5.67, 6.00] |
| e2_cap4 | 2.23 [2.21, 2.24] | 5.77 [5.68, 5.85] | 2.59 [2.55, 2.63] |
| e2_cap2 | 1.55 [1.54, 1.56] | 2.45 [2.42, 2.47] | 1.58 [1.56, 1.60] |

Paired throughput change vs unlimited buffers: cap 10: -0.32 [-0.34, -0.30]; cap 4: -1.05 [-1.07, -1.02]; cap 2: -1.72 [-1.75, -1.69]. Buffers buy throughput with WIP: capping at 2 cuts mean WIP by -55.67 [-60.58, -50.77] units but costs output.

## Experiment 3 — where to add capacity

| Arm | Throughput | Mean WIP | Mean cycle time |
|---|---|---|---|
| e3_base | 2.49 [2.47, 2.51] | 155.53 [149.08, 161.99] | 44.71 [43.05, 46.38] |
| e3_bn_up | 3.29 [3.26, 3.32] | 54.21 [49.49, 58.93] | 15.61 [14.31, 16.91] |
| e3_s1_up | 2.49 [2.47, 2.51] | 305.09 [298.65, 311.54] | 68.31 [67.09, 69.52] |

The bottleneck is station 3 (mean capacity 2.5; the rest average 3.5). Adding +1 mean capacity at the bottleneck changes throughput by +0.80 [+0.77, +0.83]; the same money at station 1 changes it by +0.00 [+0.00, +0.00] — while still piling up WIP in front of the bottleneck (+149.56 [+149.15, +149.97] mean WIP).

## Experiment 4 — push vs drum-buffer-rope

| Arm | Throughput | Mean WIP | Mean cycle time |
|---|---|---|---|
| e4_push | 2.49 [2.47, 2.51] | 384.24 [381.10, 387.38] | 77.22 [76.47, 77.97] |
| e4_dbr | 2.47 [2.45, 2.48] | 19.38 [17.46, 21.30] | 7.76 [6.99, 8.54] |

Same bottleneck line, two release policies. Paired differences (DBR − push): throughput -0.03 [-0.04, -0.02], mean WIP -364.86 [-366.55, -363.17], mean cycle time -69.45 [-69.88, -69.02]. Little's Law in the simulator's own counters: ratio 2.00 [1.98, 2.02] under push, 1.01 [1.01, 1.02] under DBR (1.00 = exact). The push ratio is not a failure of the law: Little's Law is a steady-state statement, and under push this line's queue in front of the bottleneck grows all run long, so the units completing inside the window entered when the queue was shorter than the window's average WIP implies. Where the line is stable (balanced line, capped buffers, DBR), the ratio sits at 1.00–1.06 in these experiments, and exactly 1 on the fixed-capacity line.

## LLM check — can a model find the bottleneck?

12 line configurations, three ways of answering: *direct* (from the configuration), *code* (the model writes a simulation; its printed answer is scored), and *from data* (from a 50-period process log). Ground truth: 1,000 replications of the simulator per configuration. Accuracy intervals are Wilson intervals over the 12 configurations.

| Model | Mode | Bottleneck accuracy | Throughput MAE | Mean |rel. error| |
|---|---|---|---|---|
| MiniMaxAI/MiniMax-M3.1-Flash | direct | 12/12 = 1.00 [0.76, 1.00] | 0.02 (n=12) | 0.01 |
| MiniMaxAI/MiniMax-M3.1-Flash | code | 12/12 = 1.00 [0.76, 1.00] | 0.10 (n=12) | 0.04 |
| MiniMaxAI/MiniMax-M3.1-Flash | fromdata | 9/12 = 0.75 [0.47, 0.91] | — | — |
| openai/gpt-oss-120b | direct | 12/12 = 1.00 [0.76, 1.00] | 0.05 (n=12) | 0.01 |
| openai/gpt-oss-120b | code | 9/12 = 0.75 [0.47, 0.91] | 0.06 (n=12) | 0.03 |
| openai/gpt-oss-120b | fromdata | 6/12 = 0.50 [0.25, 0.75] | — | — |
| zai-org/GLM-5.3-Flash | direct | 12/12 = 1.00 [0.76, 1.00] | 0.02 (n=12) | 0.01 |
| zai-org/GLM-5.3-Flash | code | 4/12 = 0.33 [0.14, 0.61] | 0.00 (n=4) | 0.00 |
| zai-org/GLM-5.3-Flash | fromdata | 8/12 = 0.67 [0.39, 0.86] | — | — |

Failed calls: 0 of 108. Code-mode programs that failed to run: 8 of 36.


Reading the table: asked directly, all three models name the bottleneck on all 12 configurations and estimate throughput closely — the lowest-mean-capacity rule is easy to state. Code mode separates them. MiniMax's programs run and reproduce the bottleneck on all 12; gpt-oss's programs all run and its simulated throughputs are usually close, but its bottleneck pick is wrong on 3 (its simulation can be right about output and wrong about which station limits it). GLM returns no program at all on 8 of 12 configurations — all of them ones with variable capacities: it spends the entire 16,000-token budget reasoning and the reply is empty. Where its programs do run (the fixed-capacity and simplest lines), they are the most accurate in the table. One shared miss: on the balanced dice line, both other models' written simulations report 3.47–3.49 units per period — near the naive average of 3.5 and above the true 3.29 — so their simulators understate the very dependency loss the dice game is about. Reading a log is the hardest mode for every model (6–9 of 12).

## Spend

| Model | Calls (pilot + main) | Cost |
|---|---|---|
| MiniMaxAI/MiniMax-M3.1-Flash | 66 | $0.211 |
| Qwen/Qwen3.5-9B | 30 | $0.065 |
| deepseek-ai/DeepSeek-V4.1-Flash | 30 | $0.132 |
| mistralai/Mistral-Small-24B-Instruct-2501 | 30 | $0.000 |
| openai/gpt-oss-120b | 66 | $0.070 |
| zai-org/GLM-5.3-Flash | 66 | $0.235 |
| **Total** | **288** | **$0.714** |

Prices: Together list prices on 2026-11-13 (outputs/pricing_snapshot.json); cost computed from returned token usage.

