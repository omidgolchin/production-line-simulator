"""The Bottleneck Finder's analysis layer.

Sits on top of :mod:`linesim.simulate` (the v2 engine, unchanged in
its draw order) and adds what the tool needs:

* ``tool_config`` — build a :class:`LineConfig` from the tool's
  station table (average output per period, coefficient of variation,
  buffer space in front of each station) and a release rule.
* ``analyze_line`` — replicated simulation of a line: throughput with
  an interval, WIP, cycle time, Little's-law ratio, mean buffer in
  front of each station, and the limiting / blocked / starved period
  shares per station.
* ``kingman`` — the Kingman (1961) G/G/1 approximation of the queue
  in front of each station, with variability propagated downstream
  (Whitt's approximation), to sit next to the simulation.
* ``improvement_options`` — paired simulations of "+capacity" and
  "+buffer space" at each station (common random numbers, so the
  gains carry paired intervals).
* ``release_comparison`` — push vs drum-buffer-rope vs CONWIP at a
  matched release pace: the WIP each rule needs.
* ``active_period`` / ``parse_log`` — the active-period bottleneck
  method (Roser, Nakano & Tanaka 2001) for a pasted process log.
* ``verdict`` / ``verdict_data`` — the page's verdict states, decided
  from the analysis numbers only (the page renders the words).

``docs/linesim.js`` mirrors this module; the two are checked against
each other in tests/test_js_agreement.py (die, uniform and fixed
capacities, where the LCG streams agree exactly).
"""

from __future__ import annotations

import math

from .simulate import LCG, LineConfig, StationSpec, simulate

# Two-sided 95% t quantiles for df = 1..40 (same table as the
# staffing planner's engine).
T975 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306,
        2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131, 2.120,
        2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064,
        2.060, 2.056, 2.052, 2.048, 2.045, 2.042, 2.040, 2.037,
        2.035, 2.032, 2.030, 2.028, 2.026, 2.024, 2.023, 2.021]


def _round_half_up(x: float) -> int:
    """Round to the nearest integer, halves away from zero.

    Python's round() is banker's rounding; the JavaScript mirror
    uses Math.round (half up). Every quantity the two implementations
    must agree on goes through this helper instead.
    """
    return math.floor(x + 0.5)


def mean_ci(values):
    """(mean, 95% t-interval half width) of a list of numbers."""
    v = [x for x in values if x is not None and math.isfinite(x)]
    n = len(v)
    if n == 0:
        return (float("nan"), float("nan"))
    m = sum(v) / n
    if n == 1:
        return (m, float("nan"))
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1))
    return (m, T975[min(n - 2, len(T975) - 1)] * sd / math.sqrt(n))


# ------------------------------------------------------------ tool input


def tool_spec(st: dict) -> StationSpec:
    """One row of the tool's station table -> an engine StationSpec."""
    if st.get("die"):
        return StationSpec(kind="die")
    mean = float(st["mean"])
    cv = float(st.get("cv", 0.0))
    if cv <= 0:
        if mean == int(mean):
            return StationSpec(kind="fixed", value=int(mean))
        return StationSpec(kind="normal", mu=mean, sigma=0.0)
    return StationSpec(kind="normal", mu=mean, sigma=cv * mean)


def station_scv(spec: StationSpec) -> float:
    """Squared coefficient of variation of a station's capacity."""
    if spec.kind == "die":
        return (35.0 / 12.0) / 3.5 ** 2
    if spec.kind == "uniform":
        count = spec.hi - spec.lo + 1
        var = (count * count - 1) / 12.0
        return var / spec.mean ** 2 if spec.mean else 0.0
    if spec.kind == "normal":
        return (spec.sigma / spec.mu) ** 2 if spec.mu else 0.0
    return 0.0


def tool_config(tool: dict) -> LineConfig:
    """The tool's inputs (station table + release rule) -> LineConfig."""
    stations = [tool_spec(s) for s in tool["stations"]]
    limits = []
    for s in tool["stations"][1:]:
        b = s.get("buffer")
        limits.append(10 ** 6 if b is None else int(b))
    buffer_limits = None if all(x >= 10 ** 6 for x in limits) else limits
    rel = tool.get("release", {"mode": "push", "rate": 3})
    mode = rel.get("mode", "push")
    if mode == "push":
        release = {"mode": "push", "rate": max(1, _round_half_up(rel["rate"]))}
    elif mode == "dbr":
        means = [s.mean for s in stations]
        release = {"mode": "rope",
                   "bottleneck": means.index(min(means)),
                   "time_buffer": int(rel.get("stock", 10))}
    elif mode == "conwip":
        release = {"mode": "conwip", "wip": max(1, int(rel["wip"]))}
    else:
        release = {"mode": "infinite"}
    return LineConfig(stations=stations, buffer_limits=buffer_limits,
                      release=release)


# ------------------------------------------------------------ analysis


def _run_reps(cfg: LineConfig, reps: int, periods: int, warmup: int,
              seed: int) -> list:
    return [simulate(cfg, periods, LCG(seed + r), warmup=warmup,
                     track=True)
            for r in range(reps)]


def _aggregate(runs: list, n: int) -> dict:
    def col(key):
        return [r[key] for r in runs]

    def share(key):
        return [sum(r[key][i] for r in runs) / len(runs) for i in range(n)]

    th, th_half = mean_ci(col("throughput"))
    wip, wip_half = mean_ci(col("mean_wip"))
    ct, ct_half = mean_ci(col("mean_ct"))
    lr, lr_half = mean_ci(col("littles_ratio"))
    return {
        "throughput": th, "throughput_half": th_half,
        "mean_wip": wip, "mean_wip_half": wip_half,
        "mean_ct": ct, "mean_ct_half": ct_half,
        "littles_ratio": lr, "littles_ratio_half": lr_half,
        "mean_buffers": share("mean_buffers"),
        "limiting_share": share("limiting_share"),
        "blocked_share": share("blocked_share"),
        "starved_share": share("starved_share"),
        "reps": len(runs),
    }


def analyze_line(cfg: LineConfig, reps: int = 24, periods: int = 300,
                 warmup: int = 50, seed: int = 20261113,
                 with_runs: bool = False) -> dict:
    """Replicated analysis of one line configuration."""
    runs = _run_reps(cfg, reps, periods, warmup, seed)
    out = _aggregate(runs, cfg.n)
    out["rep_throughputs"] = [r["throughput"] for r in runs]
    if with_runs:
        out["runs"] = runs
    return out


def capability(cfg: LineConfig, reps: int = 24, periods: int = 300,
               warmup: int = 50, seed: int = 20261113) -> dict:
    """What the line itself can pass: the same line fed from an
    endless supply at station 1 (no release rule holding it back)."""
    fed = LineConfig(stations=cfg.stations,
                     buffer_limits=cfg.buffer_limits,
                     release={"mode": "infinite"})
    return analyze_line(fed, reps=reps, periods=periods,
                        warmup=warmup, seed=seed)


def _station_var(spec: StationSpec) -> float:
    """Variance of a station's per-period capacity draw."""
    if spec.kind == "die":
        return 35.0 / 12.0
    if spec.kind == "uniform":
        count = spec.hi - spec.lo + 1
        return (count * count - 1) / 12.0
    if spec.kind == "normal":
        return spec.sigma ** 2
    return 0.0


def kingman(cfg: LineConfig, throughput: float) -> list:
    """Kingman's approximation of the queue in front of each station.

    Kingman's heavy-traffic form (1961), applied to the line's
    period-aggregated process: the backlog in front of a station is a
    reflected walk whose steps are (arrivals - capacity) per period,
    so queue ~ (Var A + Var C) / (2 * (mean capacity - throughput))
    and the wait in queue is queue / throughput (Little's law).
    Arrival variance propagates downstream with Whitt's approximation
    (departure SCV cd^2 = u^2 cs^2 + (1 - u^2) ca^2). Releases are
    near-deterministic for push and drum-buffer-rope, so Var A at
    station 1 is 0; under CONWIP it is set from the last station's
    departure variability. The classic per-unit form of the formula
    understates queues in this batch-period model by several-fold
    (DECISIONS.md); the heavy-traffic form runs high by roughly a
    fifth to a third at utilizations of 0.9 and up, and converges as
    utilization approaches 1. A station at or over capacity has no
    finite queue: wq and queue come back None.
    """
    specs = cfg.stations
    n = cfg.n
    mode = cfg.release.get("mode", "infinite")
    cs2 = [station_scv(s) for s in specs]
    var_c = [_station_var(s) for s in specs]
    if throughput <= 0:
        return [{"util": 0.0, "wq": 0.0, "queue": 0.0} for _ in specs]
    ca2 = [0.0] * n
    if mode == "conwip":
        ca2[0] = cs2[-1]
    rows = []
    for i, s in enumerate(specs):
        mu = s.mean
        u = throughput / mu if mu > 0 else float("inf")
        if i > 0:
            up = min(rows[i - 1]["util"], 1.0)
            cd2 = up * up * cs2[i - 1] + (1 - up * up) * ca2[i - 1]
            ca2[i] = cd2
        var_a = ca2[i] * throughput ** 2
        if not math.isfinite(u) or mu <= throughput:
            rows.append({"util": u, "wq": None, "queue": None})
        else:
            queue = (var_a + var_c[i]) / (2.0 * (mu - throughput))
            rows.append({"util": u, "wq": queue / throughput,
                         "queue": queue})
    return rows


def _capacity_variant(spec: StationSpec):
    """(delta, new spec) for the '+capacity' improvement at a station.

    The step is +0.5 units per period for dice (the spec's example),
    +1 for the integer families, and +10% (at least 0.5) for a normal
    station, keeping the coefficient of variation where one exists.
    A die becomes a rounded normal with the same CV: a die cannot
    gain half a pip.
    """
    if spec.kind == "die":
        cv = math.sqrt(station_scv(spec))
        mu = spec.mean + 0.5
        return 0.5, StationSpec(kind="normal", mu=mu, sigma=cv * mu)
    if spec.kind == "uniform":
        return 1.0, StationSpec(kind="uniform", lo=spec.lo + 1,
                                hi=spec.hi + 1)
    if spec.kind == "fixed":
        return 1.0, StationSpec(kind="fixed", value=spec.value + 1)
    delta = max(0.5, _round_half_up(0.1 * spec.mu * 10) / 10)
    cv = math.sqrt(station_scv(spec))
    mu = spec.mu + delta
    return delta, StationSpec(kind="normal", mu=mu, sigma=cv * mu)


def improvement_options(cfg: LineConfig, reps: int = 16,
                        periods: int = 300, warmup: int = 50,
                        seed: int = 20261113,
                        base_runs: list | None = None) -> list:
    """Simulated gain of each candidate change, best first.

    Candidates: +capacity at every station; +4 buffer space in front
    of every station that has a finite buffer. All candidates share
    the baseline's seeds (common random numbers), and the interval is
    the paired t-interval of the per-replication throughput gain.
    """
    if base_runs is None:
        base_runs = _run_reps(cfg, reps, periods, warmup, seed)
    base_th = [r["throughput"] for r in base_runs]
    cands = []
    for i, s in enumerate(cfg.stations):
        delta, spec = _capacity_variant(s)
        stations = list(cfg.stations)
        stations[i] = spec
        cands.append({"kind": "capacity", "station": i, "delta": delta,
                      "cfg": LineConfig(stations=stations,
                                        buffer_limits=cfg.buffer_limits,
                                        release=cfg.release)})
    if cfg.buffer_limits is not None:
        for i in range(1, cfg.n):
            if cfg.buffer_limits[i - 1] >= 10 ** 6:
                continue
            add = max(4, _round_half_up(0.5 * cfg.stations[i].mean))
            limits = list(cfg.buffer_limits)
            limits[i - 1] += add
            cands.append({"kind": "buffer", "station": i, "add": add,
                          "cfg": LineConfig(stations=cfg.stations,
                                            buffer_limits=limits,
                                            release=cfg.release)})
    out = []
    for c in cands:
        runs = _run_reps(c["cfg"], reps, periods, warmup, seed)
        gains = [r["throughput"] - b
                 for r, b in zip(runs, base_th)]
        gain, half = mean_ci(gains)
        th, _ = mean_ci([r["throughput"] for r in runs])
        out.append({"kind": c["kind"], "station": c["station"],
                    "delta": c.get("delta"), "add": c.get("add"),
                    "gain": gain, "gain_half": half, "throughput": th})
    out.sort(key=lambda o: -o["gain"])
    return out


def release_comparison(cfg: LineConfig, reps: int = 16,
                       periods: int = 300, warmup: int = 50,
                       seed: int = 20261113, share: float = 0.95) -> list:
    """Push vs drum-buffer-rope vs CONWIP at the same output.

    The target is ``share`` of what the line passes when fed without
    limit. Push releases at exactly that rate; drum-buffer-rope's rope
    and CONWIP's cap are the smallest values on a ladder whose output
    reaches the target (Hopp & Spearman: at equal throughput, a pull
    rule needs less work in process than push when push releases at
    random; a perfectly smooth push at the right rate is push's best
    case). What differs between rules is the work in process and cycle
    time each needs, and how badly each does when its setting is 20%
    too high (``wip_if_high``): push then releases faster than the line
    can work and its queues grow all run, while a pull rule only holds
    a few more units (Hopp & Spearman, *Factory Physics*, ch. 10).
    """
    means = [s.mean for s in cfg.stations]
    b = means.index(min(means))
    fed = capability(cfg, reps=max(6, reps // 2), periods=periods,
                     warmup=warmup, seed=seed)["throughput"]
    target = share * fed

    def variant(release):
        return LineConfig(stations=cfg.stations,
                          buffer_limits=cfg.buffer_limits,
                          release=release)

    def run(release, rps):
        agg = _aggregate(_run_reps(variant(release), rps, periods,
                                   warmup, seed), cfg.n)
        return {"throughput": agg["throughput"],
                "throughput_half": agg["throughput_half"],
                "mean_wip": agg["mean_wip"], "mean_ct": agg["mean_ct"]}

    def reaches(release):
        agg = _aggregate(_run_reps(variant(release), max(6, reps // 2),
                                   periods, warmup, seed), cfg.n)
        return agg["throughput"] >= 0.995 * target

    def smallest(make):
        """Smallest whole setting (1..200) whose output reaches the
        target; bisection, since output does not fall as it grows."""
        lo, hi = 1, 200
        if not reaches(make(hi)):
            return hi
        while lo < hi:
            mid = (lo + hi) // 2
            if reaches(make(mid)):
                hi = mid
            else:
                lo = mid + 1
        return lo

    rate = _round_half_up(target * 100) / 100
    push = run({"mode": "push", "rate": rate}, reps)
    rope = smallest(lambda v: {"mode": "rope", "bottleneck": b,
                               "time_buffer": v})
    dbr = run({"mode": "rope", "bottleneck": b, "time_buffer": rope}, reps)
    cap = smallest(lambda v: {"mode": "conwip", "wip": v})
    conwip = run({"mode": "conwip", "wip": cap}, reps)
    push["wip_if_high"] = run({"mode": "push", "rate": _round_half_up(rate * 120) / 100}, reps)["mean_wip"]
    dbr["wip_if_high"] = run({"mode": "rope", "bottleneck": b, "time_buffer": math.ceil(rope * 1.2)}, reps)["mean_wip"]
    conwip["wip_if_high"] = run({"mode": "conwip", "wip": math.ceil(cap * 1.2)}, reps)["mean_wip"]
    return [
        {"rule": "push", "rate": rate, "target": target, **push},
        {"rule": "dbr", "stock": rope, "target": target, **dbr},
        {"rule": "conwip", "wip": cap, "target": target, **conwip},
    ]


# ------------------------------------------------------------ data mode


_ACTIVE_WORDS = {"active", "working", "busy", "running", "processing",
                 "producing", "up", "true", "yes", "x"}
_INACTIVE_WORDS = {"idle", "starved", "blocked", "down", "off",
                   "stopped", "waiting", "false", "no", "-", ""}


def _split_row(line: str) -> list:
    for delim in (",", ";", "\t"):
        if delim in line:
            return [c.strip() for c in line.split(delim)]
    return line.split()


def _cell(cell: str):
    """One log cell -> (output or None, active bool)."""
    low = cell.strip().lower()
    if low in _ACTIVE_WORDS:
        return None, True
    if low in _INACTIVE_WORDS:
        return None, False
    try:
        v = float(cell)
    except ValueError:
        raise ValueError(f"unrecognized cell: {cell!r}")
    return v, v > 0


def parse_log(text: str):
    """Parse a pasted process log.

    Format: one row per period; columns are stations (a header row
    with station names is optional, as is a leading period column).
    Cells are either outputs per period (numbers; 0 = did not run)
    or states (active / idle / starved / blocked / ...). Returns
    (names, outputs, states): outputs holds floats or None where the
    log gives states only.
    """
    lines = [ln for ln in (ln.strip() for ln in text.splitlines()) if ln]
    if len(lines) < 2:
        raise ValueError("Paste at least a few periods of log.")
    rows = [_split_row(ln) for ln in lines]
    # Header: any cell that is neither a number nor a known state word.
    def is_header(cells):
        for c in cells:
            low = c.strip().lower()
            if low in _ACTIVE_WORDS or low in _INACTIVE_WORDS:
                continue
            try:
                float(c)
            except ValueError:
                return True
        return False

    names = None
    if is_header(rows[0]):
        names = [c if c else f"Station {i + 1}"
                 for i, c in enumerate(rows[0])]
        rows = rows[1:]
    # Leading period column: header says so, or the column is 1..T.
    def drop_first(rs, ns):
        return [r[1:] for r in rs], (ns[1:] if ns else ns)

    if names and names[0].lower() in ("period", "time", "hour", "step",
                                      "t", "#"):
        rows, names = drop_first(rows, names)
    elif rows and all(len(r) >= 3 for r in rows):
        first = [r[0] for r in rows]
        try:
            vals = [float(x) for x in first]
            if vals == list(range(1, len(vals) + 1)):
                rows, names = drop_first(rows, names)
        except ValueError:
            pass
    if not rows or len(rows[0]) < 2:
        raise ValueError("The log needs at least two stations.")
    width = len(rows[0])
    outputs, states = [], []
    bad = 0
    for r in rows:
        if len(r) != width:
            bad += 1
            continue
        orow, srow = [], []
        try:
            for c in r:
                v, a = _cell(c)
                orow.append(v)
                srow.append(a)
        except ValueError:
            bad += 1
            continue
        outputs.append(orow)
        states.append(srow)
    if bad > max(2, len(rows) // 10):
        raise ValueError("Too many rows do not match the log's shape.")
    if len(states) < 5:
        raise ValueError("Too few usable periods in the log.")
    if names is None or len(names) != width:
        names = [f"Station {i + 1}" for i in range(width)]
    return names, outputs, states


def active_period(states: list) -> dict:
    """The active-period method (Roser, Nakano & Tanaka 2001).

    In each period, the station with the longest current unbroken
    run of active periods is the momentary bottleneck (ties split
    the period). Returns per-station bottleneck shares, active
    shares and longest active runs.
    """
    if not states:
        raise ValueError("empty log")
    t_n = len(states)
    n = len(states[0])
    runs = [0] * n
    longest = [0] * n
    active = [0] * n
    shares = [0.0] * n
    by_period = []
    for row in states:
        for i in range(n):
            if row[i]:
                runs[i] += 1
                active[i] += 1
                longest[i] = max(longest[i], runs[i])
            else:
                runs[i] = 0
        top = max(runs)
        tied = [i for i in range(n) if runs[i] == top and top > 0]
        if tied:
            for i in tied:
                shares[i] += 1.0 / len(tied)
            by_period.append(tied[0] if len(tied) == 1 else -1)
        else:
            by_period.append(-1)
    return {
        "periods": t_n,
        "bottleneck_share": [s / t_n for s in shares],
        "active_share": [a / t_n for a in active],
        "longest_active": longest,
        "bottleneck_by_period": by_period,
    }


def analyze_log(text: str) -> dict:
    """parse_log + active_period + per-station output averages."""
    names, outputs, states = parse_log(text)
    ap = active_period(states)
    n = len(names)
    mean_output = []
    for i in range(n):
        vals = [row[i] for row in outputs if row[i] is not None]
        mean_output.append(sum(vals) / len(vals) if vals else None)
    shares = ap["bottleneck_share"]
    top = max(range(n), key=lambda i: shares[i])
    return {"names": names, "mean_output": mean_output, "top": top,
            **ap}


# ------------------------------------------------------------ verdicts


def verdict(summary: dict) -> dict:
    """The analyze-mode verdict state, from the analysis only.

    summary keys: names, means, limiting (per-station shares of
    periods in which the station's own capacity draw bound its flow;
    shares are not exclusive, so the verdict reads the *gaps* between
    them), blocked (shares in which downstream buffer space bound a
    station's flow), th (expected throughput), capability (what the
    line could pass with an endless supply, or None), plan (planned
    output or None), release_mode, push_rate, best_gain,
    best_station, best_kind.

    The buffer rule needs care: every station upstream of a capacity
    bottleneck is blocked whenever the bottleneck's buffer fills, so
    a high blocked share alone is a symptom, not a diagnosis. The
    rule fires only when the priced options agree that space is the
    binding fix, that is, the single best change is more buffer in
    front of the station behind the full buffer.
    """
    means = summary["means"]
    limiting = summary["limiting"]
    top = max(range(len(means)), key=lambda i: limiting[i])
    order = sorted(range(len(means)), key=lambda i: -limiting[i])
    second = order[1] if len(order) > 1 else top
    min_mean = min(means)
    bn = means.index(min_mean)
    facts = {"bottleneck": top, "by_average": bn,
             "second": second}
    for i, m in enumerate(means):
        if m <= 0:
            return {"state": "bad", "reason": "zero", **facts,
                    "bottleneck": i}
    rate = summary.get("push_rate")
    if (summary.get("release_mode") == "push" and rate is not None
            and rate > min_mean + max(0.5, 0.15 * min_mean)):
        return {"state": "bad", "reason": "release", **facts,
                "bottleneck": bn}
    cap = summary.get("capability")
    if (summary.get("release_mode") == "push" and rate is not None
            and cap is not None and rate < min_mean - 1e-9
            and cap - summary["th"] > max(0.05, 0.03 * cap)):
        return {"state": "warn", "reason": "release-limited",
                **facts}
    plan = summary.get("plan")
    if plan is not None and summary["th"] < plan - max(0.05, 0.02 * plan):
        return {"state": "warn", "reason": "plan", **facts}
    blocked = summary.get("blocked") or [0.0] * len(means)
    btop = max(range(len(means)), key=lambda i: blocked[i])
    if (blocked[btop] >= 0.5 and summary.get("best_kind") == "buffer"
            and summary.get("best_station") == btop + 1):
        gain = summary.get("best_gain")
        solid = gain is not None and gain >= max(0.05,
                                                 0.03 * summary["th"])
        return {"state": "good" if solid else "warn",
                "reason": "buffer", **facts,
                "bottleneck": btop + 1, "blocked_station": btop}
    gap_top = limiting[top] - limiting[second]
    gap_all = limiting[top] - min(limiting)
    if gap_top < 0.15 and gap_all < 0.25:
        return {"state": "accent", "reason": "balanced", **facts}
    if gap_top < 0.15:
        return {"state": "warn", "reason": "wandering", **facts}
    gain = summary.get("best_gain")
    if gain is None or gain < max(0.05, 0.03 * summary["th"]):
        return {"state": "warn", "reason": "small-gains", **facts}
    return {"state": "good", "reason": "clear", **facts}


def verdict_data(log: dict) -> dict:
    """The data-mode verdict state, from analyze_log's output."""
    shares = log["bottleneck_share"]
    active = log["active_share"]
    n = len(shares)
    top = max(range(n), key=lambda i: shares[i])
    order = sorted(range(n), key=lambda i: -shares[i])
    second = order[1] if n > 1 else top
    for i, a in enumerate(active):
        if a <= 0:
            return {"state": "bad", "reason": "never-active",
                    "bottleneck": top, "station": i}
    if shares[top] >= 0.5:
        return {"state": "good", "reason": "dominant",
                "bottleneck": top}
    if shares[top] >= 0.3 and shares[second] > shares[top] - 0.10:
        return {"state": "warn", "reason": "wandering",
                "bottleneck": top, "second": second}
    return {"state": "accent", "reason": "wandering-wide",
            "bottleneck": top}
