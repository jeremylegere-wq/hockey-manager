"use strict";
// v54: Financial statements (Team > Financial statements). The profit and loss report (fiscal year, period, columns by
// month or quarter, comparison with the budget or the year before, account levels, zero lines, units, drill-down to
// the journal lines, CSV and print), the board pack (the year to date against the budget, the forecast, the monthly
// trend, the owner's quarterly reports, the league) and the cash statement. Data: hs/game/accounts.py.

const PNL = {fy: "", period: "", columns: "total", compare: "budget", level: 3, zero: false, units: "M", drill: null};
const PNL_UNITS = {M: [1e6, 2, "$M"], K: [1e3, 0, "$000"], D: [1, 0, "$"]};
const pnlNum = (v, kind) => {
  if (v == null) return "";
  if (kind === "pct") return `${v.toFixed(1)}%`;
  const [div, dp] = PNL_UNITS[PNL.units];
  const x = Math.abs(v / div).toLocaleString(undefined, {minimumFractionDigits: dp, maximumFractionDigits: dp});
  return v < 0 ? `(${x})` : x;
};
const fmtM = (v) => v == null ? "-" : `${v < 0 ? "-" : ""}$${(Math.abs(v) / 1e6).toFixed(1)}M`;

async function pnlTab() {
  const q = {columns: PNL.columns, compare: PNL.compare, level: PNL.level};
  if (PNL.fy) q.fy = PNL.fy;
  if (PNL.period) q.period = PNL.period;
  if (PNL.zero) q.zero = "1";
  const d = await api("pnl", q);
  PNL.fy = d.fy;
  PNL.period = d.period;
  const opt = (v, label, cur) => `<option value="${v}"${String(v) === String(cur) ? " selected" : ""}>${esc(label)}</option>`;
  const periods = [["year", "Full year"], ["ytd", "Year to date"], ["q1", "Q1 (Jul-Sep)"], ["q2", "Q2 (Oct-Dec)"], ["q3", "Q3 (Jan-Mar)"], ["q4", "Q4 (Apr-Jun)"],
    ...d.months.map((m) => [m.m, m.label])];
  const bar = `<div class="toolbar pnl-bar">
    <label>Fiscal year <select id="pnl-fy">${d.fys.map((x) => opt(x.fy, x.label, d.fy)).join("")}</select></label>
    <label>Period <select id="pnl-period">${periods.map(([v, l]) => opt(v, l, d.period)).join("")}</select></label>
    <label>Columns <select id="pnl-cols">${[["total", "Total"], ["monthly", "By month"], ["quarterly", "By quarter"]].map(([v, l]) => opt(v, l, PNL.columns)).join("")}</select></label>
    <label>Compare with <select id="pnl-cmp"${PNL.columns !== "total" ? " disabled" : ""}>${[["none", "Nothing"], ["budget", "Budget"], ["prior", "Last year"], ["both", "Budget and last year"]].map(([v, l]) => opt(v, l, PNL.compare)).join("")}</select></label>
    <label>Levels <select id="pnl-lvl">${[[1, "1 sections"], [2, "2 groups"], [3, "3 accounts"]].map(([v, l]) => opt(v, l, PNL.level)).join("")}</select></label>
    <label><input type="checkbox" id="pnl-zero"${PNL.zero ? " checked" : ""}> Zero lines</label>
    <label>Units <select id="pnl-units">${Object.entries(PNL_UNITS).map(([k, v]) => opt(k, v[2], PNL.units)).join("")}</select></label>
    <span class="spacer"></span><button id="pnl-print">Print</button></div>`;
  const head = `<tr><th>Account</th>${d.columns.map((c) => `<th class="num">${esc(c.label)}</th>`).join("")}</tr>`;
  const body = d.rows.map((r) => {
    const cells = r.vals.map((v, i) => {
      const k = d.columns[i].kind;
      const cls = k === "var" ? (v > 0 ? "r4" : v < 0 ? "r1" : "") : "";
      return `<td class="num ${cls}">${pnlNum(v, k)}</td>`;
    }).join("");
    const label = r.kind === "subtotal" ? esc(r.name) : `<span class="pnl-code">${esc(r.code)}</span> ${esc(r.name)}`;
    return `<tr class="pnl-${r.kind} pnl-l${r.level}${r.drill ? " pnl-drill" : ""}"${r.drill ? ` data-drill="${r.drill}" title="Show the journal lines"` : ""}><td>${label}</td>${cells}</tr>`;
  }).join("");
  const note = `<p class="muted small">${esc(d.note)} Amounts in ${PNL_UNITS[PNL.units][2]}; costs in brackets. Click a line for its journal entries.
    ${d.budget ? `<br>Budget: ${esc(d.budget.status)}, drawn up ${dshort(d.budget.built)}. ${esc(d.budget.note)}.` : ""}</p>`;
  const tbl = `<div class="pnl-wrap"><table class="pnl nosort">${head}${body}</table></div>`;
  let jr = "";
  if (PNL.drill) {
    try {
      const j = await api("journal", {fy: d.fy, code: PNL.drill, period: d.period});
      jr = panel(`Journal: ${j.code} ${j.name}, ${j.period_label}`, j.lines.length ? `<div class="scroll" style="max-height:420px">${table(j.lines,
        [{key: "day", label: "Date", fmt: (r) => dshort(r.day)}, {key: "account", label: "Account", fmt: (r) => `${r.account} ${esc(r.account_name)}`},
         {key: "detail", label: "Detail"}, {key: "amount", label: "Amount", num: true, fmt: (r) => pnlNum(r.amount)}])}</div>
         <p class="muted small">${j.count} lines, total ${pnlNum(j.total)} ${PNL_UNITS[PNL.units][2]}${j.count > j.lines.length ? ` (the last ${j.lines.length} shown)` : ""}.</p>` : empty("No entries in the period."),
        `<a id="pnl-close">close</a>`);
    } catch (e) { PNL.drill = null; }
  }
  AFTER = () => {
    const set = (id, k, f = (x) => x) => { const el = $(id); if (el) el.onchange = (e) => { PNL[k] = f(e.target.type === "checkbox" ? e.target.checked : e.target.value); if (k === "fy") PNL.period = ""; render(); }; };
    set("#pnl-fy", "fy"); set("#pnl-period", "period"); set("#pnl-cols", "columns"); set("#pnl-cmp", "compare"); set("#pnl-lvl", "level", Number);
    set("#pnl-zero", "zero"); set("#pnl-units", "units");
    const pr = $("#pnl-print"); if (pr) pr.onclick = () => window.print();
    document.querySelectorAll("tr[data-drill]").forEach((tr) => (tr.onclick = () => { PNL.drill = tr.dataset.drill; render(); }));
    const cl = $("#pnl-close"); if (cl) cl.onclick = () => { PNL.drill = null; render(); };
  };
  return bar + panel(`Profit and loss: ${d.fy_label}, ${d.period_label}`, tbl + note) + jr;
}

function trendSvg(trend) {
  const W = 1500, H = 250, pad = 40, n = trend.length;
  const vals = trend.flatMap((t) => [t.cum_actual, t.cum_budget, t.actual, t.budget]).filter((v) => v != null);
  const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals) || 1;
  const y = (v) => H - pad - ((v - lo) / (hi - lo)) * (H - 2 * pad);
  const x = (i) => pad + (i + 0.5) * ((W - 2 * pad) / n);
  const bw = (W - 2 * pad) / n / 3;
  let s = `<svg viewBox="0 0 ${W} ${H}" class="fin-trend" role="img" aria-label="Net profit by month against the budget">`;
  s += `<line x1="${pad}" x2="${W - pad}" y1="${y(0)}" y2="${y(0)}" class="ax"/>`;
  trend.forEach((t, i) => {
    s += `<rect x="${x(i) - bw}" width="${bw}" y="${Math.min(y(0), y(t.budget))}" height="${Math.abs(y(t.budget) - y(0))}" class="bud"><title>${t.label} budget ${fmtM(t.budget)}</title></rect>`;
    if (t.actual != null) s += `<rect x="${x(i)}" width="${bw}" y="${Math.min(y(0), y(t.actual))}" height="${Math.abs(y(t.actual) - y(0))}" class="${t.actual >= 0 ? "act" : "neg"}"><title>${t.label} actual ${fmtM(t.actual)}</title></rect>`;
    s += `<text x="${x(i)}" y="${H - 10}" text-anchor="middle">${t.label.slice(0, 3)}</text>`;
  });
  const line = (k, cls) => { const p = trend.map((t, i) => t[k] == null ? null : `${x(i)},${y(t[k])}`).filter(Boolean); return p.length > 1 ? `<polyline points="${p.join(" ")}" class="${cls}"/>` : ""; };
  s += line("cum_budget", "lb") + line("cum_actual", "la");
  s += `<text x="${pad}" y="14" class="lg">bars: month (budget, actual) · lines: cumulative (budget dashed)</text>`;
  s += `<text x="4" y="${y(hi) + 4}">${fmtM(hi)}</text><text x="4" y="${y(lo) + 4}">${fmtM(lo)}</text></svg>`;
  return s;
}

async function boardTab() {
  const d = await api("boardpack");
  const k = d.kpis;
  const tile = (label, x) => `<div><b class="${x.var >= 0 ? "r4" : "r1"}">${fmtM(x.actual)}</b><span>${label}</span>
    <span class="muted small">budget ${fmtM(x.budget)} · ${x.var >= 0 ? "+" : ""}${fmtM(x.var)}</span><span class="muted small">forecast ${fmtM(x.forecast)}</span></div>`;
  const tiles = `<div class="fin-proj fin-kpi">${tile("revenue", k.revenue)}${tile("EBITDA", k.ebitda)}${tile("net profit", k.net)}
    <div><b>${fmtM(d.cash)}</b><span>cash</span><span class="muted small">${d.payroll_share != null ? `players ${d.payroll_share}% of revenue` : ""}</span>
    <span class="muted small">${d.fill != null ? `${(d.fill * 100).toFixed(1)}% full` : ""}${d.per_fan ? ` · $${d.per_fan} a fan` : ""}</span></div></div>`;
  const rows = [["Revenue", "revenue"], ["Hockey operations", "hockey"], ["Operating expenses", "opex"], ["EBITDA", "ebitda"], ["Net profit", "net"]];
  const kt = `<table class="pnl nosort"><tr><th></th><th class="num">Actual</th><th class="num">Budget</th><th class="num">Variance</th><th class="num">Forecast</th><th class="num">Full-year budget</th></tr>
    ${rows.map(([l, key]) => { const x = k[key]; return `<tr class="${key === "net" || key === "ebitda" ? "pnl-subtotal" : ""}"><td>${l}</td><td class="num">${fmtM(x.actual)}</td><td class="num">${fmtM(x.budget)}</td>
      <td class="num ${x.var >= 0 ? "r4" : "r1"}">${x.var >= 0 ? "+" : ""}${fmtM(x.var)}</td><td class="num">${fmtM(x.forecast)}</td><td class="num">${fmtM(x.full_budget)}</td></tr>`; }).join("")}</table>
    <p class="muted small">Year to date to ${dshort(d.today)}; the forecast is the actual so far plus the budget for the rest of the year.</p>`;
  const o = d.owner;
  const own = `<table class="kvt"><tr><th>Owner</th><td>${esc(o.name)}${o.archetype ? ` <span class="muted small">${esc(o.archetype)}</span>` : ""}</td></tr>
    <tr><th>Watches</th><td>${esc(o.watches)}</td></tr><tr><th>Next review</th><td>${d.next_review ? dshort(d.next_review) : "-"}</td></tr>
    <tr><th>Revenue</th><td>${d.rank_revenue} of ${d.clubs} in the league</td></tr><tr><th>Net profit</th><td>${d.rank_net} of ${d.clubs}</td></tr>
    <tr><th>Budget</th><td>${d.budget ? `${esc(d.budget.status)}, ${dshort(d.budget.built)}` : "-"}</td></tr></table>
    <p class="muted small">The finance office reports to the board on 1 October, 1 January, 1 April and 1 July (the annual report).</p>`;
  const reps = d.reports.length ? table(d.reports, [{key: "day", label: "Date", fmt: (r) => dshort(r.day)},
    {key: "quarter", label: "Report", fmt: (r) => `${r.quarter === 4 ? "Annual" : `Q${r.quarter}`} ${esc(r.fy_label)}`},
    {key: "net", label: "Net vs budget", num: true, fmt: (r) => { const v = r.data.ytd.net.var; return `<span class="${v >= 0 ? "r4" : "r1"}">${v >= 0 ? "+" : ""}${fmtM(v)}</span>`; }},
    {key: "comment", label: "The owner", fmt: (r) => `<i class="fin-quote">"${esc(r.comment)}"</i>`},
    {key: "delta", label: "Confidence", num: true, fmt: (r) => r.delta ? `<span class="${r.delta > 0 ? "r4" : "r1"}">${r.delta > 0 ? "+" : ""}${r.delta}</span>` : "-"}])
    : empty("The first report comes at the end of the quarter.");
  const cs = d.cash_statement;
  const cash = `<table class="kvt fin"><tr><th>Opening cash</th><td class="num">${fmtM(cs.opening)}</td></tr><tr><th>Net profit</th><td class="num">${fmtM(cs.net_profit)}</td></tr>
    <tr><th>Depreciation (non-cash)</th><td class="num">${fmtM(cs.depreciation)}</td></tr><tr><th>Cash from operations</th><td class="num">${fmtM(cs.operating)}</td></tr>
    <tr><th>Arena projects</th><td class="num">${fmtM(cs.capital)}</td></tr><tr><th>The owner</th><td class="num">${fmtM(cs.owner)}</td></tr>
    ${cs.financing ? `<tr><th>Arena loan (drawn less repaid)</th><td class="num">${fmtM(cs.financing)}</td></tr>` : ""}
    <tr class="tot"><th>Closing cash${cs.to_date ? " (to date)" : ""}</th><td class="num"><b>${fmtM(cs.closing)}</b></td></tr></table>`;
  const lg = table(d.league.map((r, i) => ({...r, rank: i + 1})), [{key: "rank", label: "#", num: true}, {key: "abbr", label: "Club", fmt: (r) => tm(r.abbr, r.team_id)},
    {key: "revenue", label: "Revenue", num: true, fmt: (r) => fmtM(r.revenue)}, {key: "net", label: "Net profit", num: true, fmt: (r) => `<span class="${r.net >= 0 ? "" : "r1"}">${fmtM(r.net)}</span>`},
    {key: "cash", label: "Cash", num: true, fmt: (r) => fmtM(r.cash)}], {rowClass: (r) => STATE && r.team_id === STATE.team_id ? "mine" : ""});
  return `<div class="grid two">${panel(`Board pack: ${d.fy_label}`, tiles + kt)}${panel("The owner", own)}</div>
    ${panel("Net profit by month against the budget", trendSvg(d.trend))}
    ${panel("Reports to the board", reps)}
    <div class="grid two">${panel(`Cash: ${cs.fy_label}`, cash)}${panel("The league, year to date", `<div class="scroll" style="max-height:360px">${lg}</div>`)}</div>`;
}

const finTabs = (tab) => `<div class="tabs fin-tabs">${[["#statements/pnl", "pnl", "Profit and loss"], ["#statements/board", "board", "Board pack"],
  ["#finances", "fin", "Prices, budgets and arena"]].map(([h, k, l]) => `<a href="${h}" class="btn${k === tab ? " active" : ""}">${l}</a>`).join("")}</div>`;
VIEWS.statements = async (tab) => {
  tab = tab || "pnl";
  return finTabs(tab) + (tab === "board" ? await boardTab() : await pnlTab());
};
{
  const oldFin = VIEWS.finances;
  VIEWS.finances = async (season) => finTabs("fin") + await oldFin(season);
}

(() => {
  const team = MENUS.find((m) => m[0] === "Team")[1];
  const at = team.findIndex((it) => it !== "-" && it[0] === "Finances");
  team.splice(at >= 0 ? at + 1 : team.length, 0, ["Financial statements", "#statements"], ["Board pack", "#statements/board"]);
  Object.assign(SCREEN_NAMES, {statements: "Financial statements"});
  Object.assign(TAB_OF, {statements: "contracts"});
})();

Object.assign(FR, {"Financial statements": "États financiers", "Board pack": "Dossier du conseil", "Profit and loss": "Résultats",
  "Fiscal year": "Exercice", "Period": "Période", "Columns": "Colonnes", "Compare with": "Comparer avec", "Levels": "Niveaux", "Zero lines": "Lignes à zéro",
  "Units": "Unités", "Print": "Imprimer", "Account": "Compte", "Actual": "Réel", "Budget": "Budget", "Variance": "Écart", "% of budget": "% du budget",
  "Change %": "Variation %", "Full year": "Exercice complet", "Year to date": "Cumul annuel", "By month": "Par mois", "By quarter": "Par trimestre",
  "Nothing": "Rien", "Last year": "L'an dernier", "Budget and last year": "Budget et l'an dernier", "Total": "Total", "Revenue": "Revenus",
  "Cost of hockey operations": "Coûts des opérations hockey", "Hockey operations margin": "Marge des opérations hockey", "Operating expenses": "Charges d'exploitation",
  "EBITDA": "BAIIA", "Depreciation": "Amortissement", "Operating profit": "Résultat d'exploitation", "Non-operating income and expenses": "Produits et charges hors exploitation",
  "Net profit": "Bénéfice net", "Owner": "Propriétaire", "Retained by the club": "Conservé par le club", "Forecast": "Prévision", "Full-year budget": "Budget annuel",
  "Reports to the board": "Rapports au conseil", "The league, year to date": "La ligue, cumul annuel", "The owner": "Le propriétaire", "Watches": "Surveille",
  "Next review": "Prochain examen", "Opening cash": "Encaisse d'ouverture", "Closing cash": "Encaisse de clôture", "Cash from operations": "Flux d'exploitation",
  "Arena projects": "Projets d'aréna", "Net vs budget": "Net vs budget", "Confidence": "Confiance", "Report": "Rapport",
  "Net profit by month against the budget": "Bénéfice net par mois contre le budget"});

/* ---- boot: moved to the last script (v55.js) ---- */
