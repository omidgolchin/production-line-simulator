# Plan — P12 production-line-simulator

```text
PROJECT: P12 production-line-simulator
STATUS IN ONE LINE: The dice game from Goldratt's The Goal turned into a production-line simulator: variability, dependent stations, bottlenecks and work-in-progress; plus a test of whether an LLM can find the bottleneck.
CV CLUSTER: C (manufacturing and operations).
DECISION NEEDED FROM OMID: none.
DEFINITION CHECKLIST:
  [x] Research question: why does a balanced line with variability lose output, and where should you add capacity?
  [x] Basis: The Goal's dice game; Little's Law; the basic factory-physics relations between throughput, WIP and cycle time.
  [x] Method: (1) simulator of an N-station line with random capacity per period and buffers; (2) experiments on balance, variability, buffers and release policy; (3) playground; (4) LLM check.
  [x] Key figure: throughput and WIP over time for a balanced line vs a line with a protected bottleneck.
  [x] Limitations: a serial line, discrete periods, stylised capacities.
  [x] Done: simulator, experiments in results/summary.md, playground, LLM check.
BUDGET / LIMITS: $4 of model calls.
OPEN QUESTIONS: none.
```

## Question

Why does a balanced line with variability lose output, where should
you add capacity — and can a large language model find a line's
bottleneck: from the configuration, by writing its own simulation, or
by reading a process log?

## Related work and what is different

The dice game itself is Chapter 14's match-and-bowl game in *The
Goal* (the hike and Herbie episodes make the same point about
dependent events). It is widely replayed in teaching: Washington
State University publishes dice games for teaching the Theory of
Constraints, and interactive replays exist (e.g. the replay on
richard-brooks.com, which plays 20 rounds of the five-station game).
Commercial TOC software (such as the MICSS simulator bundled with
Schragenheim & Dettmer's *Manufacturing at Warp Speed*) simulates
whole firms. What I did not find is a version that (a) treats the
game as a measurement instrument — replicated, paired experiments
with confidence intervals on the classic contrasts (variability,
buffers, capacity placement, push vs drum-buffer-rope), with Little's
Law checked in the simulator's own counters — and (b) uses the
simulator as ground truth to test whether LLMs can identify a
bottleneck three different ways. That is the gap this repo fills,
framed as a learning project, not a research claim.

## Design

### Simulator (frozen semantics; DECISIONS.md #1–#4)

Discrete periods; stations act in order 1..N each period; a station
moves min(capacity, input buffer, downstream space); capacities are
die (1–6), uniform integers, rounded normal, or fixed. Release
policies: endless supply (the book's game), push at a fixed rate, and
drum-buffer-rope (release at the bottleneck's mean pace; the
bottleneck's input buffer pre-loaded with a time buffer). Cycle time
is stamped per unit; WIP counts units in the system during each
period, so Little's Law can be checked exactly.

### Experiments (config.yaml `experiments`; 48 paired replications,
250 periods, 50 warm-up; paired t-intervals on per-seed contrasts)

1. Balanced line: fixed capacity 4 vs dice vs uniform 3–4. Headline:
   throughput of the dice line against its own mean capacity, 3.5.
2. Buffer caps (unlimited / 10 / 4 / 2) on the dice line: throughput
   and WIP.
3. Bottleneck line (station 3 mean 2.5, others 3.5): +1 mean capacity
   at the bottleneck vs +1 at station 1.
4. Push (5/period) vs drum-buffer-rope on the bottleneck line:
   throughput, WIP, cycle time, Little's Law ratio per arm.

Key figure: mean cumulative output vs plan and mean WIP over 250
periods, balanced dice line vs the DBR-protected bottleneck line
(200 replications).

### LLM check (config.yaml `llm_check`)

12 configurations (balanced lines with no bottleneck; bottlenecks
first/middle/last; fixed, uniform, die and normal capacities; 3–7
stations; one configuration with two slow stations). Ground truth:
bottleneck = lowest mean capacity ("none" if all equal); throughput
= mean of 1,000 replications (300 periods, 50 warm-up).

Each selected model answers each configuration three ways:
- **Direct:** name the bottleneck and estimate throughput from the
  configuration text.
- **Code:** write a simulation in Python; it is run in a sandbox
  (60 s, no network); its printed answer is scored.
- **From data:** name the bottleneck from a 50-period log of
  per-station outputs and buffer levels (one seeded run per
  configuration).

Scoring: bottleneck exact-match accuracy (Wilson interval over the
12 configurations); throughput absolute and relative error (direct
and code modes). Temperature 0.7, max 16,000 tokens, one call per
(model, configuration, mode), seed derived from the run ID. Every
call is recorded with model returned, usage, latency and raw text.
(The token budget was raised from 4,000 before the freeze: in pilot
v1 every format failure was a reasoning model truncated at 4,000
tokens — DECISIONS.md #10. Pilot v1 is archived, not scored.)

Model selection (rule from the P11 spec, applied to the pilot):
candidates from different families are piloted on 5 configurations
(C01, C02, C05, C07, C10); drop any whose code fails to run in more
than half of the 5; from the rest, take the three cheapest models
from three different families that answer in the required format.
Probe result (2026-11-13): five of six candidates answered
serverless; Mistral-Small-24B-Instruct-2501 returned HTTP 400
(non-serverless) and left the pool before the pilot (DECISIONS.md
#6). Selected models are pinned in config.yaml before the freeze.

Selected models (pilot v2, rule applied in DECISIONS.md #11):
`openai/gpt-oss-120b`, `MiniMaxAI/MiniMax-M3.1-Flash`,
`zai-org/GLM-5.3-Flash`.

## References (verified 2026-11-13)

- Goldratt, E. M., & Cox, J. (1984). *The Goal: A Process of
  Ongoing Improvement*. North River Press. (Revised editions 1986,
  1992, 2004; 4th revised/30th-anniversary edition 2014.) The dice
  game with matches and bowls is in the hike chapters; five
  stations, one die each, 20 rounds, expected 3.5 per round.
  https://en.wikipedia.org/wiki/The_Goal_(book)
- Hopp, W. J., & Spearman, M. L. (2011). *Factory Physics* (3rd
  ed.). Waveland Press. Little's Law, critical WIP, and the
  variability laws used to frame Experiments 1–4.
- Schragenheim, E., & Dettmer, H. W. (2001). *Manufacturing at Warp
  Speed: Optimizing Supply Chain Financial Performance*. St. Lucie
  Press. ISBN 9781574442939. Source for (simplified)
  drum-buffer-rope as implemented in Experiment 4; see also Cox &
  Schleier (eds.), *Theory of Constraints Handbook*, McGraw-Hill,
  2010, ch. 9.

## Amendment log

(Freezes before the main runs. Any change after the freeze is logged
here with "Outputs seen? Yes/No".)

- 2026-11-13, after the experiment runs: `src/linesim/analyze.py`
  gained one interpretive paragraph in the Experiment 4 section
  explaining why the push arm's Little's Law ratio exceeds 1 (the
  line is not in steady state under push; the law's premise fails,
  not the counters). No numbers, code paths, or designs changed.
  Outputs seen? Yes (the experiment table). Manifest re-frozen.
- 2026-11-13, after the LLM-check runs: `src/linesim/analyze.py`
  LLM table cells now show the n behind each throughput MAE (GLM's
  code-mode MAE covers only the 4 configurations where it returned
  a program), and the section gained one interpretive paragraph
  (direct mode is easy for all three models; code mode separates
  them; GLM's 8 missing programs were 16,000-token reasoning
  truncations with empty replies). No numbers changed. Outputs
  seen? Yes (the LLM table). Manifest re-frozen.
