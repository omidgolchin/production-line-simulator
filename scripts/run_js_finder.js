/* Run the finder fixtures through docs/linesim.js and print results
 * as JSON on stdout. Used by tests/test_js_agreement.py to check the
 * JavaScript analysis layer (tool config, aggregates, Kingman,
 * improvement options, release comparison, log analysis, verdicts)
 * against the Python reference in src/linesim/finder.py. */
"use strict";
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const L = require(path.join(root, "docs", "linesim.js"));
const cases = JSON.parse(
  fs.readFileSync(path.join(root, "tests", "fixtures", "finder_cases.json"),
                  "utf8"));

function clean(o) {
  if (typeof o === "number") return isFinite(o) ? o : null;
  if (Array.isArray(o)) return o.map(clean);
  if (o && typeof o === "object") {
    const out = {};
    for (const k of Object.keys(o)) out[k] = clean(o[k]);
    return out;
  }
  return o;
}

const out = { analyze: [], logs: [], verdicts: [], data_verdicts: [] };
for (const c of cases.analyze || []) {
  const cfg = L.toolConfig(c.tool);
  const agg = L.analyzeLine(cfg, c.opts);
  delete agg.rep_throughputs;
  out.analyze.push({
    name: c.name,
    agg: agg,
    kingman: L.kingman(cfg, agg.throughput),
    options: L.improvementOptions(cfg, c.opts),
    release: L.releaseComparison(cfg, c.opts)
  });
}
for (const c of cases.logs || []) {
  out.logs.push({ name: c.name, analysis: L.analyzeLog(c.text) });
}
for (const c of cases.verdicts || []) {
  out.verdicts.push({ name: c.name, verdict: L.verdict(c.summary) });
}
for (const c of cases.data_verdicts || []) {
  out.data_verdicts.push({ name: c.name, verdict: L.verdictData(c.log) });
}
process.stdout.write(JSON.stringify(clean(out)));
