/* The AI assist's prompt configuration: what the model is asked to extract.
 * Shared by the page (app.js) and the extraction test (scripts/eval_assist.js),
 * so the test scores exactly the prompt visitors get. */
(function (g) {
  "use strict";
  var ASSIST_CONFIG = {
    title: "Fill from my description.",
    lede: "Describe your line in your own words, or paste a shift report. The model only fills the form; every value shows the phrase it came from, and you choose what to keep.",
    placeholder: "e.g. Cutting averages 42 units an hour and is steady. Welding does about 35 an hour, varies, and has room for 12 units in front of it. Packing runs 40 an hour. We push 30 an hour into the line and the plan says 28.",
    examples: [
      { label: "A description", text: "Our line has three stations. Cutting averages 42 units an hour and is steady. Welding does about 35 an hour, varies, and has room for 12 units in front of it. Packing runs 40 an hour, steady, with space for 8 in front." },
      { label: "A shift report", text: "Shift report, Line 4 (8-hour shifts). Saw: 320 per shift, steady. Mill: 38 per hour. Drill press: 240 per shift, varies a lot. Assembly: 45 per hour, varies. There is room for 20 in front of the drill press." }
    ],
    instructions:
      "The tool analyzes a production line: a row of stations that each " +
      "complete some units per period. Extract what the text states. " +
      "The stations field holds one object per station, in line order, " +
      "with keys in exactly this order: name, output, cv, buffer, die. " +
      "Include every station the text names, even when its numbers are " +
      "missing (use nulls). If stations are unnamed, call them Station " +
      "1, Station 2, and so on. output is units completed per period. " +
      "All stations must share one period: if rates mix per hour and " +
      "per shift (or per day) and the shift or day length in hours is " +
      "stated, convert the shift or day rates to per hour by dividing " +
      "by that length. If a station works in batches (a batch of B " +
      "units every H hours, or a batch cycle of M minutes holding B " +
      "units), output is B divided by the hours per batch. If a " +
      "station is described by the time one unit takes (T minutes per " +
      "part) and the period is the hour, output is 60 / T. If output " +
      "is a range (low to high), output is the midpoint. cv is the " +
      "coefficient of variation of the station's output: use a cv the " +
      "text gives directly; variability words map to steady or " +
      "consistent = 0.15, varies or some variation = 0.3, varies a " +
      "lot, very erratic or all over the place = 0.55. If a range is " +
      "given and no variability word, cv is 0.58 times (high minus " +
      "low) divided by (high plus low), rounded to two decimals; if " +
      "both a range and a variability word are given, the word wins. " +
      "For a time-per-unit range, use the midpoint time for output " +
      "and apply the range rule to the two implied outputs. If no " +
      "variability is stated, cv is null. buffer is the number of " +
      "units that can wait in front of the station; it is null when " +
      "the text gives no finite number, including when it says the " +
      "space is unlimited. If a station is a die roll or a dice-game " +
      "station, die is true, output is 3.5 and cv is 0.49; otherwise " +
      "die is false. releaseRule is 'push' when work is released into " +
      "the line at a stated rate or on a schedule, 'conwip' when a " +
      "cap on the total units in the line is stated, 'dbr' when " +
      "releases are paced by the bottleneck station, and null when " +
      "the text does not say. releaseRate is the stated push release " +
      "rate, else null. wipCap is the stated cap on units in the " +
      "line, else null. plan is a planned or target output per period " +
      "when the text states one, else null.",
    fields: [
      { key: "stations", label: "Stations in line order: name, output per period, variability (cv), buffer space in front, die station", type: "array",
        format: function (v) {
          if (!Array.isArray(v)) return String(v);
          return v.map(function (s) {
            if (!s || typeof s !== "object") return "one station unclear";
            var bits = [s.name || "Station"];
            if (s.die) bits.push("die roll");
            else if (s.output !== null && s.output !== undefined) bits.push(s.output + " per period");
            if (s.cv !== null && s.cv !== undefined && !s.die) bits.push("cv " + s.cv);
            if (s.buffer !== null && s.buffer !== undefined) bits.push("buffer " + s.buffer);
            return bits.join(", ");
          }).join("; ");
        } },
      { key: "releaseRule", label: "How work is released: push, dbr or conwip", type: "text" },
      { key: "releaseRate", label: "Release rate in units per period, for push", type: "number" },
      { key: "wipCap", label: "Cap on units in the line, for conwip", type: "number" },
      { key: "plan", label: "Planned or target output per period, if the text states one", type: "number" }
    ]
  };
  if (typeof module !== "undefined" && module.exports) module.exports = ASSIST_CONFIG;
  g.ASSIST_CONFIG = ASSIST_CONFIG;
})(typeof window !== "undefined" ? window : globalThis);
