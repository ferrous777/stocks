// Interactive price chart for the symbol page (no dependencies).
//
// Markup: <div class="price-chart" data-chart-src="ID"> with a <script type="application/json" id="ID">
// holding {dates: ["YYYY-MM-DD", ...], closes: [...]} (split-adjusted daily closes). The server-drawn
// <svg> inside .price-chart__plot is the no-JS fallback and is replaced on load.
//
// Two modes:
//   Range         - one line of closes over a preset (6M, YTD, 1Y, 3Y, 5Y, All) or "from <year> to present".
//   Compare years - each selected calendar year on a shared Jan-Dec axis, as % change from the previous
//                   year's last close (the first year on file starts from its first close). One y-axis.
//
// The view lives in the URL so it can be linked to: ?range=5Y, ?from=2020 (2020 to present) or
// ?compare=2020,2021,2022 (compare mode with those years; only the most recent eight are offered).
// Options on the container: data-chart-label (series name, default "Close") and data-chart-modes
// ("range" hides the Compare years mode, e.g. for an equity curve).
(function () {
  "use strict";
  var SVGNS = "http://www.w3.org/2000/svg";
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var MAX_YEARS = 8;            // eight categorical slots; color follows the year, never its rank
  var PAD = { top: 12, right: 56, bottom: 26, left: 8 };

  function el(name, attrs, parent) {
    var n = document.createElementNS(SVGNS, name);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function h(tag, attrs, text) {
    var n = document.createElement(tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    return n;
  }
  function parseDate(s) { return new Date(s + "T00:00:00Z"); }
  function fmtPrice(v) { return v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function fmtPct(v) { return (v >= 0 ? "+" : "") + (v * 100).toFixed(1) + "%"; }
  function fmtDate(d) { return d.toISOString().slice(0, 10); }
  // Position on the shared Jan-Dec axis. Every year is mapped onto leap year 2000, so the same calendar
  // date lines up across years (Mar 1 is day 60 in 2023 and 2024 alike) and Feb 29 keeps its own slot.
  var REF_YEAR = 2000, YEAR_DAYS = 365;   // Dec 31 of the reference year is day 365
  function dayOfYear(d) { return (Date.UTC(REF_YEAR, d.getUTCMonth(), d.getUTCDate()) - Date.UTC(REF_YEAR, 0, 1)) / 864e5; }

  // "Nice" axis ticks covering [lo, hi].
  function ticks(lo, hi, count) {
    var span = hi - lo || Math.abs(hi) || 1, raw = span / count, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var step = [1, 2, 2.5, 5, 10].map(function (m) { return m * mag; }).find(function (s) { return s >= raw; });
    var out = [];
    for (var v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  }

  function PriceChart(root) {
    var data = JSON.parse(document.getElementById(root.dataset.chartSrc).textContent);
    this.root = root;
    this.pts = data.dates.map(function (s, i) { return { d: parseDate(s), c: data.closes[i] }; });
    this.years = [];
    var seen = {};
    this.pts.forEach(function (p) { var y = p.d.getUTCFullYear(); if (!seen[y]) { seen[y] = 1; this.years.push(y); } }, this);
    // Compare mode offers the most recent eight years; each keeps one color slot.
    this.compareYears = this.years.slice(-MAX_YEARS);
    var last = this.compareYears.length;
    this.selectedYears = this.compareYears.slice(Math.max(0, last - 3));   // default: the last three years
    this.label = root.dataset.chartLabel || "Close";
    this.modes = (root.dataset.chartModes || "range years").split(" ");
    this.mode = "range";
    this.range = "1Y";
    this.fromYear = null;
    this.readUrl();
    this.build();
    this.render();
    var self = this;
    if (window.ResizeObserver) new ResizeObserver(function () { self.render(); }).observe(this.plot);
  }

  var RANGES = ["6M", "YTD", "1Y", "3Y", "5Y", "All"], DEFAULT_RANGE = "1Y";

  // Initial view from the query string; anything unknown is ignored (the default view is shown).
  PriceChart.prototype.readUrl = function () {
    var q;
    try { q = new URLSearchParams(window.location.search); } catch (e) { return; }
    var self = this;
    if (q.get("compare") && this.modes.indexOf("years") >= 0) {
      var want = q.get("compare").split(",").map(Number).filter(function (y) { return self.compareYears.indexOf(y) >= 0; });
      if (want.length) { this.mode = "years"; this.selectedYears = want; return; }
    }
    var from = Number(q.get("from"));
    if (from && this.years.indexOf(from) >= 0) { this.fromYear = from; this.range = null; return; }
    if (RANGES.indexOf(q.get("range")) >= 0) this.range = q.get("range");
  };

  // Keep the address bar in step with the view, so copying the URL links to exactly this chart.
  PriceChart.prototype.writeUrl = function () {
    try {
      var q = new URLSearchParams(window.location.search);
      ["range", "from", "compare"].forEach(function (k) { q.delete(k); });
      if (this.mode === "years") q.set("compare", this.selectedYears.slice().sort().join(","));
      else if (this.fromYear) q.set("from", this.fromYear);
      else if (this.range && this.range !== DEFAULT_RANGE) q.set("range", this.range);
      var qs = q.toString();
      window.history.replaceState(null, "", window.location.pathname + (qs ? "?" + qs : "") + window.location.hash);
    } catch (e) { /* history unavailable (e.g. sandboxed preview): the chart still works */ }
  };

  PriceChart.prototype.build = function () {
    var self = this, root = this.root;
    var controls = root.querySelector(".price-chart__controls");
    controls.hidden = false;

    // Mode switch
    this.modeButtons = {};
    var modes = h("div", { class: "segmented", role: "group", "aria-label": "Chart mode" });
    [["range", "Range"], ["years", "Compare years"]].filter(function (m) { return self.modes.indexOf(m[0]) >= 0; }).forEach(function (m) {
      var b = h("button", { type: "button", class: "segmented__item" }, m[1]);
      b.addEventListener("click", function () { self.mode = m[0]; self.render(); });
      self.modeButtons[m[0]] = b;
      modes.appendChild(b);
    });
    if (this.modes.length > 1) controls.appendChild(modes);

    // Range presets + "from year"
    this.rangeBox = h("div", { class: "cluster" });
    var presets = h("div", { class: "segmented", role: "group", "aria-label": "Range" });
    this.rangeButtons = {};
    RANGES.forEach(function (r) {
      var b = h("button", { type: "button", class: "segmented__item" }, r);
      b.addEventListener("click", function () { self.range = r; self.fromYear = null; self.yearSelect.value = ""; self.render(); });
      self.rangeButtons[r] = b;
      presets.appendChild(b);
    });
    this.rangeBox.appendChild(presets);
    var label = h("label", { class: "small muted cluster" }, "From ");
    this.yearSelect = h("select", { class: "input btn--sm", "aria-label": "From year to present" });
    this.yearSelect.appendChild(h("option", { value: "" }, "year…"));
    this.years.slice().reverse().forEach(function (y) { self.yearSelect.appendChild(h("option", { value: y }, y + "–present")); });
    this.yearSelect.addEventListener("change", function () {
      self.fromYear = self.yearSelect.value ? +self.yearSelect.value : null;
      self.range = self.fromYear ? null : DEFAULT_RANGE;
      self.render();
    });
    label.appendChild(this.yearSelect);
    if (this.years.length > 1) this.rangeBox.appendChild(label);   // "from <year>" needs more than one year
    controls.appendChild(this.rangeBox);

    // Year toggles (they double as the legend in compare mode)
    this.yearBox = h("div", { class: "cluster", role: "group", "aria-label": "Years to compare" });
    this.yearButtons = {};
    this.compareYears.forEach(function (y, i) {
      var b = h("button", { type: "button", class: "chart-chip", style: "--chip-color: var(--series-" + (i + 1) + ")" });
      b.appendChild(h("span", { class: "chart-chip__swatch", "aria-hidden": "true" }));
      b.appendChild(document.createTextNode(String(y)));
      b.addEventListener("click", function () {
        var at = self.selectedYears.indexOf(y);
        if (at >= 0) { if (self.selectedYears.length > 1) self.selectedYears.splice(at, 1); }
        else self.selectedYears.push(y);
        self.render();
      });
      self.yearButtons[y] = b;
      self.yearBox.appendChild(b);
    });
    controls.appendChild(this.yearBox);

    this.plot = root.querySelector(".price-chart__plot");
    this.caption = root.querySelector(".price-chart__caption");
    this.tip = h("div", { class: "chart-tooltip", role: "status", "aria-live": "polite", hidden: "" });
    this.plot.appendChild(this.tip);
  };

  // Series to draw: [{key, label, color, values: [{x, y, d, c}]}] plus axis kinds.
  PriceChart.prototype.series = function () {
    var pts = this.pts;
    if (this.mode === "range") {
      var end = pts[pts.length - 1].d, start;
      if (this.fromYear) start = new Date(Date.UTC(this.fromYear, 0, 1));
      else if (this.range === "All") start = pts[0].d;
      else if (this.range === "YTD") start = new Date(Date.UTC(end.getUTCFullYear(), 0, 1));
      else {
        var months = { "6M": 6, "1Y": 12, "3Y": 36, "5Y": 60 }[this.range];
        start = new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth() - months, end.getUTCDate()));
      }
      var sel = pts.filter(function (p) { return p.d >= start; });
      var base = sel.length ? sel[0].c : null;
      return { kind: "price", series: [{ key: "close", label: this.label, color: "var(--color-accent)",
        values: sel.map(function (p) { return { x: +p.d, y: p.c, d: p.d, c: p.c, chg: p.c / base - 1 }; }) }] };
    }
    var self = this, prevClose = {};
    var byYear = {};
    pts.forEach(function (p) { (byYear[p.d.getUTCFullYear()] = byYear[p.d.getUTCFullYear()] || []).push(p); });
    this.years.forEach(function (y, i) { if (i > 0) { var prev = byYear[self.years[i - 1]]; prevClose[y] = prev[prev.length - 1].c; } });
    var series = this.compareYears.filter(function (y) { return self.selectedYears.indexOf(y) >= 0; }).map(function (y) {
      var rows = byYear[y], base = prevClose[y] != null ? prevClose[y] : rows[0].c;
      return { key: y, label: String(y), color: "var(--series-" + (self.compareYears.indexOf(y) + 1) + ")",
        values: rows.map(function (p) { return { x: dayOfYear(p.d), y: p.c / base - 1, d: p.d, c: p.c }; }) };
    });
    return { kind: "pct", series: series };
  };

  PriceChart.prototype.render = function () {
    var self = this;
    // controls state
    Object.keys(this.modeButtons).forEach(function (m) { self.modeButtons[m].setAttribute("aria-pressed", String(self.mode === m)); });
    Object.keys(this.rangeButtons).forEach(function (r) { self.rangeButtons[r].setAttribute("aria-pressed", String(!self.fromYear && self.range === r)); });
    this.rangeBox.hidden = this.mode !== "range";
    this.yearBox.hidden = this.mode !== "years";
    this.compareYears.forEach(function (y) { self.yearButtons[y].setAttribute("aria-pressed", String(self.selectedYears.indexOf(y) >= 0)); });
    if (this.yearSelect) this.yearSelect.value = this.fromYear ? String(this.fromYear) : "";
    this.writeUrl();

    var spec = this.series(), all = [];
    spec.series.forEach(function (s) { all = all.concat(s.values); });
    var old = this.plot.querySelector("svg");
    if (old) old.remove();
    this.tip.hidden = true;
    if (all.length < 2) { this.caption.textContent = "Not enough sessions in this range."; return; }

    var W = Math.max(280, this.plot.clientWidth), H = Math.round(Math.min(420, Math.max(220, W * 0.42)));
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, class: "chart-svg", role: "img" });
    var x0, x1;
    if (spec.kind === "pct") { x0 = 0; x1 = YEAR_DAYS; }
    else { x0 = all[0].x; x1 = all[all.length - 1].x; }
    var ys = all.map(function (v) { return v.y; });
    var lo = Math.min.apply(null, ys), hi = Math.max.apply(null, ys);
    if (spec.kind === "pct") { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    var pad = (hi - lo) * 0.06 || Math.abs(hi) * 0.05 || 1; lo -= pad; hi += pad;
    var iw = W - PAD.left - PAD.right, ih = H - PAD.top - PAD.bottom;
    var sx = function (x) { return PAD.left + (x - x0) / ((x1 - x0) || 1) * iw; };
    var sy = function (y) { return PAD.top + (hi - y) / (hi - lo) * ih; };

    // grid + y labels (right side)
    var grid = el("g", { class: "chart-grid" }, svg);
    ticks(lo, hi, 5).forEach(function (t) {
      el("line", { x1: PAD.left, x2: PAD.left + iw, y1: sy(t), y2: sy(t), class: t === 0 && spec.kind === "pct" ? "chart-zero" : "" }, grid);
      var lab = el("text", { x: PAD.left + iw + 6, y: sy(t) + 4, class: "chart-axis" }, grid);
      lab.textContent = spec.kind === "pct" ? fmtPct(t) : fmtPrice(t);
    });
    // x labels
    var xl = el("g", { class: "chart-axis" }, svg);
    if (spec.kind === "pct") {
      MONTHS.forEach(function (m, i) {
        var x = sx(dayOfYear(new Date(Date.UTC(REF_YEAR, i, 1))));
        if (W < 520 && i % 3) return;
        var t = el("text", { x: x, y: H - 8 }, xl); t.textContent = m;
      });
    } else {
      var n = Math.max(2, Math.floor(iw / 110)), span = x1 - x0;
      for (var i = 0; i <= n; i++) {
        var d = new Date(x0 + span * i / n), years = span / 31536e6;
        var t = el("text", { x: sx(+d), y: H - 8, "text-anchor": i === 0 ? "start" : i === n ? "end" : "middle" }, xl);
        t.textContent = years > 3 ? String(d.getUTCFullYear())
          : span < 120 * 864e5 ? MONTHS[d.getUTCMonth()] + " " + d.getUTCDate()     // short spans: day labels
          : MONTHS[d.getUTCMonth()] + " " + String(d.getUTCFullYear()).slice(2);
      }
    }
    // lines
    spec.series.forEach(function (s) {
      var dpath = s.values.map(function (v, i) { return (i ? "L" : "M") + sx(v.x).toFixed(1) + "," + sy(v.y).toFixed(1); }).join("");
      el("path", { d: dpath, class: "chart-line", style: "stroke:" + s.color }, svg);
    });
    // direct labels at line ends (<= 4 series)
    if (spec.kind === "pct" && spec.series.length <= 4) {
      spec.series.forEach(function (s) {
        var v = s.values[s.values.length - 1];
        var t = el("text", { x: Math.min(sx(v.x) + 4, PAD.left + iw - 2), y: sy(v.y) - 6, class: "chart-label",
                             "text-anchor": sx(v.x) > PAD.left + iw - 40 ? "end" : "start" }, svg);
        t.textContent = s.label;
      });
    }
    // hover + keyboard layer: the same crosshair and tooltip for pointer and keys
    var hair = el("line", { y1: PAD.top, y2: PAD.top + ih, class: "chart-hair", visibility: "hidden" }, svg);
    var dots = spec.series.map(function (s) { return el("circle", { r: 4, class: "chart-dot", style: "fill:" + s.color, visibility: "hidden" }, svg); });
    var hit = el("rect", { x: PAD.left, y: PAD.top, width: iw, height: ih, fill: "transparent" }, svg);
    // Keyboard stops: every distinct x that has a value, in order.
    var stops = all.map(function (v) { return v.x; }).sort(function (a, b) { return a - b; })
      .filter(function (x, i, arr) { return i === 0 || x !== arr[i - 1]; });
    var cursor = stops.length - 1;
    function nearest(values, x) {
      var lo = 0, hi = values.length - 1;
      while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (values[mid].x < x) lo = mid; else hi = mid; }
      return Math.abs(values[lo].x - x) <= Math.abs(values[hi].x - x) ? values[lo] : values[hi];
    }
    function showAt(x) {
      var r = svg.getBoundingClientRect();
      var rows = [];
      spec.series.forEach(function (s, i) {
        var v = nearest(s.values, x);
        if (spec.kind === "pct" && Math.abs(v.x - x) > 7) { dots[i].setAttribute("visibility", "hidden"); return; }
        dots[i].setAttribute("cx", sx(v.x)); dots[i].setAttribute("cy", sy(v.y)); dots[i].setAttribute("visibility", "visible");
        rows.push({ s: s, v: v });
      });
      if (!rows.length) return;
      var hx = sx(rows[0].v.x);
      hair.setAttribute("x1", hx); hair.setAttribute("x2", hx); hair.setAttribute("visibility", "visible");
      self.tip.textContent = "";
      if (spec.kind === "price") {
        var v = rows[0].v;
        self.tip.appendChild(h("div", { class: "chart-tooltip__title" }, fmtDate(v.d)));
        self.tip.appendChild(h("div", {}, self.label + " " + fmtPrice(v.c)));
        self.tip.appendChild(h("div", { class: "muted" }, fmtPct(v.chg) + " since range start"));
      } else {
        var md = rows[0].v.d;
        self.tip.appendChild(h("div", { class: "chart-tooltip__title" }, MONTHS[md.getUTCMonth()] + " " + md.getUTCDate()));
        rows.sort(function (a, b) { return b.v.y - a.v.y; }).forEach(function (r) {
          var line = h("div", { class: "chart-tooltip__row" });
          line.appendChild(h("span", { class: "chart-chip__swatch", style: "--chip-color:" + r.s.color, "aria-hidden": "true" }));
          line.appendChild(document.createTextNode(r.s.label + "  " + fmtPct(r.v.y) + "  (" + fmtPrice(r.v.c) + ")"));
          self.tip.appendChild(line);
        });
      }
      self.tip.hidden = false;
      var tw = self.tip.offsetWidth, left = hx / W * r.width + 12;
      if (left + tw > r.width) left = hx / W * r.width - tw - 12;
      self.tip.style.left = Math.max(0, left) + "px";
    }
    function fromPointer(ev) {
      var r = svg.getBoundingClientRect(), px = (ev.clientX - r.left) * (W / r.width);
      showAt(x0 + (px - PAD.left) / iw * (x1 - x0));
    }
    function leave() {
      hair.setAttribute("visibility", "hidden");
      dots.forEach(function (d) { d.setAttribute("visibility", "hidden"); });
      self.tip.hidden = true;
    }
    hit.addEventListener("pointermove", fromPointer);
    hit.addEventListener("pointerdown", fromPointer);
    hit.addEventListener("pointerleave", function () { if (document.activeElement !== svg) leave(); });
    svg.setAttribute("tabindex", "0");
    svg.addEventListener("focus", function () { showAt(stops[cursor]); });
    svg.addEventListener("blur", leave);
    svg.addEventListener("keydown", function (ev) {
      var step = { ArrowLeft: -1, ArrowRight: 1, PageUp: -20, PageDown: 20 }[ev.key];
      if (ev.key === "Home") cursor = 0;
      else if (ev.key === "End") cursor = stops.length - 1;
      else if (step) cursor = Math.max(0, Math.min(stops.length - 1, cursor + step));
      else return;
      ev.preventDefault();
      showAt(stops[cursor]);
    });

    // accessible name + caption
    var cap;
    if (spec.kind === "price") {
      var a = spec.series[0].values, f = a[0], l = a[a.length - 1];
      cap = fmtDate(f.d) + " to " + fmtDate(l.d) + ": " + fmtPrice(f.c) + " → " + fmtPrice(l.c) + " (" + fmtPct(l.c / f.c - 1) + ")";
    } else {
      cap = spec.series.map(function (s) { var v = s.values[s.values.length - 1]; return s.label + " " + fmtPct(v.y); }).join(" · ") +
            " — change from the previous year's last close";
    }
    svg.setAttribute("aria-label", cap + ". Use the arrow keys, Page Up/Down, Home and End to read each session's values.");
    this.caption.textContent = cap;
    this.plot.insertBefore(svg, this.tip);
  };

  document.querySelectorAll(".price-chart[data-chart-src]").forEach(function (root) { new PriceChart(root); });
})();
