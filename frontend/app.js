const $ = (id) => document.getElementById(id);
const fmt = (value, digits = 0) => value == null ? "Unknown" : Number(value).toLocaleString("en-GB", { maximumFractionDigits: digits });
const pct = (value) => value == null ? "Unknown" : `${fmt(value * 100, 1)}%`;
const marketName = (slug) => slug.split("-").map((word) => word[0].toUpperCase() + word.slice(1)).join(" ");
const date = (value) => {
  const instant = new Date(value);
  const day = instant.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).replace(/\bSept\b/, "Sep");
  const time = instant.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "UTC" });
  return `${day} at ${time} UTC`;
};
const fieldLabel = { critical_it_mw: "IT load", it_area_sqft: "IT floor area", onsite_carriers: "Carriers" };
const units = { critical_it_mw: " MW", it_area_sqft: " ft²", onsite_carriers: "" };
const origins = { card: "Market listing", detail_main: "Facility headline", detail_specs: "Facility specification" };
let report, facilities = [], sortKey = "facility_code", ascending = true, showAllMarkets = false, csvUrl, lastTrigger;

// These reading notes apply only to the exact saved pages reviewed for this study.
const sourceNotes = {
  DFW1: {
    sha256: "1daf264c8bc9338dcd77f5a962e1b10855ed4416689bc0924afcef871c385d13",
    title: "Connectivity in downtown Dallas",
    text: "The description emphasises its role as a carrier hotel, with connections to another major carrier hotel in Dallas.",
  },
  DFW8: {
    sha256: "e32e7a90ee090dcfc173396d21f1db90550a0d112b1df6706f1422522692c43e",
    title: "High-power cooling in Plano",
    text: "The page promotes high-power air and liquid cooling and HPC infrastructure.",
    caveat: "The page also says “Coming Soon”. Its main figures list 40 MW, while a highlights block lists 40.5 MW. We use 40 MW here.",
  },
  DFW12: {
    sha256: "e197c84d63cc2d642e1cc63edf53f7eac9e576ce6780ec5f1d2fce82f8a0c29f",
    text: "The saved description uses future tense. It does not confirm whether the facility is open or has capacity available to rent.",
  },
};
function reviewedNote(code) {
  const note = sourceNotes[code];
  const claims = report.breakdowns.facility_evidence[code] ?? [];
  return note && claims.some((claim) => claim.origin === "detail_main" && claim.sha256 === note.sha256) ? note : null;
}

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function link(text, url) {
  const element = node("a", text);
  const parsed = new URL(url, location.origin);
  if (["https:", "http:"].includes(parsed.protocol)) element.href = parsed.href;
  element.target = "_blank";
  element.rel = "noopener noreferrer";
  return element;
}
function metric(label, value) {
  const wrap = node("div");
  wrap.append(node("dt", label), node("dd", value));
  return wrap;
}
function listItem(parent, text, url) {
  const item = node("li", text);
  if (url) item.append(" ", link("Source ↗", url));
  parent.append(item);
}
function proportion(label, share) {
  const wrap = node("div", null, "proportion");
  const labels = node("div", null, "proportion-label");
  labels.append(node("span", label), node("strong", pct(share)));
  const track = node("div", null, "track"), fill = node("span", null, "fill");
  fill.style.width = `${Math.max(0, Math.min(100, (share ?? 0) * 100))}%`;
  track.setAttribute("aria-hidden", "true");
  track.append(fill); wrap.append(labels, track);
  return wrap;
}
function conflictText(item) {
  const unit = units[item.field] ?? "";
  return `${marketName(new URL(item.source_url).pathname.split("/").filter(Boolean).at(-1))}: ${item.origin === "faq" ? "FAQ" : "headline"} states ${item.raw_value}; individual facilities total ${fmt(item.facility_sum, 3)}${unit}.`;
}

function renderOverview() {
  const s = report.summary, q = report.quality, c = q.carrier_coverage;
  const reportTime = node("time", date(report.as_of));
  reportTime.dateTime = report.as_of;
  $("collection").replaceChildren(node("span", report.source.data_kind === "synthetic" ? "Synthetic example" : "Latest report", "report-label"), " ", reportTime);
  $("run-id").textContent = `Dataset version ${report.run_id}`;
  $("totals").replaceChildren(metric("Facilities", fmt(s.facility_count)), metric("Markets", fmt(s.market_count)), metric("Advertised IT capacity", `${fmt(s.critical_it_mw, 1)} MW`), metric("IT floor area", `${fmt(s.it_area_sqft)} ft²`));
  $("quality-finding").textContent = `${c.missing_count} of ${c.facility_count} facilities (${pct(c.missing_facility_share)}) have no known carrier count. They represent ${pct(c.missing_capacity_share)} of advertised capacity: ${fmt(c.missing_capacity_mw, 3)} of ${fmt(c.total_capacity_mw, 3)} MW.`;
  $("missing-chart").replaceChildren(proportion("Facilities with unknown carriers", c.missing_facility_share), proportion("Capacity at those facilities", c.missing_capacity_share));
  $("quality-status").textContent = `${q.accounting.accepted} facilities included. ${q.accounting.rejected} entries excluded. ${q.failures.length} pages failed to load. ${q.warning_counts.card_detail_conflicts} differences between market listings and facility pages.`;
  const conflicts = q.reconciliation.filter((item) => item.status === "conflict");
  $("issue-summary").textContent = `${conflicts.length} conflicting totals and ${q.parse_issues.length} ${q.parse_issues.length === 1 ? "value" : "values"} to review`;
  $("issues").replaceChildren();
  conflicts.forEach((item) => listItem($("issues"), conflictText(item), item.source_url));
  q.parse_issues.forEach((item) => listItem($("issues"), `${marketName(item.record_level)} ${item.raw_label}: “${item.raw_value}”. ${item.error ? "We could not interpret this value" : "We could not recognise this label"}, so it was not used.`, item.source_url));
  const names = (s.top_three_markets ?? []).map(marketName);
  $("concentration-title").textContent = `${pct(s.top_three_market_capacity_share)} of capacity sits in ${names.length} markets.`;
  $("concentration-finding").textContent = `${new Intl.ListFormat("en-GB").format(names)} contain ${s.top_three_market_facility_count ?? 0} of ${s.facility_count} facilities. Counting locations alone gives a different picture of the portfolio.`;
  $("density-finding").textContent = `Median facility density is ${fmt(s.density_w_per_sqft.median)} W/ft². Total power divided by total IT floor area is ${fmt(s.portfolio_density_w_per_sqft)} W/ft², giving sites with more floor area more weight. Neither measures utilisation, energy efficiency or GPU performance.`;
  $("market").replaceChildren(new Option("All markets", ""), ...[...new Set(facilities.map((f) => f.market))].sort().map((m) => new Option(marketName(m), m)));
  renderMarkets();
  renderAnalysis();
}

function renderMarkets() {
  const all = report.breakdowns.markets;
  const rows = showAllMarkets ? all : all.slice(0, 7);
  const max = all[0]?.critical_it_mw || 1;
  const container = $("market-chart"); container.replaceChildren();
  const shown = [...rows];
  if (!showAllMarkets && all.length > 7) {
    const rest = all.slice(7);
    shown.push({ market: null, name: `Other ${rest.length} markets`, critical_it_mw: rest.reduce((sum, m) => sum + m.critical_it_mw, 0), facility_count: rest.reduce((sum, m) => sum + m.facility_count, 0) });
  }
  const scale = Math.max(max, ...shown.map((m) => m.critical_it_mw));
  shown.forEach((m, index) => {
    const row = node("div", null, `market-row${index < 3 ? " leading" : ""}`);
    const name = node(m.market ? "button" : "span", m.name ?? marketName(m.market), "market-name");
    if (m.market) { name.type = "button"; name.title = `Filter facilities to ${marketName(m.market)}`; name.addEventListener("click", () => { resetFilters(); $("market").value = m.market; renderFacilities(); $("comparison").scrollIntoView(); }); }
    const bar = node("div", null, "market-bar"), track = node("div", null, "track"), fill = node("span", null, "fill");
    fill.style.width = `${m.critical_it_mw / scale * 100}%`; track.setAttribute("aria-hidden", "true"); track.append(fill);
    bar.append(track, node("span", `${fmt(m.critical_it_mw, 1)} MW`, "market-value"));
    row.append(name, bar, node("span", fmt(m.facility_count), "market-count")); container.append(row);
  });
  $("all-markets").hidden = all.length <= 7;
  $("all-markets").textContent = showAllMarkets ? "Show leading markets" : `Show all ${all.length} markets`;
  $("all-markets").setAttribute("aria-expanded", String(showAllMarkets));
}

const svgNS = "http://www.w3.org/2000/svg";
function svgNode(tag, attributes, text) {
  const element = document.createElementNS(svgNS, tag);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
  if (text != null) element.textContent = text;
  return element;
}
function renderScatter(rows) {
  const log = $("log-scale").checked, width = 960, height = 380;
  const left = 72, right = 32, top = 32, bottom = 64;
  const axis = (key, pixels) => {
    const values = facilities.map((f) => f[key]);
    const min = log ? 10 ** Math.floor(Math.log10(Math.min(...values))) : 0;
    const max = log ? 10 ** Math.ceil(Math.log10(Math.max(...values))) : Math.max(...values) * 1.08;
    const transform = log ? Math.log10 : (v) => v;
    const scale = (value) => (transform(value) - transform(min)) / (transform(max) - transform(min) || 1) * pixels;
    const ticks = log ? Array.from({ length: Math.round(Math.log10(max / min)) + 1 }, (_, i) => min * 10 ** i) : Array.from({ length: 5 }, (_, i) => max * i / 4);
    return { scale, ticks };
  };
  const x = axis("it_area_sqft", width - left - right), y = axis("critical_it_mw", height - top - bottom);
  const svg = svgNode("svg", { viewBox: `0 0 ${width} ${height}`, role: "group", "aria-label": `IT floor area versus advertised power for ${rows.length} facilities; ${log ? "logarithmic" : "linear"} axes` });
  x.ticks.forEach((tick) => {
    const px = left + x.scale(tick);
    svg.append(svgNode("line", { x1: px, x2: px, y1: top, y2: height - bottom, class: "grid" }), svgNode("text", { x: px, y: height - bottom + 24, "text-anchor": "middle" }, fmt(tick)));
  });
  y.ticks.forEach((tick) => {
    const py = height - bottom - y.scale(tick);
    svg.append(svgNode("line", { x1: left, x2: width - right, y1: py, y2: py, class: "grid" }), svgNode("text", { x: left - 12, y: py + 4, "text-anchor": "end" }, fmt(tick, 2)));
  });
  svg.append(svgNode("text", { x: left, y: 16 }, "Advertised IT load (MW)"), svgNode("text", { x: width / 2, y: height - 12, "text-anchor": "middle" }, `IT floor area (ft²)${log ? " / logarithmic scales" : ""}`));
  rows.forEach((f) => {
    const label = `${f.facility_code}: ${fmt(f.it_area_sqft)} ft², ${fmt(f.critical_it_mw, 3)} MW, ${f.onsite_carriers == null ? "carriers unknown" : `${f.onsite_carriers} carriers`}`;
    const point = svgNode("circle", { cx: left + x.scale(f.it_area_sqft), cy: height - bottom - y.scale(f.critical_it_mw), r: 5, fill: f.onsite_carriers == null ? "var(--paper)" : "var(--accent)", class: "point", tabindex: 0, role: "button", "aria-label": label });
    point.append(svgNode("title", {}, label));
    point.addEventListener("click", () => showEvidence(f, point));
    point.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); showEvidence(f, point); } });
    svg.append(point);
  });
  $("scatter-chart").replaceChildren(svg);
}

const narrowChart = matchMedia("(max-width: 720px)");
function renderSizeChart(groups) {
  const compact = narrowChart.matches;
  const width = compact ? 400 : 760, height = compact ? 370 : 300;
  const left = compact ? 16 : 208, right = compact ? 60 : 92;
  const top = compact ? 54 : 36, step = compact ? 80 : 56, bottom = 36;
  const max = Math.ceil(Math.max(...groups.map((g) => g.median_density_w_per_sqft)) / 50) * 50;
  const scale = (value) => value / max * (width - left - right);
  const svg = svgNode("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": groups.map((g) => `${g.label}: median ${fmt(g.median_density_w_per_sqft)} watts per square foot, ${g.facility_count} facilities`).join(". ") });
  svg.append(svgNode("text", { x: left, y: 16 }, "Median advertised W/ft²"));
  for (let i = 0; i <= 5; i++) {
    const value = max * i / 5, x = left + scale(value);
    if (!compact) svg.append(svgNode("line", { x1: x, x2: x, y1: top - 8, y2: height - bottom, class: "grid" }));
    svg.append(svgNode("text", { x, y: height - 12, "text-anchor": "middle" }, fmt(value)));
  }
  groups.forEach((group, index) => {
    const y = top + index * step;
    svg.append(
      svgNode("text", { x: compact ? left : 0, y: compact ? y - 12 : y + 12, class: "group-name" }, group.label),
      svgNode("text", { x: compact ? width - 4 : 0, y: compact ? y - 12 : y + 32, "text-anchor": compact ? "end" : "start" }, `${fmt(group.area_min_sqft)}–${fmt(group.area_max_sqft)} ft²`),
      svgNode("rect", { x: left, y, width: scale(group.median_density_w_per_sqft), height: 24, fill: index === 3 ? "var(--accent)" : "var(--soft-blue)" }),
      svgNode("text", { x: left + scale(group.median_density_w_per_sqft) + 12, y: y + 17, class: "group-value" }, fmt(group.median_density_w_per_sqft)),
    );
  });
  $("size-chart").replaceChildren(svg);
}
narrowChart.addEventListener("change", () => {
  if (report?.breakdowns.size_density) renderSizeChart(report.breakdowns.size_density.groups);
});

function renderAnalysis() {
  const analysis = report.breakdowns.size_density;
  $("size-chart").replaceChildren();
  $("size-checks").replaceChildren();
  $("facility-examples").replaceChildren();
  $("quality-size").hidden = true;
  $("facility-case-study").hidden = true;
  $("carrier-question").hidden = true;
  $("size-method").hidden = !analysis;
  $("size-caption").textContent = "";
  if (!analysis) {
    $("size-finding").textContent = "Size comparisons are unavailable for this dataset.";
    return;
  }
  const groups = analysis.groups;
  const first = groups[0], last = groups.at(-1);
  $("size-finding").textContent = `The largest quarter by floor area advertises a median of ${fmt(last.median_density_w_per_sqft)} W/ft², compared with ${fmt(first.median_density_w_per_sqft)} W/ft² in the smallest quarter. That is ${fmt(analysis.largest_to_smallest_median_ratio, 1)} times as much power per square foot.`;
  const missing = report.quality.carrier_coverage.missing_count;
  if (missing) {
    $("quality-size").textContent = `${last.missing_carriers} of the ${missing} facilities with unknown carrier counts fall in the largest quarter by floor area.`;
    $("quality-size").hidden = false;
  }
  renderSizeChart(groups);
  const counts = groups.map((g) => g.facility_count);
  const countText = new Set(counts).size === 1 ? `${counts[0]} facilities in each group.` : `Group sizes: ${counts.join(", ")} facilities.`;
  $("size-caption").textContent = `${countText} Ranges show IT floor area. This comparison uses the full dataset, regardless of filters above.`;
  analysis.checks.forEach((check) => {
    const row = node("tr");
    row.append(node("td", check.label), node("td", fmt(check.facility_count), "numeric"), node("td", fmt(check.area_density_spearman, 2), "numeric"));
    $("size-checks").append(row);
  });
  $("size-check-description").hidden = analysis.checks.length < 2;
  const carrier = analysis.power_carriers;
  if (carrier.spearman != null) {
    const missingNote = carrier.missing_count ? ` The ${carrier.missing_count} unknown counts are excluded.` : "";
    const sizeNote = carrier.missing_count && last.missing_carriers === carrier.missing_count ? " All of those are in the largest size group, leaving a gap in this comparison." : "";
    $("carrier-finding").textContent = `For the ${carrier.facility_count} facilities with reported carrier counts, the rank correlation between advertised power and carrier count is ${fmt(carrier.spearman, 2)}.${missingNote}${sizeNote}`;
    $("carrier-question").hidden = false;
  }
  const examples = ["DFW1", "DFW8"].map((code) => facilities.find((f) => f.facility_code === code));
  if (examples.every((f) => f && reviewedNote(f.facility_code))) {
    const [a, b] = examples;
    $("case-finding").textContent = `DFW8 has ${pct(1 - b.it_area_sqft / a.it_area_sqft)} less IT floor area than DFW1, but advertises ${fmt(b.critical_it_mw / a.critical_it_mw, 1)} times the power. Its power density is ${fmt(b.capacity_density_w_per_sqft / a.capacity_density_w_per_sqft, 1)} times that of DFW1.`;
    examples.forEach((f) => {
      const note = reviewedNote(f.facility_code);
      const card = node("article", null, "case-example");
      const metrics = node("dl", null, "case-metrics");
      metrics.append(metric("IT floor area", `${fmt(f.it_area_sqft)} ft²`), metric("Advertised power", `${fmt(f.critical_it_mw)} MW`), metric("Power density", `${fmt(f.capacity_density_w_per_sqft)} W/ft²`));
      card.append(node("h4", `${f.facility_code}: ${note.title}`), metrics, node("p", note.text, "small"));
      if (note.caveat) card.append(node("p", note.caveat, "small muted"));
      const actions = node("div", null, "case-actions");
      const inspect = node("button", "Inspect figures", "text-button");
      inspect.type = "button";
      inspect.addEventListener("click", () => showEvidence(f, inspect));
      actions.append(link("Source page ↗", f.detail_url), inspect);
      card.append(actions);
      $("facility-examples").append(card);
    });
    $("facility-case-study").hidden = false;
  }
}

function filteredRows() {
  const query = $("search").value.trim().toLowerCase(), market = $("market").value;
  return facilities.filter((f) => (!market || f.market === market) && (!$("missing").checked || f.onsite_carriers == null) && [f.facility_code, f.facility_name, marketName(f.market), f.address_raw, f.campus_name].join(" ").toLowerCase().includes(query)).sort((a, b) => {
    const av = a[sortKey], bv = b[sortKey];
    if (av == null || bv == null) return av == null && bv == null ? a.facility_code.localeCompare(b.facility_code) : av == null ? 1 : -1;
    const cmp = typeof av === "number" ? av - bv : String(av).localeCompare(String(bv), undefined, { numeric: true });
    return (ascending ? cmp : -cmp) || a.facility_code.localeCompare(b.facility_code, undefined, { numeric: true });
  });
}
function renderFacilities() {
  const rows = filteredRows();
  $("result-count").textContent = `${rows.length} of ${facilities.length} facilities`;
  $("result-count").hidden = rows.length === facilities.length;
  $("empty").hidden = rows.length > 0;
  $("evidence").hidden = true;
  const body = $("facility-rows"); body.replaceChildren();
  rows.forEach((f) => {
    const row = node("tr"), identity = node("td"), button = node("button", f.facility_code, "facility-button");
    button.type = "button"; button.addEventListener("click", () => showEvidence(f, button));
    identity.append(button, node("small", f.facility_name)); row.append(identity, node("td", marketName(f.market)));
    [fmt(f.critical_it_mw, 3), fmt(f.it_area_sqft), fmt(f.capacity_density_w_per_sqft, 1), fmt(f.onsite_carriers)].forEach((value) => row.append(node("td", value, "numeric")));
    body.append(row);
  });
  document.querySelectorAll("[data-sort]").forEach((button) => { button.parentElement.setAttribute("aria-sort", button.dataset.sort === sortKey ? ascending ? "ascending" : "descending" : "none"); });
  renderScatter(rows);
  const fields = ["facility_code", "facility_name", "market", "it_area_sqft", "critical_it_mw", "capacity_density_w_per_sqft", "onsite_carriers", "detail_url", "fetched_at"];
  const cell = (value) => `"${String(value ?? "").replace(/^[=+@\-\t\r]/, (match) => "'" + match).replaceAll('"', '""')}"`;
  const csv = [fields.join(","), ...rows.map((f) => fields.map((key) => cell(f[key])).join(","))].join("\r\n");
  if (csvUrl) URL.revokeObjectURL(csvUrl);
  csvUrl = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  $("download").href = csvUrl;
}

function showEvidence(f, trigger) {
  lastTrigger = trigger;
  $("evidence-title").textContent = `${f.facility_code} / ${f.facility_name}`;
  $("evidence-address").textContent = [f.campus_name, f.address_raw].filter(Boolean).join(" / ");
  $("evidence-values").replaceChildren(metric("Advertised IT load", `${fmt(f.critical_it_mw, 3)} MW`), metric("IT floor area", `${fmt(f.it_area_sqft)} ft²`), metric("Capacity per area", `${fmt(f.capacity_density_w_per_sqft, 1)} W/ft²`), metric("Onsite carriers", fmt(f.onsite_carriers)));
  $("evidence-links").replaceChildren(link("Facility source ↗", f.detail_url), " / ", link("Market source ↗", f.market_url));
  $("evidence-time").textContent = `Page saved ${date(f.fetched_at)}. We do not know when these figures were last updated.`;
  const notes = $("evidence-notes"); notes.replaceChildren();
  if (f.onsite_carriers == null) listItem(notes, "Carrier count is unknown; it is not treated as zero.");
  const reading = reviewedNote(f.facility_code);
  if (reading) listItem(notes, [reading.text, reading.caveat].filter(Boolean).join(" "), f.detail_url);
  report.quality.reconciliation.filter((item) => item.status === "conflict" && item.source_url === f.market_url).forEach((item) => listItem(notes, `Market context, not a change to this facility: ${conflictText(item)}`, item.source_url));
  report.quality.card_detail_conflicts.filter((item) => item.facility_url === f.detail_url).forEach((item) => listItem(notes, `The published ${fieldLabel[item.field] ?? item.field} values differ. We use the facility page's main figure, or its specification table if the main figure is absent.`));
  if (!notes.children.length) listItem(notes, "The published figures agree across the pages we checked. We have not independently verified them.");
  const claims = report.breakdowns.facility_evidence[f.facility_code] ?? [];
  const body = $("evidence-rows"); body.replaceChildren();
  claims.forEach((claim) => {
    const row = node("tr"), source = node("td"); source.append(link(origins[claim.origin] ?? claim.origin, claim.source_url));
    row.append(source, node("td", claim.raw_label), node("td", claim.raw_value), node("td", claim.value == null ? "Unknown" : `${fmt(claim.value, 3)}${units[claim.field] ?? ""}`)); body.append(row);
  });
  const provenance = $("evidence-provenance"); provenance.replaceChildren();
  [...new Map(claims.map((claim) => [claim.source_url, claim])).values()].forEach((claim) => {
    const p = node("p"); p.append(link(claim.source_url, claim.source_url), node("br"), `Retrieved: ${date(claim.fetched_at)}`, node("br"), `SHA-256: ${claim.sha256}`); provenance.append(p);
  });
  $("evidence").hidden = false; $("evidence").focus({ preventScroll: true }); $("evidence").scrollIntoView({ block: "start" });
}
function resetFilters() { $("filters").reset(); }
$("filters").addEventListener("submit", (event) => event.preventDefault());
$("filters").addEventListener("input", () => renderFacilities());
$("reset-filters").addEventListener("click", () => { resetFilters(); renderFacilities(); });
$("missing-filter").addEventListener("click", () => { resetFilters(); $("missing").checked = true; renderFacilities(); $("comparison").scrollIntoView(); });
$("all-markets").addEventListener("click", () => { showAllMarkets = !showAllMarkets; renderMarkets(); });
$("log-scale").addEventListener("change", () => renderScatter(filteredRows()));
document.querySelectorAll("[data-sort]").forEach((button) => button.addEventListener("click", () => { ascending = sortKey === button.dataset.sort ? !ascending : true; sortKey = button.dataset.sort; renderFacilities(); }));
$("close-evidence").addEventListener("click", () => { $("evidence").hidden = true; lastTrigger?.focus(); });
async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Could not load the data (${response.status}). Please retry.`);
  return response.json();
}
async function load() {
  $("retry").hidden = true; $("study").hidden = true; $("status").hidden = false; $("status").textContent = "Loading data…";
  try {
    report = await getJSON("/api/overview");
    const result = await getJSON(`/api/facilities?run_id=${encodeURIComponent(report.run_id)}`);
    if (result.run_id !== report.run_id) throw new Error("The dataset changed while loading. Please retry.");
    if (!report.quality.carrier_coverage || !report.breakdowns.facility_evidence) throw new Error("This dataset does not include the source details needed by this page.");
    facilities = result.facilities;
    if (!facilities.length) throw new Error("No facilities are available in this dataset.");
    renderOverview(); renderFacilities(); $("study").hidden = false; $("status").hidden = true;
  } catch (error) { $("status").textContent = error.message; $("retry").hidden = false; }
}
$("retry").addEventListener("click", load);
const navLinks = [...document.querySelectorAll('nav[aria-label="Sections"] a')];
function selectSection(id) {
  navLinks.forEach((link) => {
    if (link.hash === `#${id}`) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  });
}
navLinks.forEach((link) => link.addEventListener("click", () => selectSection(link.hash.slice(1))));
const sections = navLinks.map((link) => document.querySelector(link.hash));
function followScroll() {
  if ($("study").hidden) return;
  const atBottom = Math.ceil(scrollY + innerHeight) >= document.documentElement.scrollHeight;
  const anchorLine = parseFloat(getComputedStyle(sections[0]).scrollMarginTop) + 1;
  const current = atBottom ? sections.at(-1) : sections.findLast((section) => section.getBoundingClientRect().top <= anchorLine) ?? sections[0];
  selectSection(current.id);
}
addEventListener("scroll", followScroll, { passive: true });
addEventListener("resize", followScroll);
await load();
followScroll();
