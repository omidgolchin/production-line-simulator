/* Run the agreement fixtures through docs/linesim.js and print the
 * resulting series as JSON on stdout. Used by
 * tests/test_js_agreement.py. */
"use strict";
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const { LCG, simulateLine } = require(path.join(root, "docs", "linesim.js"));
const cases = JSON.parse(
  fs.readFileSync(path.join(root, "tests", "fixtures", "agreement.json"),
                  "utf8"));

const out = cases.map((c) => {
  const res = simulateLine(c.config, c.periods, new LCG(c.seed), { record: true });
  return {
    name: c.name,
    series_output: res.series_output,
    series_wip: res.series_wip,
    series_buffers: res.series_buffers,
    series_station_output: res.series_station_output,
    series_caps: res.series_caps,
  };
});
process.stdout.write(JSON.stringify(out));
