/* linesim.js: the production-line engine and the Bottleneck Finder's
 * analysis layer, in JavaScript.
 *
 * A mirror of src/linesim/simulate.py and src/linesim/finder.py:
 * same period mechanics (capacities drawn for all stations first,
 * then release, then stations act in order), same Park-Miller LCG,
 * same analysis. The two implementations agree exactly on fixed
 * seeds for the die, uniform and fixed distributions (tested in
 * tests/test_js_agreement.py). Normal capacities use each platform's
 * libm and are excluded from the exact-agreement check.
 *
 * Loadable from Node (module.exports) and from the page (window).
 */
(function (g) {
  "use strict";

  /* ---------------- RNG ---------------- */
  function LCG(seed) {
    var s = Math.trunc(seed) % 2147483647;
    this.state = s > 0 ? s : 1;
    this._spare = null;
  }
  LCG.prototype.u = function () {
    this.state = (48271 * this.state) % 2147483647;
    return this.state / 2147483647;
  };
  LCG.prototype.die = function () { return Math.floor(this.u() * 6) + 1; };
  LCG.prototype.randint = function (lo, hi) { return lo + Math.floor(this.u() * (hi - lo + 1)); };
  LCG.prototype.normal = function (mu, sigma) {
    if (this._spare !== null) { var z = this._spare; this._spare = null; return mu + sigma * z; }
    var u1 = Math.max(this.u(), 1e-12), u2 = this.u();
    var r = Math.sqrt(-2.0 * Math.log(u1));
    this._spare = r * Math.sin(2.0 * Math.PI * u2);
    return mu + sigma * r * Math.cos(2.0 * Math.PI * u2);
  };

  /* ---------------- stations ---------------- */
  function stationMean(s) {
    if (s.kind === "die") return 3.5;
    if (s.kind === "uniform") return (s.lo + s.hi) / 2.0;
    if (s.kind === "normal") return s.mu;
    if (s.kind === "fixed") return s.value;
    throw new Error("unknown station kind: " + s.kind);
  }
  /* Python's round() is banker's rounding (half to even); the Python
     engine rounds normal capacity draws with it, so the mirror must
     too. (Configuration rounding elsewhere, pace and option deltas,
     is half-up in both implementations.) */
  function roundHalfEven(x) {
    var f = Math.floor(x), d = x - f;
    if (d > 0.5) return f + 1;
    if (d < 0.5) return f;
    return Math.abs(f % 2) === 1 ? f + 1 : f;
  }
  function stationDraw(s, rng) {
    if (s.kind === "die") return rng.die();
    if (s.kind === "uniform") return rng.randint(s.lo, s.hi);
    if (s.kind === "normal") return Math.max(0, roundHalfEven(rng.normal(s.mu, s.sigma)));
    if (s.kind === "fixed") return s.value;
    throw new Error("unknown station kind: " + s.kind);
  }
  function stationScv(s) {
    if (s.kind === "die") return (35.0 / 12.0) / (3.5 * 3.5);
    if (s.kind === "uniform") {
      var count = s.hi - s.lo + 1, mean = stationMean(s);
      return mean ? ((count * count - 1) / 12.0) / (mean * mean) : 0;
    }
    if (s.kind === "normal") return s.mu ? (s.sigma / s.mu) * (s.sigma / s.mu) : 0;
    return 0;
  }
  function stationVar(s) {
    if (s.kind === "die") return 35.0 / 12.0;
    if (s.kind === "uniform") { var c = s.hi - s.lo + 1; return (c * c - 1) / 12.0; }
    if (s.kind === "normal") return s.sigma * s.sigma;
    return 0;
  }

  /* ---------------- simulate ----------------
   * cfg: {stations: [...], buffer_limits: null | [..], release: {...}}
   * opts: {warmup, record, track}. Mirrors Python simulate(). */
  function simulateLine(cfg, periods, rng, opts) {
    opts = opts || {};
    var warmup = opts.warmup || 0, record = !!opts.record, track = !!opts.track;
    var n = cfg.stations.length;
    var buffers = []; for (var b0 = 0; b0 < n; b0++) buffers.push([]);
    var mode = (cfg.release && cfg.release.mode) || "infinite";
    var ropeRate = 0, ropeAcc = 0;
    if (mode === "dbr") {
      var b = cfg.release.bottleneck;
      ropeRate = stationMean(cfg.stations[b]);
      var tb = cfg.release.time_buffer || 0;
      for (var p = 0; p < tb; p++) buffers[b].push(0);
    } else if (mode === "rope") {
      /* drum-buffer-rope: release tied to the bottleneck's consumption */
      var rb = cfg.release.bottleneck, rtb = Math.trunc(cfg.release.time_buffer || 0);
      for (var rp = 0; rp < rtb; rp++) buffers[rb].push(0);
    } else if (mode === "conwip") {
      var W = Math.trunc(cfg.release.wip);
      for (var w0 = 0; w0 < W; w0++) buffers[0].push(0);
    }
    var totalOut = 0, wipArea = 0, ctSum = 0, ctCount = 0;
    var wipEndPrev = buffers.reduce(function (a, x) { return a + x.length; }, 0);
    var bufferSums = new Array(n).fill(0);
    var limiting = new Array(n).fill(0), blocked = new Array(n).fill(0), starved = new Array(n).fill(0);
    var seriesOutput = [], seriesWip = [], seriesBuffers = [], seriesStationOutput = [], seriesCaps = [];

    for (var t = 1; t <= periods; t++) {
      var caps = cfg.stations.map(function (s) { return stationDraw(s, rng); });
      var entered = 0;
      if (mode === "push") {
        ropeAcc += Number(cfg.release.rate); /* fractional rates */
        var r1 = Math.trunc(ropeAcc);
        ropeAcc -= r1;
        for (var q = 0; q < r1; q++) buffers[0].push(t);
        entered = r1;
      } else if (mode === "rope") {
        var seg = 0;
        for (var sj = 0; sj <= cfg.release.bottleneck; sj++) seg += buffers[sj].length;
        var r3 = Math.max(0, Math.trunc(cfg.release.time_buffer || 0) - seg);
        for (var q3 = 0; q3 < r3; q3++) buffers[0].push(t);
        entered = r3;
      } else if (mode === "dbr") {
        ropeAcc += ropeRate;
        var r2 = Math.floor(ropeAcc);
        ropeAcc -= r2;
        for (var q2 = 0; q2 < r2; q2++) buffers[0].push(t);
        entered = r2;
      }
      var moved = new Array(n).fill(0);
      for (var i = 0; i < n; i++) {
        var avail = (i === 0 && mode === "infinite") ? Infinity : buffers[i].length;
        var space = Infinity;
        if (i < n - 1 && cfg.buffer_limits) space = cfg.buffer_limits[i] - buffers[i + 1].length;
        var k = Math.min(caps[i], avail, space);
        if (track && t > warmup) {
          if (k === caps[i] && caps[i] < avail && caps[i] < space) limiting[i]++;
          else if (k === space && space < caps[i] && space < avail) blocked[i]++;
          else if (k === avail && avail < caps[i] && avail < space) starved[i]++;
        }
        if (k > 0) {
          var entries;
          if (i === 0 && mode === "infinite") { entries = new Array(k).fill(t); }
          else entries = buffers[i].splice(0, k);
          if (i < n - 1) { for (var e = 0; e < entries.length; e++) buffers[i + 1].push(entries[e]); }
          else if (t > warmup) { for (var e2 = 0; e2 < entries.length; e2++) ctSum += (t - entries[e2] + 1); ctCount += k; }
          moved[i] = k;
        }
      }
      var outT = moved[n - 1];
      if (mode === "conwip") { for (var c0 = 0; c0 < outT; c0++) buffers[0].push(t + 1); }
      var wipDuring = wipEndPrev + (mode !== "infinite" ? entered : moved[0]);
      var wipEnd = wipDuring - outT;
      if (mode === "conwip") wipEnd = wipDuring;
      if (t > warmup) {
        totalOut += outT; wipArea += wipDuring;
        if (track) for (var j = 0; j < n; j++) bufferSums[j] += buffers[j].length;
      }
      wipEndPrev = wipEnd;
      if (record) {
        seriesOutput.push(outT);
        seriesWip.push(wipEnd);
        seriesBuffers.push(buffers.slice(1).map(function (x) { return x.length; }));
        seriesStationOutput.push(moved.slice());
        seriesCaps.push(caps.slice());
      }
    }
    var window = periods - warmup;
    var throughput = window > 0 ? totalOut / window : 0;
    var meanWip = window > 0 ? wipArea / window : 0;
    var meanCt = ctCount > 0 ? ctSum / ctCount : NaN;
    var result = {
      output: totalOut, throughput: throughput, mean_wip: meanWip, mean_ct: meanCt,
      littles_ratio: (throughput > 0 && ctCount > 0) ? meanWip / (throughput * meanCt) : NaN,
      completed: ctCount
    };
    if (track) {
      result.mean_buffers = bufferSums.map(function (s) { return window > 0 ? s / window : 0; });
      result.limiting_share = limiting.map(function (c) { return window > 0 ? c / window : 0; });
      result.blocked_share = blocked.map(function (c) { return window > 0 ? c / window : 0; });
      result.starved_share = starved.map(function (c) { return window > 0 ? c / window : 0; });
    }
    if (record) {
      result.series_output = seriesOutput;
      result.series_wip = seriesWip;
      result.series_buffers = seriesBuffers;
      result.series_station_output = seriesStationOutput;
      result.series_caps = seriesCaps;
    }
    return result;
  }

  /* ---------------- stats ---------------- */
  var T975 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306,
    2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131, 2.120,
    2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064,
    2.060, 2.056, 2.052, 2.048, 2.045, 2.042, 2.040, 2.037,
    2.035, 2.032, 2.030, 2.028, 2.026, 2.024, 2.023, 2.021];
  function meanCi(values) {
    var v = values.filter(function (x) { return x !== null && isFinite(x); });
    var n = v.length;
    if (n === 0) return [NaN, NaN];
    var m = v.reduce(function (a, x) { return a + x; }, 0) / n;
    if (n === 1) return [m, NaN];
    var sd = Math.sqrt(v.reduce(function (a, x) { return a + (x - m) * (x - m); }, 0) / (n - 1));
    return [m, T975[Math.min(n - 2, T975.length - 1)] * sd / Math.sqrt(n)];
  }

  /* ---------------- tool input ---------------- */
  function toolSpec(st) {
    if (st.die) return { kind: "die", lo: 1, hi: 6, mu: 0, sigma: 0, value: 0 };
    var mean = Number(st.mean), cv = Number(st.cv || 0);
    if (cv <= 0) {
      if (mean === Math.trunc(mean)) return { kind: "fixed", lo: 1, hi: 6, mu: 0, sigma: 0, value: Math.trunc(mean) };
      return { kind: "normal", lo: 1, hi: 6, mu: mean, sigma: 0, value: 0 };
    }
    return { kind: "normal", lo: 1, hi: 6, mu: mean, sigma: cv * mean, value: 0 };
  }
  function toolConfig(tool) {
    var stations = tool.stations.map(toolSpec);
    var limits = tool.stations.slice(1).map(function (s) { return s.buffer === null || s.buffer === undefined ? 1000000 : Math.trunc(s.buffer); });
    var bufferLimits = limits.every(function (x) { return x >= 1000000; }) ? null : limits;
    var rel = tool.release || { mode: "push", rate: 3 };
    var release;
    if (rel.mode === "push") release = { mode: "push", rate: Math.max(1, Math.round(rel.rate)) };
    else if (rel.mode === "dbr") {
      var means = stations.map(stationMean);
      release = { mode: "rope", bottleneck: means.indexOf(Math.min.apply(null, means)), time_buffer: Math.trunc(rel.stock == null ? 10 : rel.stock) };
    } else if (rel.mode === "conwip") release = { mode: "conwip", wip: Math.max(1, Math.trunc(rel.wip)) };
    else release = { mode: "infinite" };
    return { stations: stations, buffer_limits: bufferLimits, release: release };
  }

  /* ---------------- analysis ---------------- */
  function runReps(cfg, reps, periods, warmup, seed) {
    var out = [];
    for (var r = 0; r < reps; r++) out.push(simulateLine(cfg, periods, new LCG(seed + r), { warmup: warmup, track: true }));
    return out;
  }
  function aggregate(runs, n) {
    function col(key) { return runs.map(function (r) { return r[key]; }); }
    function share(key) {
      var out = [];
      for (var i = 0; i < n; i++) out.push(runs.reduce(function (a, r) { return a + r[key][i]; }, 0) / runs.length);
      return out;
    }
    var th = meanCi(col("throughput")), wip = meanCi(col("mean_wip")), ct = meanCi(col("mean_ct")), lr = meanCi(col("littles_ratio"));
    return {
      throughput: th[0], throughput_half: th[1],
      mean_wip: wip[0], mean_wip_half: wip[1],
      mean_ct: ct[0], mean_ct_half: ct[1],
      littles_ratio: lr[0], littles_ratio_half: lr[1],
      mean_buffers: share("mean_buffers"),
      limiting_share: share("limiting_share"),
      blocked_share: share("blocked_share"),
      starved_share: share("starved_share"),
      reps: runs.length
    };
  }
  function analyzeLine(cfg, o) {
    o = o || {};
    var reps = o.reps || 24, periods = o.periods || 300, warmup = o.warmup == null ? 50 : o.warmup, seed = o.seed || 20261113;
    var runs = runReps(cfg, reps, periods, warmup, seed);
    var out = aggregate(runs, cfg.stations.length);
    out.rep_throughputs = runs.map(function (r) { return r.throughput; });
    if (o.withRuns) out.runs = runs;
    return out;
  }
  function capability(cfg, o) {
    o = o || {};
    var fed = { stations: cfg.stations, buffer_limits: cfg.buffer_limits, release: { mode: "infinite" } };
    return analyzeLine(fed, o);
  }
  function kingman(cfg, throughput) {
    var specs = cfg.stations, n = specs.length, mode = (cfg.release && cfg.release.mode) || "infinite";
    var cs2 = specs.map(stationScv), varC = specs.map(stationVar);
    if (throughput <= 0) return specs.map(function () { return { util: 0, wq: 0, queue: 0 }; });
    var ca2 = new Array(n).fill(0);
    if (mode === "conwip") ca2[0] = cs2[n - 1];
    var rows = [];
    for (var i = 0; i < n; i++) {
      var mu = stationMean(specs[i]);
      var u = mu > 0 ? throughput / mu : Infinity;
      if (i > 0) {
        var up = Math.min(rows[i - 1].util, 1.0);
        ca2[i] = up * up * cs2[i - 1] + (1 - up * up) * ca2[i - 1];
      }
      var varA = ca2[i] * throughput * throughput;
      if (!isFinite(u) || mu <= throughput) rows.push({ util: u, wq: null, queue: null });
      else {
        var queue = (varA + varC[i]) / (2.0 * (mu - throughput));
        rows.push({ util: u, wq: queue / throughput, queue: queue });
      }
    }
    return rows;
  }
  function capacityVariant(spec) {
    if (spec.kind === "die") {
      var cv = Math.sqrt(stationScv(spec)), mu = stationMean(spec) + 0.5;
      return [0.5, { kind: "normal", lo: 1, hi: 6, mu: mu, sigma: cv * mu, value: 0 }];
    }
    if (spec.kind === "uniform") return [1.0, { kind: "uniform", lo: spec.lo + 1, hi: spec.hi + 1, mu: 0, sigma: 0, value: 0 }];
    if (spec.kind === "fixed") return [1.0, { kind: "fixed", lo: 1, hi: 6, mu: 0, sigma: 0, value: spec.value + 1 }];
    var delta = Math.max(0.5, Math.round(0.1 * spec.mu * 10) / 10);
    var cv2 = Math.sqrt(stationScv(spec)), mu2 = spec.mu + delta;
    return [delta, { kind: "normal", lo: 1, hi: 6, mu: mu2, sigma: cv2 * mu2, value: 0 }];
  }
  function improvementOptions(cfg, o) {
    o = o || {};
    var reps = o.reps || 16, periods = o.periods || 300, warmup = o.warmup == null ? 50 : o.warmup, seed = o.seed || 20261113;
    var baseRuns = o.baseRuns || runReps(cfg, reps, periods, warmup, seed);
    var baseTh = baseRuns.map(function (r) { return r.throughput; });
    var cands = [];
    cfg.stations.forEach(function (s, i) {
      var v = capacityVariant(s), stations = cfg.stations.slice();
      stations[i] = v[1];
      cands.push({ kind: "capacity", station: i, delta: v[0], add: null, cfg: { stations: stations, buffer_limits: cfg.buffer_limits, release: cfg.release } });
    });
    if (cfg.buffer_limits) {
      for (var i = 1; i < cfg.stations.length; i++) {
        if (cfg.buffer_limits[i - 1] >= 1000000) continue;
        var add = Math.max(4, Math.round(0.5 * stationMean(cfg.stations[i])));
        var limits = cfg.buffer_limits.slice(); limits[i - 1] += add;
        cands.push({ kind: "buffer", station: i, delta: null, add: add, cfg: { stations: cfg.stations, buffer_limits: limits, release: cfg.release } });
      }
    }
    var out = cands.map(function (c) {
      var runs = runReps(c.cfg, reps, periods, warmup, seed);
      var gains = runs.map(function (r, j) { return r.throughput - baseTh[j]; });
      var gm = meanCi(gains), tm = meanCi(runs.map(function (r) { return r.throughput; }));
      return { kind: c.kind, station: c.station, delta: c.delta, add: c.add, gain: gm[0], gain_half: gm[1], throughput: tm[0] };
    });
    out.sort(function (a, b) { return b.gain - a.gain; });
    return out;
  }
  /* Push vs drum-buffer-rope vs CONWIP at the same output: share (0.95) of
   * what the line passes fed without limit. Mirrors release_comparison. */
  function releaseComparison(cfg, o) {
    o = o || {};
    var reps = o.reps || 16, periods = o.periods || 300, warmup = o.warmup == null ? 50 : o.warmup, seed = o.seed || 20261113;
    var share = o.share || 0.95;
    var means = cfg.stations.map(stationMean);
    var b = means.indexOf(Math.min.apply(null, means));
    var half = Math.max(6, Math.floor(reps / 2));
    var fed = capability(cfg, { reps: half, periods: periods, warmup: warmup, seed: seed }).throughput;
    var target = share * fed;
    function variant(release) { return { stations: cfg.stations, buffer_limits: cfg.buffer_limits, release: release }; }
    function run(release, rps) {
      var agg = aggregate(runReps(variant(release), rps, periods, warmup, seed), cfg.stations.length);
      return { throughput: agg.throughput, throughput_half: agg.throughput_half, mean_wip: agg.mean_wip, mean_ct: agg.mean_ct };
    }
    function reaches(release) {
      return aggregate(runReps(variant(release), half, periods, warmup, seed), cfg.stations.length).throughput >= 0.995 * target;
    }
    function smallest(make) { /* bisection over whole settings 1..200 */
      var lo = 1, hi = 200;
      if (!reaches(make(hi))) return hi;
      while (lo < hi) { var mid = Math.floor((lo + hi) / 2); if (reaches(make(mid))) hi = mid; else lo = mid + 1; }
      return lo;
    }
    var rate = Math.round(target * 100) / 100;
    var push = run({ mode: "push", rate: rate }, reps);
    var rope = smallest(function (v) { return { mode: "rope", bottleneck: b, time_buffer: v }; });
    var dbr = run({ mode: "rope", bottleneck: b, time_buffer: rope }, reps);
    var cap = smallest(function (v) { return { mode: "conwip", wip: v }; });
    var conwip = run({ mode: "conwip", wip: cap }, reps);
    push.wip_if_high = run({ mode: "push", rate: Math.round(rate * 120) / 100 }, reps).mean_wip;
    dbr.wip_if_high = run({ mode: "rope", bottleneck: b, time_buffer: Math.ceil(rope * 1.2) }, reps).mean_wip;
    conwip.wip_if_high = run({ mode: "conwip", wip: Math.ceil(cap * 1.2) }, reps).mean_wip;
    return [
      Object.assign({ rule: "push", rate: rate, target: target }, push),
      Object.assign({ rule: "dbr", stock: rope, target: target }, dbr),
      Object.assign({ rule: "conwip", wip: cap, target: target }, conwip)
    ];
  }


  /* ---------------- data mode ---------------- */
  var ACTIVE_WORDS = { active: 1, working: 1, busy: 1, running: 1, processing: 1, producing: 1, up: 1, "true": 1, yes: 1, x: 1 };
  var INACTIVE_WORDS = { idle: 1, starved: 1, blocked: 1, down: 1, off: 1, stopped: 1, waiting: 1, "false": 1, no: 1, "-": 1, "": 1 };
  function splitRow(line) {
    var delims = [",", ";", "\t"];
    for (var i = 0; i < delims.length; i++) if (line.indexOf(delims[i]) >= 0) return line.split(delims[i]).map(function (c) { return c.trim(); });
    return line.split(/\s+/).filter(function (c) { return c.length; });
  }
  function parseCell(cell) {
    var low = cell.trim().toLowerCase();
    if (ACTIVE_WORDS[low]) return [null, true];
    if (INACTIVE_WORDS[low]) return [null, false];
    var v = Number(cell);
    if (cell.trim() === "" || !isFinite(v)) throw new Error("unrecognized cell: " + cell);
    return [v, v > 0];
  }
  function parseLog(text) {
    var lines = text.split(/\r?\n/).map(function (s) { return s.trim(); }).filter(function (s) { return s.length; });
    if (lines.length < 2) throw new Error("Paste at least a few periods of log.");
    var rows = lines.map(splitRow);
    function isHeader(cells) {
      for (var i = 0; i < cells.length; i++) {
        var low = cells[i].trim().toLowerCase();
        if (ACTIVE_WORDS[low] || INACTIVE_WORDS[low]) continue;
        if (!isFinite(Number(cells[i]))) return true;
      }
      return false;
    }
    var names = null;
    if (isHeader(rows[0])) {
      names = rows[0].map(function (c, i) { return c || "Station " + (i + 1); });
      rows = rows.slice(1);
    }
    if (names && ["period", "time", "hour", "step", "t", "#"].indexOf(names[0].toLowerCase()) >= 0) {
      rows = rows.map(function (r) { return r.slice(1); });
      names = names.slice(1);
    } else if (rows.length && rows.every(function (r) { return r.length >= 3; })) {
      var first = rows.map(function (r) { return Number(r[0]); });
      var seq = first.every(function (v, i) { return v === i + 1; });
      if (seq) { rows = rows.map(function (r) { return r.slice(1); }); if (names) names = names.slice(1); }
    }
    if (!rows.length || rows[0].length < 2) throw new Error("The log needs at least two stations.");
    var width = rows[0].length, outputs = [], states = [], bad = 0;
    rows.forEach(function (r) {
      if (r.length !== width) { bad++; return; }
      var orow = [], srow = [];
      try { r.forEach(function (c) { var p = parseCell(c); orow.push(p[0]); srow.push(p[1]); }); }
      catch (e) { bad++; return; }
      outputs.push(orow); states.push(srow);
    });
    if (bad > Math.max(2, Math.floor(rows.length / 10))) throw new Error("Too many rows do not match the log's shape.");
    if (states.length < 5) throw new Error("Too few usable periods in the log.");
    if (!names || names.length !== width) names = rows[0].map(function (_, i) { return "Station " + (i + 1); });
    return { names: names, outputs: outputs, states: states };
  }
  function activePeriod(states) {
    if (!states.length) throw new Error("empty log");
    var T = states.length, n = states[0].length;
    var runs = new Array(n).fill(0), longest = new Array(n).fill(0), active = new Array(n).fill(0), shares = new Array(n).fill(0);
    var byPeriod = [];
    states.forEach(function (row) {
      var i;
      for (i = 0; i < n; i++) {
        if (row[i]) { runs[i]++; active[i]++; if (runs[i] > longest[i]) longest[i] = runs[i]; }
        else runs[i] = 0;
      }
      var top = Math.max.apply(null, runs);
      var tied = [];
      for (i = 0; i < n; i++) if (runs[i] === top && top > 0) tied.push(i);
      if (tied.length) {
        tied.forEach(function (j) { shares[j] += 1.0 / tied.length; });
        byPeriod.push(tied.length === 1 ? tied[0] : -1);
      } else byPeriod.push(-1);
    });
    return {
      periods: T,
      bottleneck_share: shares.map(function (s) { return s / T; }),
      active_share: active.map(function (a) { return a / T; }),
      longest_active: longest,
      bottleneck_by_period: byPeriod
    };
  }
  function analyzeLog(text) {
    var parsed = parseLog(text);
    var ap = activePeriod(parsed.states);
    var n = parsed.names.length;
    var meanOutput = [];
    for (var i = 0; i < n; i++) {
      var vals = parsed.outputs.map(function (r) { return r[i]; }).filter(function (v) { return v !== null; });
      meanOutput.push(vals.length ? vals.reduce(function (a, x) { return a + x; }, 0) / vals.length : null);
    }
    var top = ap.bottleneck_share.indexOf(Math.max.apply(null, ap.bottleneck_share));
    return Object.assign({ names: parsed.names, mean_output: meanOutput, top: top }, ap);
  }

  /* ---------------- verdicts ---------------- */
  function argmax(arr) { var b = 0; for (var i = 1; i < arr.length; i++) if (arr[i] > arr[b]) b = i; return b; }
  function argmin(arr) { var b = 0; for (var i = 1; i < arr.length; i++) if (arr[i] < arr[b]) b = i; return b; }
  function verdict(s) {
    var means = s.means, limiting = s.limiting;
    var top = argmax(limiting);
    var order = means.map(function (_, i) { return i; }).sort(function (a, b) { return limiting[b] - limiting[a]; });
    var second = order.length > 1 ? order[1] : top;
    var minMean = Math.min.apply(null, means), bn = means.indexOf(minMean);
    var facts = { bottleneck: top, by_average: bn, second: second };
    var i;
    for (i = 0; i < means.length; i++) if (means[i] <= 0) return Object.assign({ state: "bad", reason: "zero", bottleneck: i }, facts, { bottleneck: i });
    var rate = s.push_rate;
    if (s.release_mode === "push" && rate !== null && rate !== undefined && rate > minMean + Math.max(0.5, 0.15 * minMean))
      return Object.assign({ state: "bad", reason: "release" }, facts, { bottleneck: bn });
    var cap = s.capability;
    if (s.release_mode === "push" && rate !== null && rate !== undefined && cap !== null && cap !== undefined && rate < minMean - 1e-9 && cap - s.th > Math.max(0.05, 0.03 * cap))
      return Object.assign({ state: "warn", reason: "release-limited" }, facts);
    if (s.plan !== null && s.plan !== undefined && s.th < s.plan - Math.max(0.05, 0.02 * s.plan))
      return Object.assign({ state: "warn", reason: "plan" }, facts);
    var blocked = s.blocked || means.map(function () { return 0; });
    var btop = argmax(blocked);
    /* A high blocked share alone is a symptom: stations upstream of a
       capacity bottleneck are blocked whenever its buffer fills. The
       buffer verdict fires only when the priced options agree that
       space is the binding fix (best change = buffer at that station). */
    if (blocked[btop] >= 0.5 && s.best_kind === "buffer" && s.best_station === btop + 1) {
      var solid = s.best_gain !== null && s.best_gain !== undefined && s.best_gain >= Math.max(0.05, 0.03 * s.th);
      return Object.assign({ state: solid ? "good" : "warn", reason: "buffer" }, facts, { bottleneck: btop + 1, blocked_station: btop });
    }
    var gapTop = limiting[top] - limiting[second];
    var gapAll = limiting[top] - Math.min.apply(null, limiting);
    if (gapTop < 0.15 && gapAll < 0.25) return Object.assign({ state: "accent", reason: "balanced" }, facts);
    if (gapTop < 0.15) return Object.assign({ state: "warn", reason: "wandering" }, facts);
    if (s.best_gain === null || s.best_gain === undefined || s.best_gain < Math.max(0.05, 0.03 * s.th))
      return Object.assign({ state: "warn", reason: "small-gains" }, facts);
    return Object.assign({ state: "good", reason: "clear" }, facts);
  }
  function verdictData(log) {
    var shares = log.bottleneck_share, active = log.active_share, n = shares.length;
    var top = argmax(shares);
    var order = shares.map(function (_, i) { return i; }).sort(function (a, b) { return shares[b] - shares[a]; });
    var second = n > 1 ? order[1] : top;
    for (var i = 0; i < n; i++) if (active[i] <= 0) return { state: "bad", reason: "never-active", bottleneck: top, station: i };
    if (shares[top] >= 0.5) return { state: "good", reason: "dominant", bottleneck: top };
    if (shares[top] >= 0.3 && shares[second] > shares[top] - 0.10) return { state: "warn", reason: "wandering", bottleneck: top, second: second };
    return { state: "accent", reason: "wandering-wide", bottleneck: top };
  }

  var api = {
    LCG: LCG, stationMean: stationMean, stationDraw: stationDraw,
    stationScv: stationScv, stationVar: stationVar,
    simulateLine: simulateLine, meanCi: meanCi,
    toolSpec: toolSpec, toolConfig: toolConfig,
    analyzeLine: analyzeLine, capability: capability,
    kingman: kingman, improvementOptions: improvementOptions,
    releaseComparison: releaseComparison,
    parseLog: parseLog, activePeriod: activePeriod, analyzeLog: analyzeLog,
    verdict: verdict, verdictData: verdictData
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  g.Linesim = api;
})(typeof window !== "undefined" ? window : globalThis);
