"""The production-line simulator.

Model (discrete periods, stations processed in order 1..N each period,
as in the bowl game in *The Goal*, where the players also move in
order):

* Each period, station i draws a capacity c_i from its distribution
  (die 1-6, uniform on integers, rounded normal, or fixed).
* Station i moves ``min(c_i, units in its input buffer, free space in
  the next buffer)`` units to the next station's input buffer; the
  last station moves units out of the system (output).
* Release policies control how raw material enters station 1:
    - ``infinite``: an endless supply in front of station 1 (the
      book's game: "the first boy takes from an endless supply").
    - ``push``: a fixed number of units is released each period.
    - ``dbr`` (drum-buffer-rope): units are released at the mean pace
      of the bottleneck station (the rope), and the bottleneck's input
      buffer starts pre-loaded with ``time_buffer`` units so the
      bottleneck is protected from upstream fluctuations (the buffer).
    - ``conwip``: the total number of units in the line is held at
      ``wip``; a new unit is released into station 1 for every unit
      that leaves the line (stamped with the next period, the first
      period it can be worked on).
* A unit's cycle time is (exit period - entry period + 1). Entry is
  when the unit is released (push/dbr) or first processed by station 1
  (infinite supply). Mean WIP is the time average of the number of
  units in the system during each period, so Little's Law can be
  checked in the simulator's own counters: L = TH x CT.

Two random-number backends expose the same interface:

* ``NumpyRNG`` (numpy PCG64) — used for the published experiments.
* ``LCG`` — a Park-Miller generator implemented identically in the
  JavaScript engine (``docs/engine.js``), so the Python and JavaScript
  simulators agree exactly on fixed seeds for the die, uniform and
  fixed distributions. (Normal capacities use each platform's libm and
  are excluded from the cross-language check; see DECISIONS.md.)
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

# ---------------------------------------------------------------- RNGs


class LCG:
    """Park-Miller minimal standard generator: x <- 48271 x mod (2^31-1).

    All arithmetic stays below 2^53, so JavaScript doubles reproduce it
    exactly.
    """

    MOD = 2147483647
    MULT = 48271

    def __init__(self, seed: int):
        s = int(seed) % self.MOD
        self.state = s if s > 0 else 1
        self._spare: float | None = None

    def u(self) -> float:
        self.state = (self.MULT * self.state) % self.MOD
        return self.state / self.MOD

    def die(self) -> int:
        return int(self.u() * 6) + 1

    def randint(self, lo: int, hi: int) -> int:
        return lo + int(self.u() * (hi - lo + 1))

    def normal(self, mu: float, sigma: float) -> float:
        if self._spare is not None:
            z, self._spare = self._spare, None
            return mu + sigma * z
        u1 = max(self.u(), 1e-12)
        u2 = self.u()
        r = math.sqrt(-2.0 * math.log(u1))
        self._spare = r * math.sin(2.0 * math.pi * u2)
        return mu + sigma * r * math.cos(2.0 * math.pi * u2)


class NumpyRNG:
    """numpy-backed RNG with the same interface as :class:`LCG`."""

    def __init__(self, seed: int):
        self._g = np.random.default_rng(int(seed))

    def u(self) -> float:
        return float(self._g.random())

    def die(self) -> int:
        return int(self._g.integers(1, 7))

    def randint(self, lo: int, hi: int) -> int:
        return int(self._g.integers(lo, hi + 1))

    def normal(self, mu: float, sigma: float) -> float:
        return float(self._g.normal(mu, sigma))


# ------------------------------------------------------------- stations


@dataclass(frozen=True)
class StationSpec:
    """Capacity distribution of one station.

    kind: "die" (uniform 1..6), "uniform" (integers lo..hi),
    "normal" (rounded normal, floored at 0), or "fixed".
    """

    kind: str
    lo: int = 1
    hi: int = 6
    mu: float = 0.0
    sigma: float = 0.0
    value: int = 0

    @property
    def mean(self) -> float:
        if self.kind == "die":
            return 3.5
        if self.kind == "uniform":
            return (self.lo + self.hi) / 2.0
        if self.kind == "normal":
            return self.mu
        if self.kind == "fixed":
            return float(self.value)
        raise ValueError(f"unknown station kind: {self.kind}")

    def draw(self, rng) -> int:
        if self.kind == "die":
            return rng.die()
        if self.kind == "uniform":
            return rng.randint(self.lo, self.hi)
        if self.kind == "normal":
            return max(0, int(round(rng.normal(self.mu, self.sigma))))
        if self.kind == "fixed":
            return self.value
        raise ValueError(f"unknown station kind: {self.kind}")

    def describe(self) -> str:
        if self.kind == "die":
            return "die roll (uniform 1-6, mean 3.5)"
        if self.kind == "uniform":
            return f"uniform {self.lo}-{self.hi} (mean {self.mean:g})"
        if self.kind == "normal":
            return f"normal mean {self.mu:g}, sd {self.sigma:g}, rounded, min 0"
        if self.kind == "fixed":
            return f"fixed {self.value}"
        return self.kind

    @classmethod
    def from_dict(cls, d: dict) -> "StationSpec":
        return cls(
            kind=d["kind"],
            lo=int(d.get("lo", 1)),
            hi=int(d.get("hi", 6)),
            mu=float(d.get("mu", 0.0)),
            sigma=float(d.get("sigma", 0.0)),
            value=int(d.get("value", 0)),
        )

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "lo": self.lo,
            "hi": self.hi,
            "mu": self.mu,
            "sigma": self.sigma,
            "value": self.value,
        }


# ---------------------------------------------------------------- line


@dataclass
class LineConfig:
    """A full line configuration.

    stations: list of StationSpec, length N.
    buffer_limits: None (unlimited) or a list of length N-1 giving the
        maximum size of the input buffer of stations 2..N. A station
        that cannot move a unit because the next buffer is full keeps
        it (blocking).
    release: dict, one of
        {"mode": "infinite"}
        {"mode": "push", "rate": R}
        {"mode": "dbr", "bottleneck": b (0-based), "time_buffer": TB}
        {"mode": "conwip", "wip": W}
    """

    stations: list
    buffer_limits: list | None = None
    release: dict = field(default_factory=lambda: {"mode": "infinite"})

    @property
    def n(self) -> int:
        return len(self.stations)

    def bottleneck_index(self) -> int | None:
        """Station with the lowest mean capacity; None if all equal."""
        means = [s.mean for s in self.stations]
        m = min(means)
        if all(abs(x - m) < 1e-12 for x in means):
            return None
        return means.index(m)

    @classmethod
    def from_dict(cls, d: dict) -> "LineConfig":
        return cls(
            stations=[StationSpec.from_dict(s) for s in d["stations"]],
            buffer_limits=d.get("buffer_limits"),
            release=d.get("release", {"mode": "infinite"}),
        )

    def to_dict(self) -> dict:
        return {
            "stations": [s.to_dict() for s in self.stations],
            "buffer_limits": self.buffer_limits,
            "release": self.release,
        }


# ------------------------------------------------------------ simulate


def simulate_counts(cfg: LineConfig, periods: int, rng,
                    warmup: int = 0) -> dict:
    """Throughput-only fast path: buffers as integer counts.

    Draws capacities in exactly the same order as :func:`simulate`,
    so for the same seed the throughput is identical; only the
    per-unit bookkeeping (cycle times, WIP) is skipped. Used for the
    1,000-replication ground truth, where those are not needed.
    """
    n = cfg.n
    buffers = [0] * n
    mode = cfg.release.get("mode", "infinite")
    rope_rate = 0.0
    rope_acc = 0.0
    if mode == "dbr":
        b = int(cfg.release["bottleneck"])
        rope_rate = cfg.stations[b].mean
        buffers[b] += int(cfg.release.get("time_buffer", 0))
    elif mode == "conwip":
        buffers[0] += int(cfg.release["wip"])
    total_out = 0
    for t in range(1, periods + 1):
        caps = [s.draw(rng) for s in cfg.stations]
        if mode == "push":
            buffers[0] += int(cfg.release["rate"])
        elif mode == "dbr":
            rope_acc += rope_rate
            r = int(rope_acc)
            rope_acc -= r
            buffers[0] += r
        out_t = 0
        for i in range(n):
            avail = math.inf if (i == 0 and mode == "infinite") \
                else buffers[i]
            if i < n - 1:
                space = (cfg.buffer_limits[i] - buffers[i + 1]
                         if cfg.buffer_limits is not None else math.inf)
            else:
                space = math.inf
            k = int(min(caps[i], avail, space))
            if k > 0:
                if not (i == 0 and mode == "infinite"):
                    buffers[i] -= k
                if i < n - 1:
                    buffers[i + 1] += k
                else:
                    out_t = k
        if mode == "conwip":
            buffers[0] += out_t
        if t > warmup:
            total_out += out_t
    window = periods - warmup
    return {"output": total_out,
            "throughput": total_out / window if window > 0 else 0.0}


def simulate(cfg: LineConfig, periods: int, rng, warmup: int = 0,
             record: bool = False, track: bool = False) -> dict:
    """Run one replication.

    Returns a dict with totals over the measurement window (periods
    after ``warmup``): ``output`` (units), ``throughput`` (units per
    period), ``mean_wip``, ``mean_ct`` (mean cycle time of units that
    exited inside the window), ``littles_ratio`` =
    mean_wip / (throughput x mean_ct), and, if ``record``, per-period
    series: ``series_output``, ``series_wip`` (end-of-period WIP),
    ``series_buffers`` (end-of-period input buffers of stations 2..N),
    ``series_station_output`` (per-station units moved per period).

    With ``track=True`` the result also carries ``mean_buffers``
    (time-average end-of-period content of every station's input
    buffer, station 1 included) and three per-station period shares
    over the measurement window: ``limiting_share`` (the station's own
    capacity draw was the binding constraint on how much it moved),
    ``blocked_share`` (downstream buffer space was the binding
    constraint) and ``starved_share`` (lack of input was). Tracking
    draws no random numbers, so tracked and untracked runs agree.
    """
    n = cfg.n
    buffers: list[deque] = [deque() for _ in range(n)]  # input buffers
    mode = cfg.release.get("mode", "infinite")

    rope_rate = 0.0
    rope_acc = 0.0
    if mode == "dbr":
        b = int(cfg.release["bottleneck"])
        rope_rate = cfg.stations[b].mean
        tb = int(cfg.release.get("time_buffer", 0))
        for _ in range(tb):
            buffers[b].append(0)  # pre-loaded at period 0
    elif mode == "conwip":
        for _ in range(int(cfg.release["wip"])):
            buffers[0].append(0)  # the line starts full: W units

    total_out = 0
    wip_area = 0.0
    ct_sum = 0.0
    ct_count = 0
    wip_end_prev = sum(len(b) for b in buffers)
    buffer_sums = [0] * n
    limiting = [0] * n
    blocked = [0] * n
    starved = [0] * n

    series_output: list[int] = []
    series_wip: list[int] = []
    series_buffers: list[list[int]] = []
    series_station_output: list[list[int]] = []
    series_caps: list[list[int]] = []

    for t in range(1, periods + 1):
        caps = [s.draw(rng) for s in cfg.stations]

        # --- release into station 1's input buffer
        entered = 0
        if mode == "push":
            r = int(cfg.release["rate"])
            for _ in range(r):
                buffers[0].append(t)
            entered = r
        elif mode == "dbr":
            rope_acc += rope_rate
            r = int(rope_acc)
            rope_acc -= r
            for _ in range(r):
                buffers[0].append(t)
            entered = r

        # --- stations in order
        moved = [0] * n
        for i in range(n):
            if i == 0 and mode == "infinite":
                avail = math.inf
            else:
                avail = len(buffers[i])
            if i < n - 1:
                if cfg.buffer_limits is not None:
                    space = cfg.buffer_limits[i] - len(buffers[i + 1])
                else:
                    space = math.inf
            else:
                space = math.inf
            k = int(min(caps[i], avail, space))
            if track and t > warmup:
                if k == caps[i] and caps[i] < avail and caps[i] < space:
                    limiting[i] += 1
                elif k == space and space < caps[i] and space < avail:
                    blocked[i] += 1
                elif k == avail and avail < caps[i] and avail < space:
                    starved[i] += 1
            if k > 0:
                if i == 0 and mode == "infinite":
                    entries = [t] * k
                else:
                    entries = [buffers[i].popleft() for _ in range(k)]
                if i < n - 1:
                    buffers[i + 1].extend(entries)
                else:
                    if t > warmup:
                        for e in entries:
                            ct_sum += (t - e + 1)
                        ct_count += k
                moved[i] = k

        out_t = moved[n - 1]
        if mode == "conwip":
            # One replacement per exit, stamped with the next period:
            # the first period it counts toward WIP and can be worked.
            for _ in range(out_t):
                buffers[0].append(t + 1)
        wip_during = wip_end_prev + (entered if mode != "infinite"
                                     else moved[0])
        wip_end = wip_during - out_t
        if mode == "conwip":
            wip_end = wip_during  # replacements restore the count
        if t > warmup:
            total_out += out_t
            wip_area += wip_during
            if track:
                for i in range(n):
                    buffer_sums[i] += len(buffers[i])
        wip_end_prev = wip_end

        if record:
            series_output.append(out_t)
            series_wip.append(wip_end)
            series_buffers.append([len(buffers[i]) for i in range(1, n)])
            series_station_output.append(list(moved))
            series_caps.append(list(caps))

    window = periods - warmup
    throughput = total_out / window if window > 0 else 0.0
    mean_wip = wip_area / window if window > 0 else 0.0
    mean_ct = ct_sum / ct_count if ct_count > 0 else float("nan")
    littles = (mean_wip / (throughput * mean_ct)
               if throughput > 0 and ct_count > 0 else float("nan"))

    result = {
        "output": total_out,
        "throughput": throughput,
        "mean_wip": mean_wip,
        "mean_ct": mean_ct,
        "littles_ratio": littles,
        "completed": ct_count,
    }
    if track:
        result["mean_buffers"] = [s / window if window > 0 else 0.0
                                  for s in buffer_sums]
        result["limiting_share"] = [c / window if window > 0 else 0.0
                                    for c in limiting]
        result["blocked_share"] = [c / window if window > 0 else 0.0
                                   for c in blocked]
        result["starved_share"] = [c / window if window > 0 else 0.0
                                   for c in starved]
    if record:
        result["series_output"] = series_output
        result["series_wip"] = series_wip
        result["series_buffers"] = series_buffers
        result["series_station_output"] = series_station_output
        result["series_caps"] = series_caps
    return result
