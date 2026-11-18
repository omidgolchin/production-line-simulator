# Decisions

Choices the spec left open, settled by the spec's decision rules or
the more conservative option, with reasons. (Program rule: log it and
continue; there are no human checkpoints.)

1. **Period mechanics.** Stations act in order 1..N within a period,
   as in the book's game (the players also move in order), so a unit
   can pass several stations in one period. Capacities are drawn for
   all stations at the start of the period. This makes the fixed-
   capacity test exact: output per period equals the minimum station
   capacity from period 1.
2. **Drum-buffer-rope implementation.** The rope releases units into
   station 1 at the bottleneck's mean capacity, using a fractional
   accumulator so a mean of 2.5 releases 2, 3, 2, 3, ... units. The
   buffer is a pre-load of `time_buffer` (10) units in the
   bottleneck's input buffer at period 0. The bottleneck station is
   the one named in the configuration — in a real plant the operator
   knows their constraint; the interesting comparison is WIP and
   cycle time at matched release pace, not bottleneck discovery.
3. **Little's Law accounting.** WIP for a period counts every unit in
   the system during that period (start-of-period WIP plus units that
   entered), and cycle time is stamped per unit (exit − entry + 1).
   With end-of-period snapshots instead, a unit that flows through in
   one period would count as zero WIP and the fixed-line check could
   not come out exact. On the fixed 4×5 line the ratio is exactly 1.
4. **Cross-language agreement.** The JavaScript engine mirrors the
   Python engine with the same Park–Miller LCG (multiplier 48271;
   all arithmetic below 2^53, so JS doubles are exact). Agreement is
   tested on die, uniform and fixed capacities over full per-period
   state. Normal capacities are excluded from the exact-agreement
   test because Box–Muller depends on each platform's libm, which can
   differ in the last bit and flip a rounding; both engines still
   implement them the same way.
5. **P01's `errorbars` module is not used.** It computes intervals
   for accuracy over a set of questions with repeated runs. Here the
   experiment contrasts are paired per-seed differences of simulation
   metrics (paired t-intervals) and the LLM check makes one call per
   configuration (Wilson intervals for accuracy). Different estimands;
   forcing the module in would weaken both. (Program rule says use it
   "wherever a spec asks for error bars over questions or tasks" —
   this spec asks for confidence intervals on simulation contrasts.)
6. **Candidate pool reduced to five families before the pilot.**
   `mistralai/Mistral-Small-24B-Instruct-2501` answered the probe
   call with HTTP 400 (non-serverless on this account, 2026-11-13),
   so it cannot be piloted. The pool is gpt-oss, GLM, MiniMax, Qwen
   and DeepSeek — still five different families.
7. **Bottleneck ground truth is analytic, throughput truth is
   simulated.** The bottleneck of a configuration is the station with
   the lowest mean capacity ("none" when all means are equal) — that
   is a property of the configuration, not something to estimate.
   Throughput truth is the mean of 1,000 simulator replications,
   which is what the models are asked to predict.
8. **From-data logs** come from a single seeded run per configuration
   (seed fixed in config.yaml), with unlimited raw material, showing
   per-station output and the input buffers of stations 2..N. One log
   per configuration keeps the task identical for every model.
9. **Experiment 1's no-variability arm uses fixed capacity 4**, not
   3.5, because units are discrete. The variability loss is measured
   against each variable arm's own mean capacity (3.5 for both dice
   and uniform 3–4), which is the game's comparison: plan said 3.5,
   the line delivers less.
10. **Token budget raised after pilot v1 (design correction, made
    before the freeze).** The first pilot used max_tokens = 4,000
    (inherited from P11, whose answers are short). Every format
    failure in every mode — 18 code-mode and 21 direct/from-data
    answers — was `finish_reason = length` at exactly 4,000 output
    tokens with empty visible text: the reasoning-style models spent
    the whole budget thinking and never emitted an answer. That
    measures the token cap, not the models. max_tokens is now 16,000
    for all modes, applied uniformly; pilot v1 is archived as
    outputs/pilot_runs_v1.jsonl and the pilot was re-run from
    scratch (pilot v2). Pilot v1 spend ($0.13) still counts against
    the cap.
11. **Model selection (pilot v2, 2026-11-13).** Pilot: 5
    configurations × 3 modes per candidate. Code ran in: gpt-oss-120b
    5/5, DeepSeek-V4.1-Flash 5/5, MiniMax-M3.1-Flash 4/5,
    GLM-5.3-Flash 3/5, Qwen3.5-9B 2/5. The rule drops models whose
    code fails in more than half the pilot configurations → Qwen is
    dropped. Mistral never connected (all calls HTTP 400). Of the
    four survivors, the three cheapest by measured pilot cost for the
    same 15 calls are gpt-oss-120b ($0.016), MiniMax-M3.1-Flash
    ($0.048) and GLM-5.3-Flash ($0.059); DeepSeek-V4.1-Flash ($0.081)
    is the most expensive survivor and is not selected. Selected:
    openai/gpt-oss-120b, MiniMaxAI/MiniMax-M3.1-Flash,
    zai-org/GLM-5.3-Flash — three families. Pilot bottleneck hits
    (not a selection criterion, recorded for context): DeepSeek
    14/15, MiniMax 13/15, GLM 11/15, gpt-oss 10/15, Qwen 8/15.

## P12v2 reshape (2026-11-14): the simulator becomes a product

12. **Reshape, engine kept.** Under the tools_v3 program the project
    is now the Production Line Bottleneck Finder: one job (where is
    the bottleneck, what output is real, where does the next dollar
    go), verdict first, no experiments inside the tool. The v2
    engine (items 1–11 above) is unchanged in its draw order and
    kept as the Python reference; the four experiments and the LLM
    check moved to the README's Research notes with their numbers.
13. **CONWIP added to the engine.** The release comparison needs all
    three rules, so simulate() and simulate_counts() gained a CONWIP
    mode: W units are preloaded (stamped period 0) and each exit
    releases one replacement (stamped t+1). Fixed line check: caps
    5/3/4 with W=10 gives throughput exactly 3, mean WIP exactly 10,
    Little's ratio exactly 1.0.
14. **Binding-constraint accounting.** Each simulated period, a
    station is limiting when its own capacity draw was the binding
    limit (capacity strictly below both work available and space
    behind it), blocked when space bound it, starved when supply
    bound it; ties count for nobody, so the shares are not exclusive
    and need not sum to 1. The verdict therefore reads the *gaps*
    between the top shares (clear / wandering / balanced), never
    their levels.
15. **Buffer-cap flow ceiling (engine mechanics, found while
    calibrating examples).** Within a period, inflow to a buffer
    happens before the station behind it drains, so sustained
    per-period flow through a buffer cannot exceed the buffer's
    size: a 40-per-hour line with buffers of 12 capped throughput at
    11.73 with the first station blocked 100% of periods. Tool
    examples and defaults therefore live at single-digit
    units-per-period scale (the spec's own 3.2/3.5 example does
    too), and the buffer improvement step scales with the station's
    mean: max(4, half the mean).
16. **Kingman: heavy-traffic form, territory marked.** The classic
    per-unit Kingman understates queues 2.3–6× in this batch-period
    model (single-station check: 0.069 predicted vs 0.226 simulated;
    the simulated backlog equals a reflected walk on identical draws
    exactly). The tool uses Kingman's heavy-traffic form, queue ≈
    (arrival variance + capacity variance) / (2 × (capacity −
    throughput)), with arrival variability propagated by Whitt's
    departure rule. Measured against simulation at bottleneck
    utilizations 0.85 / 0.88 / 0.95: predicted 1.32× / 1.95× /
    1.45× the simulated queue. At utilization ≥ 0.98 the
    denominator is knife-edge and the estimate explodes (21.5 vs
    3.8 on the default line); the page's check names that case
    instead of quoting the number, and the tests assert the stated
    factor (0.7–2.1) only inside the territory.
17. **The buffer verdict must be priced, not just observed.** The
    first rule (any station blocked ≥ 50% of periods ⇒ buffer
    verdict) fired on ordinary capacity problems, because queues
    back up from a real bottleneck through every buffer in front of
    it: on the default line Cut is blocked 54% of periods and on a
    two-bottleneck line Saw 83%, while the best fix in both cases is
    capacity. The rule now fires only when the best priced change
    is buffer space in front of the station behind the full buffer.
    The starved-bottleneck case it was built for (buffer 2 in front
    of the bottleneck, +buffer worth +1.57 per period) still fires.
18. **Two rounding rules, kept apart.** A JS/Python divergence on a
    zero-variance station at mean 2.5 (JavaScript passed 3 units a
    period, Python 2) traced to capacity draws: Python's round() is
    half-to-even, Math.round is half-up. Capacity draws now round
    half-to-even in both engines. Configuration rounding (release
    pace, push rate, option deltas) is half-up in both, via
    _round_half_up in finder.py and Math.round in linesim.js.
19. **Release comparison construction.** Push and drum-buffer-rope
    both release at the bottleneck's (rounded) mean pace, DBR with
    the protective stock taken from the bottleneck's buffer input;
    the CONWIP cap is found by a ladder (4…100) at half repetitions,
    the first cap reaching 98% of push's throughput, then priced
    with a full run. The comparison's point is work in process at
    matched output, so the table leads with that.
20. **Data mode honesty.** The active-period method reads idle
    time: numeric cells count as active only when positive. A log
    in which every station is active in every period cannot be
    separated, and the page says so instead of guessing. (The v2
    study's dice-game logs are exactly this case; their ground
    truth for the balanced configurations is "no bottleneck", and
    the tool reproduces that reading.) Verdict thresholds for data
    mode: a station never active is an error state; top share
    ≥ 0.5 is dominant; ≥ 0.3 with the runner-up within 0.10 is
    wandering.
21. **Assist test set: fixed key order.** The shared scorer compares
    array fields as JSON strings, so the extraction instructions
    fix the station object's key order (name, output, cv, buffer,
    die) and the test set stores them in that order. Conversions
    the instructions must carry: per-shift and per-day rates divide
    by a stated shift length; batch processes divide batch size by
    hours per batch; a range's midpoint is the output and a stated
    variability word overrides the range-derived cv.
22. **Drum-buffer-rope is a true rope (changed after the study).**
    Decision 2 released at the bottleneck's mean pace, which loads the
    bottleneck at exactly 100% and lets its queue drift upward: on the
    default line the "protected" bottleneck carried 20 units in process
    at 6 periods of cycle time. The tool now uses mode `rope`: work at
    or before the bottleneck is held at the rope length and a unit is
    released only as the bottleneck takes one. The old mode `dbr` is
    kept unchanged because the frozen experiment E4 used it; rerunning
    the experiments after the change reproduces `results/experiments_raw.json`
    and `results/timeseries.json` byte for byte. `src/linesim/simulate.py`
    therefore no longer matches its FREEZE_MANIFEST hash (now
    5dea46ee9f307d5e…); the change only adds the `rope` mode and fractional
    push rates (integer rates behave exactly as before).
23. **Release comparison at a common target, plus a wrong setting
    (replaces 19).** Every rule is set to make 95% of what the line
    passes fed without limit: push at exactly that rate, the rope and
    the CONWIP cap at the smallest whole values that reach it (found by
    bisection). Matching push's output, as decision 19 did, compared a
    rounded push against a rope that released more. A smooth push at
    the right rate is close to the pull rules on work in process; the
    comparison that separates them is the same rules set 20% too high,
    which the table now shows.

## 2026-11-18: what a screen reader announces

- Only the verdict title is announced. The whole verdict panel used to
  be one `aria-live` region, and its KPI tiles and checks are rewritten
  on every run, so a screen reader read them all again after each pause
  in typing. Now the title alone carries `aria-live="polite"` and
  `aria-atomic="true"`: a changed verdict is announced in full, and the
  KPIs and checks stay on the page for the reader to move to. The title
  is written only when its text changes, so an unchanged verdict is not
  read out again.
