"use strict";
/* Production Line Bottleneck Finder: page logic.
   The engine is docs/linesim.js (window.Linesim), a line-by-line mirror
   of the Python reference implementation in src/linesim/. Every number
   on the page comes from that engine; this file only reads inputs,
   renders results, and runs the live-line animation. */
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var LS = window.Linesim, F = Tool.fmt;
  var SEED = 20261113;

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function n1(x) { return F.num(x, 1); }
  function n2(x) { var v = F.num(x, 2); return v === "-0.00" || v === "−0.00" ? "0.00" : v; }
  /* a signed gain: "+0.42", "−0.03", never "+-0.00" */
  function sg2(x) { var v = n2(x); return v === "0.00" ? "±0.00" : (x > 0 ? "+" : "") + v; }
  function pct0(x) { return F.pct(x, 0); }
  function debounce(fn, ms) { var t; return function () { clearTimeout(t); t = setTimeout(fn, ms); }; }

  /* ---------------- state ---------------- */
  var DEFAULT_ST = "Cut,5.5,0.25,|Weld,4.6,0.3,8|Paint,3.4,0.35,8|Assemble,4.8,0.25,8|Pack,5.2,0.2,8";
  var state = Tool.readParams({
    mode: "analyze", st: DEFAULT_ST, rel: "dbr",
    rate: 3, stock: 8, wip: 24, plan: "", reps: 20, periods: 300
  });
  var relVals = { rate: state.rate, stock: state.stock, wip: state.wip };
  function paramKey(rule) { return rule === "push" ? "rate" : rule === "dbr" ? "stock" : "wip"; }
  var mode = state.mode === "data" ? "data" : "analyze";
  var lastResult = null, lastData = null;

  var VAR_OPTS = [
    ["steady", "Steady", 0.15], ["some", "Some", 0.3], ["lot", "A lot", 0.55],
    ["die", "Die roll (1 to 6)", null], ["custom", "Custom cv", null]
  ];
  function presetFor(cv) {
    for (var i = 0; i < 3; i++) if (Math.abs(cv - VAR_OPTS[i][2]) < 1e-9) return VAR_OPTS[i][0];
    return "custom";
  }

  /* ---------------- station rows ---------------- */
  function makeRow(st, idx) {
    var row = document.createElement("div");
    row.className = "stn-row";
    var bufCell;
    if (idx === 0) {
      bufCell = '<span class="stn-nobuf">line start</span>';
    } else {
      bufCell = '<span class="stn-lab">Buffer in front</span>' +
        '<input class="stn-buf" type="number" min="1" step="1" placeholder="no limit" aria-label="Buffer space in front" value="' + esc(st.buf) + '">';
    }
    row.innerHTML =
      '<span class="stn-name-cell"><span class="stn-lab">Station</span>' +
      '<input class="stn-name" type="text" aria-label="Station name" value="' + esc(st.name) + '"></span>' +
      '<span><span class="stn-lab">Output / period</span>' +
      '<input class="stn-mean" type="number" min="0" step="any" aria-label="Average output per period" value="' + esc(st.mean) + '"></span>' +
      '<span class="stn-varwrap"><span class="stn-lab">Variability</span><span class="stn-varcell"></span></span>' +
      '<span class="stn-bufcell">' + bufCell + '</span>' +
      '<button type="button" class="stn-del" aria-label="Remove this station">×</button>';
    var varCell = row.children[2].querySelector(".stn-varcell");
    var varSel = document.createElement("select");
    varSel.className = "stn-var";
    varSel.setAttribute("aria-label", "Variability");
    VAR_OPTS.forEach(function (o) {
      var op = document.createElement("option");
      op.value = o[0]; op.textContent = o[1];
      varSel.appendChild(op);
    });
    varSel.value = st.varSel;
    varCell.appendChild(varSel);
    var cvIn = document.createElement("input");
    cvIn.className = "stn-cv"; cvIn.type = "number"; cvIn.min = "0"; cvIn.max = "2";
    cvIn.step = "0.01"; cvIn.placeholder = "cv"; cvIn.value = st.cv;
    cvIn.setAttribute("aria-label", "Coefficient of variation");
    cvIn.hidden = st.varSel !== "custom";
    varCell.appendChild(cvIn);
    return row;
  }
  function renderRows(stations) {
    var host = $("stations");
    host.innerHTML = "";
    stations.forEach(function (st, i) { host.appendChild(makeRow(st, i)); });
    $("stn-count").textContent = stations.length + " stations (2 to 8). Buffer blank means no limit.";
    $("add-station").disabled = stations.length >= 8;
  }
  function collectRows() {
    return Array.prototype.map.call($("stations").children, function (row, i) {
      var varSel = row.querySelector(".stn-var").value;
      return {
        name: row.querySelector(".stn-name").value,
        mean: row.querySelector(".stn-mean").value,
        varSel: varSel,
        cv: varSel === "custom" ? row.querySelector(".stn-cv").value : "",
        buf: i === 0 ? "" : row.querySelector(".stn-buf").value
      };
    });
  }
  function parseStationsParam(s) {
    return String(s).split("|").filter(Boolean).map(function (part) {
      var bits = part.split(",");
      var cvTok = (bits[2] || "0.3").trim();
      if (cvTok === "die") return { name: bits[0] || "", mean: bits[1] || "", varSel: "die", cv: "", buf: bits[3] || "" };
      var cv = Number(cvTok);
      var sel = isFinite(cv) ? presetFor(cv) : "some";
      return { name: bits[0] || "", mean: bits[1] || "", varSel: sel, cv: sel === "custom" ? cvTok : "", buf: bits[3] || "" };
    });
  }
  function stationsParam(stations) {
    return stations.map(function (st) {
      var cvTok = st.varSel === "die" ? "die"
        : st.varSel === "custom" ? (st.cv === "" ? "0.3" : st.cv)
        : String(VAR_OPTS.filter(function (o) { return o[0] === st.varSel; })[0][2]);
      return [st.name.replace(/[,|]/g, " "), st.mean, cvTok, st.buf].join(",");
    }).join("|");
  }

  /* ---------------- reading the analyze form ---------------- */
  function readLine() {
    var errors = [];
    function mark(el, msg) { if (el) el.classList.add("err"); errors.push(msg); }
    Array.prototype.forEach.call(document.querySelectorAll("#inputs .err"), function (e) { e.classList.remove("err"); });
    var raw = collectRows();
    if (raw.length < 2) errors.push("A line needs at least two stations.");
    var stations = raw.map(function (r, i) {
      var row = $("stations").children[i];
      var name = r.name.trim() || ("Station " + (i + 1));
      var meanEl = row.querySelector(".stn-mean");
      var mean = r.mean === "" ? NaN : Number(r.mean);
      if (!isFinite(mean) || mean < 0) mark(meanEl, "Station " + (i + 1) + ": output per period must be 0 or more.");
      var cv = null, die = false;
      if (r.varSel === "die") { die = true; cv = 0.49; }
      else if (r.varSel === "custom") {
        var cvEl = row.querySelector(".stn-cv");
        cv = r.cv === "" ? NaN : Number(r.cv);
        if (!isFinite(cv) || cv < 0 || cv > 2) mark(cvEl, name + ": variability (cv) must be between 0 and 2.");
      } else cv = VAR_OPTS.filter(function (o) { return o[0] === r.varSel; })[0][2];
      var buffer = null;
      if (i > 0 && r.buf !== "") {
        var bufEl = row.querySelector(".stn-buf");
        var b = Number(r.buf);
        if (!isFinite(b) || b < 1 || Math.floor(b) !== b) mark(bufEl, name + ": buffer space is a whole number of 1 or more, or blank for no limit.");
        else buffer = b;
      }
      return { name: name, mean: mean, cv: cv, buffer: buffer, die: die };
    });
    var rel = $("rel").value;
    var paramEl = $("rel-param");
    var pv = paramEl.value === "" ? NaN : Number(paramEl.value);
    if (rel === "push" && (!isFinite(pv) || pv < 1 || Math.floor(pv) !== pv)) mark(paramEl, "Release rate: a whole number of units per period, 1 or more.");
    if (rel === "conwip" && (!isFinite(pv) || pv < 1 || Math.floor(pv) !== pv)) mark(paramEl, "Work-in-process cap: a whole number, 1 or more.");
    if (rel === "dbr" && (!isFinite(pv) || pv < 1 || Math.floor(pv) !== pv)) mark(paramEl, "Rope length: a whole number, 1 or more.");
    if (isFinite(pv)) relVals[paramKey(rel)] = pv;
    var release = rel === "push" ? { mode: "push", rate: relVals.rate }
      : rel === "dbr" ? { mode: "dbr", stock: relVals.stock }
      : { mode: "conwip", wip: relVals.wip };
    var plan = null;
    var planEl = $("plan");
    if (planEl.value !== "") {
      plan = Number(planEl.value);
      if (!isFinite(plan) || plan <= 0) { mark(planEl, "Planned output: above 0, or blank."); plan = null; }
    }
    var errBox = $("form-error");
    if (errors.length) { errBox.textContent = errors[0]; errBox.hidden = false; return null; }
    errBox.hidden = true;
    return { tool: { stations: stations, release: release }, plan: plan };
  }

  function writeUrl() {
    if (mode !== "analyze") { Tool.writeParams({ mode: mode }); return; }
    Tool.writeParams({
      mode: mode, st: stationsParam(collectRows()), rel: $("rel").value,
      rate: relVals.rate, stock: relVals.stock, wip: relVals.wip,
      plan: $("plan").value, reps: Number($("reps").value), periods: Number($("periods").value)
    });
  }

  /* ---------------- analyze: compute and render ---------------- */
  function optionText(o, names, withGain) {
    var base = o.kind === "capacity"
      ? "add capacity at " + names[o.station] + " (" + (o.delta >= 0 ? "+" : "") + n2(o.delta) + " per period)"
      : "add " + o.add + " buffer spaces in front of " + names[o.station];
    if (!withGain) return base;
    return base + ", for about " + sg2(o.gain) + " per period (" +
      n2(o.gain - o.gain_half) + " to " + n2(o.gain + o.gain_half) + ")";
  }
  function capFirst(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

  function showInvalid() {
    stopLive();
    lastResult = null;
    $("verdict").className = "panel verdict v-neutral";
    $("v-title").textContent = "Check the highlighted inputs";
    $("v-body").textContent = "";
    $("v-kpis").innerHTML = "";
    $("v-checks").innerHTML = "";
    $("chart").innerHTML = "";
    $("chart-cap").textContent = "";
    $("full-numbers").innerHTML = "";
    $("release-numbers").innerHTML = "";
    $("live-line").innerHTML = "";
  }

  function compute() {
    var parsed = readLine();
    if (!parsed) { showInvalid(); writeUrl(); return; }
    var tool = parsed.tool;
    var cfg = LS.toolConfig(tool);
    var reps = Number($("reps").value), periods = Number($("periods").value);
    var warmup = Math.floor(periods / 6);
    var o = { reps: reps, periods: periods, warmup: warmup, seed: SEED };
    var oSmall = { reps: Math.max(8, Math.round(reps * 0.6)), periods: periods, warmup: warmup, seed: SEED };
    var agg = LS.analyzeLine(cfg, o);
    var capAgg = tool.release.mode === "push" ? LS.capability(cfg, o) : null;
    var options = LS.improvementOptions(cfg, oSmall);
    var relCmp = LS.releaseComparison(cfg, oSmall);
    var kg = LS.kingman(cfg, agg.throughput);
    var names = tool.stations.map(function (s) { return s.name; });
    var means = cfg.stations.map(LS.stationMean);
    var v = LS.verdict({
      means: means, limiting: agg.limiting_share, blocked: agg.blocked_share,
      th: agg.throughput, capability: capAgg ? capAgg.throughput : null,
      plan: parsed.plan, release_mode: tool.release.mode,
      push_rate: tool.release.mode === "push" ? tool.release.rate : null,
      best_gain: options.length ? options[0].gain : null,
      best_station: options.length ? options[0].station : null,
      best_kind: options.length ? options[0].kind : null
    });
    var R = {
      tool: tool, cfg: cfg, parsed: parsed, agg: agg, capAgg: capAgg,
      options: options, relCmp: relCmp, kg: kg, names: names, means: means, v: v,
      reps: reps, periods: periods
    };
    lastResult = R;
    renderVerdict(R);
    renderOptionsChart(R);
    renderFullNumbers(R);
    renderReleaseTable(R);
    buildLive(R);
    writeUrl();
  }

  function verdictCopy(R) {
    var agg = R.agg, v = R.v, names = R.names, th = agg.throughput;
    var bn = v.bottleneck, BN = names[bn];
    var best = R.options.length ? R.options[0] : null;
    var bestPhrase = !best ? "no single change stands out"
      : best.gain > 0.02 ? "Best next change: " + optionText(best, names, true) + "."
      : "No single change pays on its own: the best of them, " + optionText(best, names, false) +
        ", comes out at " + n2(best.gain) + " per period, inside the noise.";
    var lo = n2(th - agg.throughput_half), hi = n2(th + agg.throughput_half);
    switch (v.reason) {
      case "zero":
        return { title: BN + " averages zero output.",
          body: "A station that completes nothing stops the whole line behind it, so expected output is zero whatever the other stations do. Repair it, staff it, or take it out of the line. Until then, no other change matters." };
      case "release":
        return { title: "You are releasing work faster than the line can take it.",
          body: "Releases of " + R.tool.release.rate + " per period run into " + BN + ", which averages " +
            n2(R.means[bn]) + ". Output stays at " + n2(th) + " per period; the extra work only piles up in front of " +
            BN + ", with " + n1(agg.mean_wip) + " units in process on average. Tie release to the bottleneck (drum-buffer-rope) or cap work in process (CONWIP); both are compared below." };
      case "release-limited":
        return { title: "Your release rate, not the line, is the limit.",
          body: "You release " + R.tool.release.rate + " per period and the line passes " + n2(th) + ". Fed freely, the same line would pass about " +
            n2(R.capAgg.throughput) + ". " + BN + " is the line's own bottleneck once releases keep up, so raising the release rate toward " +
            n2(R.means[bn]) + " is output the line already has in it. " + bestPhrase };
      case "plan": {
        var gap = R.parsed.plan - th;
        var closes = best && best.gain > 0 ? " " + capFirst(optionText(best, names, true)) +
          (best.gain >= gap ? ", which more than closes the gap." : ", which closes about " + pct0(best.gain / gap) + " of the gap.") : "";
        return { title: "Expect " + n2(th) + " per period, not the " + n2(R.parsed.plan) + " in the plan.",
          body: BN + " sets the pace, limiting the line in " + pct0(agg.limiting_share[bn]) + " of periods. The shortfall is " +
            n2(gap) + " per period." + closes };
      }
      case "buffer": {
        var up = R.names[v.blocked_station], buf = R.tool.stations[bn].buffer;
        return { title: "The buffer in front of " + BN + " is the bottleneck.",
          body: up + " finishes work it cannot pass on in " + pct0(agg.blocked_share[v.blocked_station]) +
            " of periods, because the " + buf + " spaces in front of " + BN + " are full. So " + BN +
            " gets work in bursts, is starved in others, and the line averages " + n2(th) + " per period. " + bestPhrase };
      }
      case "balanced": {
        var shares = agg.limiting_share;
        return { title: "No single bottleneck: this line is balanced.",
          body: "Every station limits the line at times; limiting shares run from " + pct0(Math.min.apply(null, shares)) +
            " to " + pct0(Math.max.apply(null, shares)) + ". Output is lost to variability and dependence, not to one station: expect " +
            n2(th) + " per period (" + lo + " to " + hi + ") against a slowest-station average of " + n2(Math.min.apply(null, R.means)) +
            ". On a balanced line the levers are buffers, less variability, and release discipline. " + bestPhrase };
      }
      case "wandering": {
        var A = BN, B = R.names[v.second];
        return { title: "The bottleneck moves between " + A + " and " + B + ".",
          body: A + " limits the line in " + pct0(agg.limiting_share[bn]) + " of periods and " + B + " in " +
            pct0(agg.limiting_share[v.second]) + ". The two are close enough that fixing only one hands the constraint to the other; together they cap output at " +
            n2(th) + " per period (" + lo + " to " + hi + "). The ranked list below prices each change separately." };
      }
      case "small-gains":
        return { title: BN + " is the bottleneck, but single fixes buy little.",
          body: BN + " limits the line in " + pct0(agg.limiting_share[bn]) + " of periods, yet the best single change (" +
            (best ? optionText(best, names, false) : "none") + ") adds only about " + n2(best ? best.gain : 0) +
            " per period: the line already runs close to what its averages allow. The remaining lever is variability at " + BN + " itself, which this tool does not price." };
      default:
        return { title: BN + " is your bottleneck.",
          body: "Expect " + n2(th) + " units per period (" + lo + " to " + hi + "), not the " + n2(R.means[bn]) +
            " the slowest station averages on its own: variability and dependence take the rest. " + BN + " limited the line in " +
            pct0(agg.limiting_share[bn]) + " of simulated periods. A unit spends about " + n1(agg.mean_ct) +
            " periods in the line, and " + n1(agg.mean_wip) + " units are in process on average. " + bestPhrase };
    }
  }

  function buildChecks(R) {
    var agg = R.agg, v = R.v, names = R.names, th = agg.throughput;
    var bn = v.bottleneck, BN = names[bn];
    var checks = [];
    /* 1: bottleneck by simulation */
    if (v.reason === "buffer") {
      checks.push(["warn", "BUFFER", "The binding constraint is space",
        names[v.blocked_station] + " is blocked by the full buffer in front of " + BN + " in " +
        pct0(agg.blocked_share[v.blocked_station]) + " of periods. The station itself has capacity to spare; the room in front of it does not."]);
    } else if (bn === v.by_average) {
      checks.push(["info", "BY SIMULATION", BN + " is the bottleneck",
        BN + " limits the line in " + pct0(agg.limiting_share[bn]) + " of periods, and it also has the lowest average output (" +
        n2(R.means[bn]) + "). The simulation and the averages agree here."]);
    } else {
      checks.push(["warn", "BY SIMULATION", "The averages point at a different station",
        names[v.by_average] + " has the lowest average output (" + n2(R.means[v.by_average]) + "), but " + BN +
        " limits the line most often (" + pct0(agg.limiting_share[bn]) + " of periods). With this much variability, trust the simulation."]);
    }
    /* 2: Little's law */
    var lr = agg.littles_ratio;
    if (lr === null || lr === undefined || !isFinite(lr)) {
      checks.push(["info", "LITTLE'S LAW", "Nothing to check yet",
        "No units finished during the measured part of the runs, so work in process and cycle time have nothing to agree with."]);
    } else {
      var dev = Math.abs(lr - 1), prod = th * agg.mean_ct;
      if (dev <= 0.05) checks.push(["ok", "LITTLE'S LAW", "The simulator's counters agree",
        "Work in process (" + n1(agg.mean_wip) + ") matches throughput × cycle time (" + n2(th) + " × " + n1(agg.mean_ct) +
        " = " + n1(prod) + ")" + (dev < 0.005 ? ", to within half a percent." : " within " + pct0(dev) + ".")]);
      else if (dev <= 0.5) checks.push(["warn", "LITTLE'S LAW", "The line is still settling",
        "Work in process (" + n1(agg.mean_wip) + ") sits " + pct0(dev) + " away from throughput × cycle time (" + n1(prod) +
        "): queues are still growing over this horizon, so read the WIP and cycle-time figures as approximate."]);
      else checks.push(["fail", "LITTLE'S LAW", "The run never settles",
        "Work in process (" + n1(agg.mean_wip) + ") is " + pct0(dev) + " away from throughput × cycle time (" + n1(prod) +
        "): queues grow through the whole run. Throughput is the settled number here; WIP and cycle time are lower bounds."]);
    }
    /* 3: Kingman next to simulation */
    var kgB = R.kg[bn], simQ = agg.mean_buffers[bn];
    if (!kgB || kgB.queue === null || kgB.queue === undefined) {
      checks.push(["info", "KINGMAN", "No finite queue at " + BN,
        BN + " runs at or over the line's throughput on average, so the heavy-traffic approximation has no finite queue there, and neither does the line: its queue is the one that grows."]);
    } else if (kgB.util >= 0.98) {
      checks.push(["info", "KINGMAN", "The formula explodes this close to saturation",
        "Kingman's heavy-traffic form puts " + n1(kgB.queue) + " units in front of " + BN + "; the simulation averages " +
        n1(simQ) + ". At " + pct0(Math.min(kgB.util, 1)) + " utilization the formula's denominator (average capacity minus throughput) is so small that the estimate blows up. Use the simulated queue here; the formula is a cross-check at lower utilizations."]);
    } else {
      var dir = kgB.queue >= simQ ? "high" : "low";
      var kdev = simQ > 0.05 ? " It runs " + dir + " by about " + pct0(Math.abs(kgB.queue - simQ) / simQ) + " at this utilization (" + pct0(Math.min(kgB.util, 1)) + ")." : "";
      checks.push(["info", "KINGMAN", "Formula next to simulation",
        "Kingman's heavy-traffic approximation puts " + n1(kgB.queue) + " units in front of " + BN +
        "; the simulation averages " + n1(simQ) + "." + kdev]);
    }
    /* 4: release rules, compared at the same output and with a wrong setting */
    var rows = R.relCmp, labels = { push: "Push", dbr: "Drum-buffer-rope", conwip: "CONWIP" };
    var byRule = {}; rows.forEach(function (r) { byRule[r.rule] = r; });
    var wipList = rows.map(function (r) { return labels[r.rule] + " " + n1(r.mean_wip); }).join(", ");
    var highList = rows.map(function (r) { return labels[r.rule] + " " + n1(r.wip_if_high); }).join(", ");
    var pullHigh = Math.min(byRule.dbr.wip_if_high, byRule.conwip.wip_if_high);
    var fragile = byRule.push.wip_if_high > 2 * pullHigh;
    var mine = R.tool.release.mode;
    var relText = "Set to make " + n2(rows[0].target) + " a period (95% of what the line can pass), work in process is " + wipList +
      ". Set 20% too high, it becomes " + highList + ".";
    if (mine === "push" && fragile) {
      checks.push(["warn", "RELEASE RULES", "Push only works while the rate is right",
        relText + " A pull rule caps the damage of a wrong setting; push lets the queue grow until someone notices."]);
    } else if (mine !== "push") {
      checks.push(["ok", "RELEASE RULES", labels[mine] + " protects you from a wrong setting", relText]);
    } else {
      checks.push(["info", "RELEASE RULES", "Release rules at the same output", relText]);
    }
    /* 5: plan, or what dependence costs */
    if (R.parsed.plan !== null && R.parsed.plan !== undefined) {
      if (th >= R.parsed.plan) checks.push(["ok", "PLAN", "The plan is met",
        "Expected output " + n2(th) + " per period covers the planned " + n2(R.parsed.plan) + "."]);
      else checks.push(["fail", "PLAN", "The plan is not met",
        "Expected " + n2(th) + " falls short of the planned " + n2(R.parsed.plan) + " by " + n2(R.parsed.plan - th) +
        " per period (" + pct0((R.parsed.plan - th) / R.parsed.plan) + " short)."]);
    } else {
      var minMean = Math.min.apply(null, R.means);
      var capVal = R.capAgg ? R.capAgg.throughput : th;
      var loss = minMean - capVal;
      checks.push(["info", "DEPENDENCE", "What dependence costs",
        "The slowest station averages " + n2(minMean) + " per period on its own. " +
        (R.capAgg ? "Even with an endless supply, the line passes " + n2(capVal)
                  : "As released, the line passes " + n2(capVal)) +
        ": dependence and variability cost " + n2(Math.max(loss, 0)) + " (" + pct0(minMean > 0 ? Math.max(loss, 0) / minMean : 0) + ") before anything else enters it."]);
    }
    return checks;
  }

  function renderVerdict(R) {
    var copy = verdictCopy(R);
    var agg = R.agg, v = R.v;
    $("verdict").className = "panel verdict v-" + v.state;
    $("v-title").textContent = copy.title;
    $("v-body").textContent = copy.body;
    var kpis;
    if (v.reason === "buffer") {
      kpis = [
        [n2(agg.throughput) + " ± " + n2(agg.throughput_half), "units per period expected"],
        [n1(agg.mean_wip), "units in process"],
        [n1(agg.mean_ct), "periods end to end"],
        [pct0(agg.blocked_share[v.blocked_station]), "of periods " + R.names[v.blocked_station] + " is blocked"]
      ];
    } else {
      kpis = [
        [n2(agg.throughput) + " ± " + n2(agg.throughput_half), "units per period expected"],
        [n1(agg.mean_wip), "units in process"],
        [n1(agg.mean_ct), "periods end to end"],
        [pct0(agg.limiting_share[v.bottleneck]), "of periods " + R.names[v.bottleneck] + " limits the line"]
      ];
    }
    $("v-kpis").innerHTML = kpis.map(function (x) {
      return '<div class="kpi"><span class="k-val">' + esc(x[0]) + '</span><span class="k-lbl">' + esc(x[1]) + "</span></div>";
    }).join("");
    $("v-checks").innerHTML = buildChecks(R).map(function (x) {
      return '<div class="check is-' + x[0] + '"><span class="badge">' + esc(x[1]) + '</span><div><span class="c-name">' +
        esc(x[2]) + '.</span> <span class="c-text">' + esc(x[3]) + "</span></div></div>";
    }).join("");
    R.copyText = ["Production line verdict: " + copy.title, copy.body, "",
      "Open with these inputs: " + location.href].join("\n");
  }

  function renderOptionsChart(R) {
    var opts = R.options.slice(0, 8);
    if (!opts.length) { $("chart").innerHTML = ""; $("chart-cap").textContent = ""; return; }
    var labels = opts.map(function (o) {
      var nm = R.names[o.station];
      return (nm.length > 10 ? nm.slice(0, 9) + "…" : nm) + (o.kind === "capacity" ? " +cap" : " +buf");
    });
    Tool.lineChart($("chart"), {
      height: 250, yTitle: "Gain in output per period", aria: "Ranked improvement options",
      series: [{
        points: opts.map(function (o, i) { return [i, o.gain]; }),
        ci: opts.map(function (o) { return [o.gain - o.gain_half, o.gain + o.gain_half]; }),
        bars: true, color: "accent"
      }],
      hLines: [{ y: 0, color: "fg" }],
      xTicks: opts.map(function (_, i) { return i; }), xMin: -0.6, xMax: opts.length - 0.4,
      xFormat: function (x) { return labels[Math.round(x)] || ""; },
      yFormat: function (y) { return n2(y); }
    });
    var top = R.options.slice(0, 3).map(function (o) { return capFirst(optionText(o, R.names, true)); });
    $("chart-cap").textContent = "Best first: " + top.join(" · ") + ".";
  }

  function renderFullNumbers(R) {
    var agg = R.agg, names = R.names;
    var rows = R.tool.stations.map(function (s, i) {
      var kgI = R.kg[i];
      return "<tr><td>" + esc(s.name) + "</td><td>" + n2(R.means[i]) + "</td><td>" +
        (s.die ? "die (≈0.49)" : n2(s.cv)) + "</td><td>" +
        (i === 0 ? "—" : (s.buffer === null ? "no limit" : s.buffer)) + "</td><td>" +
        pct0(agg.limiting_share[i]) + "</td><td>" + pct0(agg.blocked_share[i]) + "</td><td>" +
        pct0(agg.starved_share[i]) + "</td><td>" + n1(agg.mean_buffers[i]) + "</td><td>" +
        (kgI && kgI.queue !== null && kgI.queue !== undefined ? n1(kgI.queue) : "grows") + "</td><td>" +
        (R.means[i] > 0 ? pct0(Math.min(agg.throughput / R.means[i], 1.5)) : "—") + "</td></tr>";
    }).join("");
    var optRows = R.options.map(function (o) {
      return "<tr><td>" + esc(capFirst(optionText(o, names, false))) + "</td><td>" + sg2(o.gain) +
        "</td><td>" + n2(o.gain - o.gain_half) + " to " + n2(o.gain + o.gain_half) + "</td><td>" + n2(o.throughput) + "</td></tr>";
    }).join("");
    $("full-numbers").innerHTML =
      '<div style="overflow-x:auto"><table class="tbl"><thead><tr><th>Station</th><th>Avg output</th><th>CV</th><th>Buffer</th>' +
      "<th>Limits</th><th>Blocked</th><th>Starved</th><th>Queue (sim)</th><th>Queue (Kingman)</th><th>Utilization</th></tr></thead><tbody>" +
      rows + "</tbody></table></div>" +
      '<p class="hint">Shares are fractions of simulated periods in which that station\'s own capacity, its downstream space, or its upstream supply was the binding limit; they need not add to 100%. From ' +
      R.reps + " runs of " + R.periods + " periods each.</p>" +
      "<h4>Every single change, priced</h4>" +
      '<div style="overflow-x:auto"><table class="tbl"><thead><tr><th>Change</th><th>Gain / period</th><th>95% range</th><th>Output after</th></tr></thead><tbody>' +
      optRows + "</tbody></table></div>";
  }

  function renderReleaseTable(R) {
    var labels = { push: "Push", dbr: "Drum-buffer-rope", conwip: "CONWIP" };
    var rows = R.relCmp.map(function (r) {
      var setting = r.rule === "conwip" ? "cap " + r.wip + " in process"
        : r.rule === "dbr" ? "rope " + r.stock + " units ahead of " + R.names[R.v.bottleneck]
        : "release " + n2(r.rate) + " / period";
      return "<tr><td>" + labels[r.rule] + (r.rule === R.tool.release.mode ? " (your rule)" : "") + "</td><td>" + setting +
        "</td><td>" + n2(r.throughput) + " ± " + n2(r.throughput_half) + "</td><td>" + n1(r.mean_wip) + "</td><td>" + n1(r.mean_ct) +
        "</td><td>" + n1(r.wip_if_high) + "</td></tr>";
    }).join("");
    $("release-numbers").innerHTML =
      '<div style="overflow-x:auto"><table class="tbl"><thead><tr><th>Release rule</th><th>Setting</th><th>Output / period</th><th>Work in process</th><th>Cycle time</th><th>Work in process, set 20% high</th></tr></thead><tbody>' +
      rows + "</tbody></table></div>" +
      '<p class="hint">The same line under each rule, each set to make ' + n2(R.relCmp[0].target) + ' a period: 95% of what the line passes when fed without limit. Push releases at exactly that rate, the smoothest push there is; the rope and the CONWIP cap are the smallest that reach it. The last column sets each rule 20% too high: push then releases faster than the line can work, while a pull rule only holds a few more units.</p>';
  }


  /* ---------------- live line ---------------- */
  var live = null, lvTimer = null, lvPlaying = true;
  function buildLive(R) {
    var rec = LS.simulateLine(R.cfg, 480, new LS.LCG(987654321), { record: true });
    live = { rec: rec, pos: 0, out: 0, periods: 0, names: R.names, means: R.means, bn: R.v.bottleneck };
    var host = $("live-line");
    host.innerHTML = "";
    R.names.forEach(function (nm, i) {
      if (i > 0) { var ar = document.createElement("div"); ar.className = "lv-arrow"; ar.textContent = "→"; host.appendChild(ar); }
      var unit = document.createElement("div");
      unit.className = "lv-unit";
      unit.innerHTML = '<div class="lv-pile" id="lv-pile-' + i + '"></div>' +
        '<div class="lv-pile-n" id="lv-pilen-' + i + '"></div>' +
        '<div class="lv-box' + (i === R.v.bottleneck ? " is-bn" : "") + '" id="lv-box-' + i + '">' +
        '<div class="lv-name">' + esc(nm) + '</div><div class="lv-sub" id="lv-sub-' + i + '">avg ' + n2(R.means[i]) + " / period</div></div>";
      host.appendChild(unit);
    });
    var sel = $("lv-station");
    sel.innerHTML = R.names.map(function (nm, i) { return '<option value="' + i + '">' + esc(nm) + "</option>"; }).join("");
    sel.value = String(R.v.bottleneck);
    renderFrame(0);
    $("lv-period").textContent = "0"; $("lv-out").textContent = "0"; $("lv-wip").textContent = "0";
    startLive();
  }
  function renderFrame(pos) {
    if (!live) return;
    var rec = live.rec, n = live.names.length;
    var rest = 0, i;
    for (i = 1; i < n; i++) rest += rec.series_buffers[pos][i - 1];
    for (i = 0; i < n; i++) {
      var count = i === 0 ? rec.series_wip[pos] - rest : rec.series_buffers[pos][i - 1];
      var pile = $("lv-pile-" + i), lab = $("lv-pilen-" + i), box = $("lv-box-" + i), sub = $("lv-sub-" + i);
      if (!pile) continue;
      var dots = "";
      for (var d = 0; d < Math.min(count, 30); d++) dots += '<span class="lv-dot"></span>';
      pile.innerHTML = dots;
      lab.textContent = count > 0 ? count + " waiting" : "";
      var moved = rec.series_station_output[pos][i];
      box.classList.toggle("moved", moved > 0);
      sub.textContent = "avg " + n2(live.means[i]) + " / period" + (moved > 0 ? " · moved " + moved : "");
    }
  }
  function lvTick() {
    if (!live || mode !== "analyze") return;
    var steps = Number($("lv-speed").value), last = live.pos;
    for (var k = 0; k < steps; k++) {
      if (live.pos >= live.rec.series_output.length) { live.pos = 0; live.out = 0; live.periods = 0; }
      live.out += live.rec.series_output[live.pos];
      live.periods++;
      last = live.pos;
      live.pos++;
    }
    renderFrame(last);
    $("lv-period").textContent = String(live.periods);
    $("lv-out").textContent = String(live.out);
    $("lv-wip").textContent = String(live.rec.series_wip[last]);
  }
  function startLive() {
    if (lvTimer || !lvPlaying) return;
    lvTimer = setInterval(lvTick, 150);
  }
  function stopLive() {
    if (lvTimer) { clearInterval(lvTimer); lvTimer = null; }
  }

  /* ---------------- examples ---------------- */
  var EXAMPLES = {
    goal: { st: "Station 1,3.5,die,|Station 2,3.5,die,50|Station 3,3.5,die,50|Station 4,3.5,die,50|Station 5,3.5,die,50", rel: "push", rate: 4, plan: "" },
    plan: { st: "Cut,6,0.2,|Weld,3.6,0.3,10|Polish,4.4,0.25,10|Pack,5,0.2,10", rel: "dbr", stock: 10, plan: "3.8" },
    flood: { st: "Mill,4.2,0.25,|Lathe,3.8,0.3,8|Drill,4.5,0.25,8", rel: "push", rate: 7, plan: "" },
    two: { st: "Saw,5.5,0.25,|Mill,3.4,0.3,8|Lathe,3.45,0.3,8|Pack,5,0.25,8", rel: "conwip", wip: 24, plan: "" },
    slow: { st: "Cut,5.5,0.25,|Weld,4.6,0.3,8|Paint,3.4,0.35,8|Pack,5.2,0.2,8", rel: "push", rate: 3, plan: "" },
    buffer: { st: "Saw,5,0.55,|Mill,3.6,0.2,2|Drill,5,0.25,8|Pack,5.4,0.2,8", rel: "conwip", wip: 20, plan: "" },
    down: { st: "Load,4.5,0.25,|Print,3.8,0.3,8|Unload,0,0.3,8", rel: "push", rate: 3, plan: "" }
  };
  var prevRel = "dbr";
  function syncRelParam() {
    var rel = $("rel").value;
    var labels = { push: "Release rate (units per period)", dbr: "Rope: units allowed at or before the bottleneck", conwip: "Work-in-process cap (units)" };
    $("rel-param-label").textContent = labels[rel];
    $("rel-param").value = relVals[paramKey(rel)];
  }
  function applyExample(key) {
    var ex = EXAMPLES[key];
    if (!ex) return;
    renderRows(parseStationsParam(ex.st));
    if (ex.rate !== undefined) relVals.rate = ex.rate;
    if (ex.stock !== undefined) relVals.stock = ex.stock;
    if (ex.wip !== undefined) relVals.wip = ex.wip;
    $("rel").value = ex.rel; prevRel = ex.rel;
    syncRelParam();
    $("plan").value = ex.plan;
    schedule();
  }

  /* ---------------- data mode ---------------- */
  var SAMPLES = {
    planted: "period,Saw,Mill,Oven,Glaze,Pack\n1,busy,busy,busy,busy,busy\n2,busy,busy,busy,busy,busy\n3,busy,busy,busy,busy,busy\n4,busy,busy,busy,busy,busy\n5,busy,busy,busy,starved,busy\n6,busy,busy,busy,busy,busy\n7,blocked,busy,busy,busy,busy\n8,busy,busy,busy,busy,busy\n9,busy,busy,busy,busy,starved\n10,busy,busy,busy,busy,busy\n11,busy,blocked,busy,busy,busy\n12,busy,busy,busy,busy,busy\n13,busy,busy,busy,busy,busy\n14,busy,busy,busy,busy,busy\n15,busy,busy,busy,busy,busy\n16,busy,busy,busy,starved,busy\n17,busy,busy,busy,busy,busy\n18,busy,busy,busy,busy,busy\n19,blocked,busy,busy,busy,busy\n20,busy,busy,busy,busy,busy\n21,busy,busy,busy,busy,starved\n22,busy,busy,busy,busy,busy\n23,busy,blocked,busy,busy,busy\n24,busy,busy,busy,busy,busy\n25,busy,busy,busy,busy,busy\n26,blocked,busy,busy,busy,busy\n27,busy,busy,busy,busy,busy\n28,busy,busy,busy,starved,busy\n29,busy,busy,busy,busy,busy\n30,busy,busy,busy,busy,busy\n31,busy,busy,busy,busy,starved\n32,busy,busy,busy,busy,busy\n33,busy,busy,busy,busy,busy\n34,busy,blocked,busy,busy,busy\n35,busy,busy,busy,busy,busy\n36,busy,busy,busy,busy,busy\n37,busy,busy,busy,busy,busy\n38,blocked,busy,busy,busy,busy\n39,busy,busy,busy,starved,busy\n40,busy,busy,busy,busy,busy\n41,busy,busy,busy,busy,busy\n42,busy,busy,busy,busy,starved\n43,busy,busy,busy,busy,busy\n44,busy,blocked,busy,busy,busy\n45,busy,busy,busy,busy,busy\n46,busy,busy,busy,busy,busy\n47,blocked,busy,busy,busy,busy\n48,busy,busy,busy,busy,busy\n49,busy,busy,busy,starved,busy\n50,busy,busy,busy,busy,busy\n51,busy,busy,busy,busy,starved\n52,busy,blocked,busy,busy,busy\n53,busy,busy,busy,busy,busy\n54,busy,busy,busy,busy,busy\n55,blocked,busy,busy,busy,busy\n56,busy,busy,busy,busy,busy\n57,busy,busy,busy,starved,busy\n58,busy,busy,busy,busy,busy\n59,busy,busy,busy,busy,busy\n60,busy,busy,busy,busy,busy",
    wandering: "period,Cut,Press,Weld,Kiln,Pack\n1,busy,busy,busy,busy,busy\n2,busy,busy,busy,busy,busy\n3,busy,busy,busy,busy,busy\n4,busy,busy,busy,starved,busy\n5,blocked,busy,blocked,busy,blocked\n6,busy,busy,busy,busy,busy\n7,busy,busy,busy,busy,busy\n8,busy,busy,busy,starved,busy\n9,busy,busy,busy,busy,busy\n10,blocked,busy,blocked,busy,blocked\n11,busy,busy,busy,busy,busy\n12,busy,busy,busy,starved,busy\n13,busy,busy,busy,busy,busy\n14,busy,busy,busy,busy,busy\n15,blocked,busy,blocked,busy,blocked\n16,busy,busy,busy,starved,busy\n17,busy,busy,busy,busy,busy\n18,busy,busy,busy,busy,busy\n19,busy,busy,busy,busy,busy\n20,blocked,busy,blocked,starved,blocked\n21,busy,busy,busy,busy,busy\n22,busy,busy,busy,busy,busy\n23,busy,busy,busy,busy,busy\n24,busy,busy,busy,starved,busy\n25,blocked,busy,blocked,busy,blocked\n26,busy,busy,busy,busy,busy\n27,busy,busy,busy,busy,busy\n28,busy,busy,busy,starved,busy\n29,busy,busy,busy,busy,busy\n30,blocked,busy,blocked,busy,blocked\n31,busy,busy,busy,busy,busy\n32,busy,starved,busy,busy,busy\n33,busy,busy,busy,busy,busy\n34,busy,busy,busy,busy,busy\n35,blocked,busy,blocked,busy,blocked\n36,busy,starved,busy,busy,busy\n37,busy,busy,busy,busy,busy\n38,busy,busy,busy,busy,busy\n39,busy,busy,busy,busy,busy\n40,blocked,starved,blocked,busy,blocked\n41,busy,busy,busy,busy,busy\n42,busy,busy,busy,busy,busy\n43,busy,busy,busy,busy,busy\n44,busy,starved,busy,busy,busy\n45,blocked,busy,blocked,busy,blocked\n46,busy,busy,busy,busy,busy\n47,busy,busy,busy,busy,busy\n48,busy,starved,busy,busy,busy\n49,busy,busy,busy,busy,busy\n50,blocked,busy,blocked,busy,blocked\n51,busy,busy,busy,busy,busy\n52,busy,starved,busy,busy,busy\n53,busy,busy,busy,busy,busy\n54,busy,busy,busy,busy,busy\n55,blocked,busy,blocked,busy,blocked\n56,busy,starved,busy,busy,busy\n57,busy,busy,busy,busy,busy\n58,busy,busy,busy,busy,busy\n59,busy,busy,busy,busy,busy\n60,blocked,starved,blocked,busy,blocked",
    dice: "period,Station 1,Station 2,Station 3,Station 4,Station 5\n1,6,2,2,2,2\n2,2,1,1,1,1\n3,2,5,4,3,3\n4,1,3,2,3,2\n5,5,5,6,2,3\n6,1,1,2,1,1\n7,1,1,1,5,2\n8,6,5,4,5,6\n9,4,1,2,2,4\n10,6,1,1,1,1\n11,6,4,2,2,1\n12,5,6,5,1,2\n13,6,3,1,3,2\n14,5,6,1,3,4\n15,5,2,5,1,1\n16,4,6,5,5,2\n17,6,2,5,6,3\n18,3,6,4,6,3\n19,4,6,2,3,6\n20,4,5,4,3,2\n21,2,6,3,3,1\n22,1,5,1,2,1\n23,1,4,3,3,2\n24,4,4,4,2,4\n25,3,3,2,4,5\n26,2,1,5,4,1\n27,6,4,4,5,6\n28,2,5,1,1,4\n29,4,2,4,2,3\n30,1,2,2,1,4\n31,6,5,3,5,1\n32,2,3,3,3,6\n33,5,3,3,3,2\n34,1,1,2,3,5\n35,4,3,1,1,4\n36,1,4,2,2,1\n37,3,4,1,1,2\n38,2,2,4,4,3\n39,5,5,2,1,1\n40,6,5,5,4,4\n41,4,3,4,5,2\n42,3,5,3,4,1\n43,1,1,4,3,1\n44,2,2,5,5,5\n45,2,2,2,3,5\n46,4,1,1,1,1\n47,1,2,5,5,3\n48,2,4,3,3,6\n49,5,5,1,1,5\n50,2,2,6,4,3"
  };
  function showDataInvalid(msg) {
    lastData = null;
    $("d-verdict").className = "panel verdict v-neutral";
    $("dv-title").textContent = msg || "Check the log";
    $("dv-body").textContent = "";
    $("dv-kpis").innerHTML = "";
    $("dv-checks").innerHTML = "";
    $("d-chart").innerHTML = "";
    $("d-chart-cap").textContent = "";
    $("data-numbers").innerHTML = "";
  }
  function runData() {
    var text = $("log").value;
    var errBox = $("d-form-error");
    if (!text.trim()) { errBox.hidden = true; showDataInvalid("Paste a log to begin"); return; }
    var a;
    try { a = LS.analyzeLog(text); }
    catch (e) {
      errBox.textContent = e.message; errBox.hidden = false;
      showDataInvalid("That log could not be read");
      return;
    }
    errBox.hidden = true;
    var v = LS.verdictData(a);
    var names = a.names, top = a.top, T = a.periods;
    var allActive = a.active_share.every(function (x) { return x >= 0.999; });
    var B = names[top];
    var title, body;
    if (v.reason === "never-active") {
      title = names[v.station] + " never ran in this log.";
      body = names[v.station] + " has no active period in " + T + " periods, so the rest of the line cannot be judged until that is explained: the station may be down, bypassed, or missing from the log's coding.";
    } else if (v.reason === "dominant") {
      title = B + " is the bottleneck in this log.";
      body = B + " held the momentary-bottleneck spot in " + pct0(a.bottleneck_share[top]) + " of the " + T +
        " periods, and was active " + pct0(a.active_share[top]) + " of the time (longest unbroken run: " +
        a.longest_active[top] + " periods). The other stations' runs keep breaking, which is what a line looks like when one station sets its pace.";
    } else if (v.reason === "wandering") {
      title = "The bottleneck moves between " + B + " and " + names[v.second] + ".";
      body = B + " holds the spot in " + pct0(a.bottleneck_share[top]) + " of periods and " + names[v.second] + " in " +
        pct0(a.bottleneck_share[v.second]) + ". When the spot changes hands this often, fixing one station alone mostly moves the problem. Look at the pair, and at what changed partway through the log.";
    } else if (allActive) {
      title = "This log cannot separate the stations.";
      body = "Every station was active in every one of the " + T + " periods, so no station's run ever breaks and the active-period method has nothing to separate them with. A state log (busy, starved, blocked, down), or an output log with zero-output periods, would let it work.";
    } else {
      title = "No station dominates this log.";
      body = "The largest bottleneck share is " + B + " at " + pct0(a.bottleneck_share[top]) + ", with the rest spread across the line. Either the bottleneck genuinely moves, or the log is too short or too coarse to show it.";
    }
    lastData = { a: a, v: v };
    $("d-verdict").className = "panel verdict v-" + v.state;
    $("dv-title").textContent = title;
    $("dv-body").textContent = body;
    var kpis = [
      [pct0(a.bottleneck_share[top]), "of periods " + B + " is the bottleneck"],
      [pct0(a.active_share[top]), "of periods " + B + " was active"],
      [F.int(T), "periods in the log"],
      [F.int(names.length), "stations"]
    ];
    $("dv-kpis").innerHTML = kpis.map(function (x) {
      return '<div class="kpi"><span class="k-val">' + esc(x[0]) + '</span><span class="k-lbl">' + esc(x[1]) + "</span></div>";
    }).join("");
    var checks = [];
    if (allActive) {
      checks.push(["warn", "ACTIVE PERIOD", "This log has no idle time to read",
        "The method works by watching whose unbroken active run is longest. With every station active in every period, all runs grow together and no winner emerges."]);
    } else {
      checks.push(["info", "ACTIVE PERIOD", "Longest unbroken run wins",
        B + " was the momentary bottleneck in " + pct0(a.bottleneck_share[top]) + " of the " + T + " periods. Longest unbroken run in the log: " + B + ", " + a.longest_active[top] + " periods."]);
    }
    var withOut = a.mean_output.map(function (m, i) { return m === null ? -1 : i; }).filter(function (i) { return i >= 0; });
    if (withOut.length) {
      var low = withOut[0];
      withOut.forEach(function (i) { if (a.mean_output[i] < a.mean_output[low]) low = i; });
      if (low === top) checks.push(["info", "FROM DATA", "The averages agree",
        B + " also has the lowest average output (" + n2(a.mean_output[top]) + " per period) of the stations in this log."]);
      else checks.push(["warn", "FROM DATA", "The averages point elsewhere",
        names[low] + " has the lowest average output (" + n2(a.mean_output[low]) + " per period), but the active-period method puts the bottleneck at " +
        B + ". Low output can mean a station is starved, not slow."]);
    } else {
      checks.push(["info", "FROM DATA", "States only",
        "This log records states, not output counts, so there are no averages to compare against the active-period reading."]);
    }
    if (T < 30) checks.push(["warn", "THE LOG", "A short log",
      T + " periods is short for shares: under 30 periods, treat the winner as a lead, not a verdict."]);
    else checks.push(["ok", "THE LOG", "Log read cleanly", T + " periods across " + names.length + " stations."]);
    var idleIdx = 0;
    a.active_share.forEach(function (s, i) { if (s < a.active_share[idleIdx]) idleIdx = i; });
    if (a.active_share[idleIdx] < 0.5 && v.reason !== "never-active") {
      checks.push(["warn", "IDLE TIME", names[idleIdx] + " was mostly idle",
        names[idleIdx] + " was active in only " + pct0(a.active_share[idleIdx]) + " of periods: down, starved, or simply not needed then."]);
    } else if (v.reason !== "never-active") {
      checks.push(["ok", "IDLE TIME", "No station sits idle", "Every station was active at least half of the periods."]);
    }
    $("dv-checks").innerHTML = checks.map(function (x) {
      return '<div class="check is-' + x[0] + '"><span class="badge">' + esc(x[1]) + '</span><div><span class="c-name">' +
        esc(x[2]) + '.</span> <span class="c-text">' + esc(x[3]) + "</span></div></div>";
    }).join("");
    var shortNames = names.map(function (nm) { return nm.length > 10 ? nm.slice(0, 9) + "…" : nm; });
    Tool.lineChart($("d-chart"), {
      height: 230, yTitle: "% of periods as bottleneck", aria: "Bottleneck share by station",
      series: [{ points: a.bottleneck_share.map(function (s, i) { return [i, s * 100]; }), bars: true, color: "accent" }],
      xTicks: names.map(function (_, i) { return i; }),
      xFormat: function (x) { return shortNames[Math.round(x)] || ""; },
      yFormat: function (y) { return F.num(y, 0) + "%"; }
    });
    $("d-chart-cap").textContent = B + " leads with " + pct0(a.bottleneck_share[top]) + " of the " + T + " periods.";
    $("data-numbers").innerHTML =
      '<div style="overflow-x:auto"><table class="tbl"><thead><tr><th>Station</th><th>Avg output</th><th>% active</th><th>% bottleneck</th><th>Longest run</th></tr></thead><tbody>' +
      names.map(function (nm, i) {
        return "<tr><td>" + esc(nm) + "</td><td>" + (a.mean_output[i] === null ? "states only" : n2(a.mean_output[i])) +
          "</td><td>" + pct0(a.active_share[i]) + "</td><td>" + pct0(a.bottleneck_share[i]) + "</td><td>" + a.longest_active[i] + "</td></tr>";
      }).join("") + "</tbody></table></div>";
  }

  function useAverages() {
    var parsed;
    try { parsed = LS.parseLog($("log").value); }
    catch (e) { $("dToast").textContent = "Read the log first."; return; }
    var a = lastData && lastData.a;
    if (!a) return;
    if (a.mean_output.some(function (m) { return m === null; })) {
      $("dToast").textContent = "This log records states, not outputs, for at least one station, so there are no averages to carry over.";
      return;
    }
    var rows = parsed.names.map(function (nm, i) {
      var vals = parsed.outputs.map(function (r) { return r[i]; }).filter(function (x) { return x !== null; });
      var mean = a.mean_output[i], varSel = "some", cvStr = "";
      if (vals.length >= 5 && mean > 0) {
        var sd = Math.sqrt(vals.reduce(function (s, x) { return s + (x - mean) * (x - mean); }, 0) / vals.length);
        var cv = Math.min(sd / mean, 1.5), best = null, bd = 1e9;
        VAR_OPTS.slice(0, 3).forEach(function (o) { var d = Math.abs(cv - o[2]); if (d < bd) { bd = d; best = o[0]; } });
        if (bd <= 0.06) varSel = best; else { varSel = "custom"; cvStr = String(Math.round(cv * 100) / 100); }
      }
      return { name: nm, mean: String(Math.round(mean * 100) / 100), varSel: varSel, cv: cvStr, buf: "" };
    });
    renderRows(rows);
    setMode("analyze");
    $("toast").textContent = "Averages carried over from the log. Variability is estimated from the log's own spread.";
  }

  /* ---------------- mode switching ---------------- */
  function setMode(m) {
    mode = m;
    document.querySelectorAll("[data-mode]").forEach(function (b) {
      var on = b.getAttribute("data-mode") === m;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", String(on));
    });
    $("view-analyze").hidden = m !== "analyze";
    $("view-data").hidden = m !== "data";
    if (m === "analyze") compute();
    else { stopLive(); writeUrl(); runData(); }
  }

  /* ---------------- AI assist ---------------- */
  function nearestPreset(cv) {
    var best = "custom", bd = 1e9;
    VAR_OPTS.slice(0, 3).forEach(function (o) { var d = Math.abs(cv - o[2]); if (d < bd) { bd = d; best = o[0]; } });
    return bd <= 0.06 ? best : "custom";
  }
  Tool.assist(Object.assign({}, window.ASSIST_CONFIG, {
    mount: $("assistMount"), toggle: $("assistToggle"),
    apply: function (vals) {
      document.querySelectorAll("#inputs .filled").forEach(function (el) { el.classList.remove("filled"); });
      if (Array.isArray(vals.stations) && vals.stations.length >= 2) {
        var rowsIn = vals.stations.slice(0, 8).map(function (s, i) {
          s = s || {};
          var row = {
            name: s.name || ("Station " + (i + 1)),
            mean: s.output === null || s.output === undefined ? "" : String(s.output),
            varSel: "some", cv: "",
            buf: s.buffer === null || s.buffer === undefined ? "" : String(s.buffer)
          };
          if (s.die) row.varSel = "die";
          else if (s.cv !== null && s.cv !== undefined && isFinite(Number(s.cv))) {
            var cv = Number(s.cv);
            row.varSel = nearestPreset(cv);
            if (row.varSel === "custom") row.cv = String(Math.round(cv * 100) / 100);
          }
          return row;
        });
        renderRows(rowsIn);
        Array.prototype.forEach.call($("stations").children, function (rowEl, i) {
          var s = vals.stations[i];
          if (!s) return;
          if (s.output !== null && s.output !== undefined) rowEl.querySelector(".stn-mean").classList.add("filled");
          if (s.buffer !== null && s.buffer !== undefined && rowEl.querySelector(".stn-buf")) rowEl.querySelector(".stn-buf").classList.add("filled");
        });
      }
      var rr = String(vals.releaseRule || "").toLowerCase();
      if (["push", "dbr", "conwip"].indexOf(rr) >= 0) {
        $("rel").value = rr; prevRel = rr;
        $("rel").closest(".field").classList.add("filled");
      }
      if (vals.releaseRate !== null && vals.releaseRate !== undefined) relVals.rate = Number(vals.releaseRate);
      if (vals.wipCap !== null && vals.wipCap !== undefined) relVals.wip = Number(vals.wipCap);
      syncRelParam();
      if (vals.plan !== null && vals.plan !== undefined) {
        $("plan").value = vals.plan;
        $("plan").closest(".field").classList.add("filled");
      }
      schedule();
    }
  }));

  /* ---------------- events ---------------- */
  var schedule = debounce(function () { if (mode === "analyze") compute(); }, 350);
  var scheduleData = debounce(runData, 200);
  $("inputs").addEventListener("input", function (e) {
    if (e.target.closest("#assistMount")) return;
    schedule();
  });
  $("inputs").addEventListener("change", function (e) {
    if (e.target.closest("#assistMount")) return;
    schedule();
  });
  $("stations").addEventListener("change", function (e) {
    if (e.target.classList.contains("stn-var")) {
      var row = e.target.closest(".stn-row");
      row.querySelector(".stn-cv").hidden = e.target.value !== "custom";
    }
  });
  $("stations").addEventListener("click", function (e) {
    if (!e.target.classList.contains("stn-del")) return;
    var rows = collectRows();
    if (rows.length <= 2) { $("toast").textContent = "A line keeps at least two stations."; return; }
    var idx = Array.prototype.indexOf.call($("stations").children, e.target.closest(".stn-row"));
    rows.splice(idx, 1);
    renderRows(rows);
    schedule();
  });
  $("add-station").addEventListener("click", function () {
    var rows = collectRows();
    if (rows.length >= 8) return;
    rows.push({ name: "Station " + (rows.length + 1), mean: "4", varSel: "some", cv: "", buf: "" });
    renderRows(rows);
    schedule();
  });
  $("rel").addEventListener("change", function () {
    var pv = Number($("rel-param").value);
    if (isFinite(pv)) relVals[paramKey(prevRel)] = pv;
    prevRel = $("rel").value;
    syncRelParam();
    schedule();
  });
  $("example").addEventListener("change", function () { applyExample($("example").value); });
  $("reps").addEventListener("change", schedule);
  $("periods").addEventListener("change", schedule);
  document.querySelectorAll("[data-mode]").forEach(function (b) {
    b.addEventListener("click", function () { setMode(b.getAttribute("data-mode")); });
  });
  $("copy-summary").addEventListener("click", function () {
    if (!lastResult) return;
    Tool.copy(["Production line verdict: " + $("v-title").textContent, $("v-body").textContent, "",
      "Open with these inputs: " + location.href].join("\n"), $("toast"), "Summary copied.");
  });
  $("copy-link").addEventListener("click", function () {
    writeUrl();
    Tool.copy(location.href, $("toast"), "Link copied: it opens with these inputs.");
  });
  $("lv-toggle").addEventListener("click", function () {
    lvPlaying = !lvPlaying;
    $("lv-toggle").textContent = lvPlaying ? "Pause" : "Resume";
    if (lvPlaying) startLive(); else stopLive();
  });
  $("lv-restart").addEventListener("click", function () {
    if (!live) return;
    live.pos = 0; live.out = 0; live.periods = 0;
    renderFrame(0);
    $("lv-period").textContent = "0"; $("lv-out").textContent = "0"; $("lv-wip").textContent = "0";
  });
  $("lv-addcap").addEventListener("click", function () {
    var i = Number($("lv-station").value);
    var row = $("stations").children[i];
    if (!row) return;
    var meanEl = row.querySelector(".stn-mean"), varSel = row.querySelector(".stn-var");
    var mean = Number(meanEl.value);
    if (!isFinite(mean)) return;
    var delta = Math.max(0.5, Math.round(mean * 0.1 * 10) / 10);
    if (varSel.value === "die") {
      varSel.value = "custom";
      row.querySelector(".stn-cv").hidden = false;
      row.querySelector(".stn-cv").value = "0.49";
      delta = 0.5;
    }
    meanEl.value = String(Math.round((mean + delta) * 10) / 10);
    schedule();
  });
  $("lv-addbuf").addEventListener("click", function () {
    var i = Number($("lv-station").value);
    if (i === 0) { $("toast").textContent = "The first station has no buffer in front of it."; return; }
    var row = $("stations").children[i];
    if (!row) return;
    var bufEl = row.querySelector(".stn-buf");
    if (!bufEl || bufEl.value === "") { $("toast").textContent = "That buffer is already unlimited."; return; }
    var mean = Number(row.querySelector(".stn-mean").value) || 4;
    bufEl.value = String(Number(bufEl.value) + Math.max(4, Math.round(0.5 * mean)));
    schedule();
  });
  $("log").addEventListener("input", scheduleData);
  $("d-example").addEventListener("change", function () {
    var key = $("d-example").value;
    if (key && SAMPLES[key]) { $("log").value = SAMPLES[key]; runData(); }
  });
  $("log-file").addEventListener("change", function () {
    var f = $("log-file").files[0];
    if (!f) return;
    var reader = new FileReader();
    reader.onload = function () { $("log").value = String(reader.result || ""); runData(); };
    reader.readAsText(f);
  });
  $("d-copy-summary").addEventListener("click", function () {
    if (!lastData) return;
    Tool.copy(["Bottleneck from a production log: " + $("dv-title").textContent, $("dv-body").textContent].join("\n"),
      $("dToast"), "Summary copied.");
  });
  $("d-copy-link").addEventListener("click", function () {
    Tool.writeParams({ mode: "data" });
    Tool.copy(location.href, $("dToast"), "Link copied. The log itself is not in the link; it stays in the box.");
  });
  $("use-averages").addEventListener("click", useAverages);
  window.addEventListener("resize", debounce(function () {
    if (mode === "analyze" && lastResult) renderOptionsChart(lastResult);
    if (mode === "data" && lastData) runData();
  }, 200));
  if (window.KitTheme) KitTheme.onChange(debounce(function () {
    if (mode === "analyze" && lastResult) renderOptionsChart(lastResult);
    if (mode === "data" && lastData) runData();
  }, 50));

  /* ---------------- init ---------------- */
  var initStations = parseStationsParam(state.st);
  if (initStations.length < 2) initStations = parseStationsParam(DEFAULT_ST);
  renderRows(initStations);
  if (["push", "dbr", "conwip"].indexOf(state.rel) >= 0) { $("rel").value = state.rel; prevRel = state.rel; }
  else { $("rel").value = "dbr"; prevRel = "dbr"; }
  syncRelParam();
  $("plan").value = state.plan || "";
  if (["12", "20", "32"].indexOf(String(state.reps)) >= 0) $("reps").value = String(state.reps);
  if (["200", "300", "500"].indexOf(String(state.periods)) >= 0) $("periods").value = String(state.periods);
  $("log").value = SAMPLES.planted;
  Tool.explain({
    mean: { t: "Output per period", d: "How many units this station finishes in one period when it has work to do, on average. In The Goal's dice game, a fair die averages 3.5." },
    cv: { t: "Variability", d: "How much a station's output swings from period to period, as the coefficient of variation (standard deviation ÷ average). Low ≈ 0.1, some ≈ 0.25, high ≈ 0.5; pick Custom to type your own. Variability is why a line makes less than its slowest station's average: a bad period starves the next station, and a good period cannot be banked without a buffer." },
    buf: { t: "Buffer in front", d: "How many waiting units fit in front of this station. When the buffer is full, the station before it is blocked and has to stop. Leave it blank for unlimited space." },
    release: { t: "How work is released", d: "<b>Push</b>: release a fixed amount each period. <b>Drum-buffer-rope</b> (from The Goal): let in new work only when the bottleneck has room, so the bottleneck sets the pace (the drum), a small queue protects it (the buffer), and releases are tied to it (the rope). <b>CONWIP</b>: keep the total number of units in the line fixed; one finishes, one enters." },
    watch: { t: "Watch it run", d: "A replay of one simulated run, period by period. Dots are units waiting in front of each station; a growing queue sits in front of the station holding the line back. The red frame is the bottleneck from the verdict." },
    pays: { t: "Where the next change pays", d: "Each bar is one single change (add capacity at a station, or add buffer space), tested on the same random draws as the current line (common random numbers), so the difference reflects the change, not luck. Whiskers are 95% ranges: if a range crosses zero, the gain is not proven." },
    share: { t: "Bottleneck share", d: "The share of periods in which each station was the bottleneck, by the active-period method (Roser, Nakano and Tanaka): at each moment, the station that has been working without a break the longest is the one holding the line back." }
  });

  setMode(mode);
})();
