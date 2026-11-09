"use strict";
// Front end for hs.ui.server. Reads JSON views; every action posts a CLI command line, so the rules live in Python.

const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const money = (v) => v == null ? "-" : "$" + Math.round(v).toLocaleString();
const ssn = (y) => y == null || y === "" ? "-" : `${y}-${String((+y + 1) % 100).padStart(2, "0")}`;
const CTYPE = {entry_level: "Entry-level", standard: "Standard", generated: "Standard", emergency: "Emergency", offer_sheet: "Offer sheet"};
const ctype = (t) => CTYPE[t] || (t ? t.replace(/_/g, " ") : "");
const mil = (v) => v == null ? "-" : "$" + (v / 1e6).toFixed(2) + "M";
let STATE = null;

// The game's own question dialog (the browser's confirm() / prompt() look foreign in the desktop window).
// ask(text) -> Promise<boolean>; ask(text, {input: "default"}) -> Promise<string|null>.
function ask(text, {ok = "OK", cancel = "Cancel", title = "Hockey Manager", input = null, danger = false} = {}) {
  return new Promise((resolve) => {
    let el = document.getElementById("dialog");
    if (!el) { el = document.createElement("div"); el.id = "dialog"; el.className = "dialog"; document.body.appendChild(el); }
    const lines = String(text).split("\n").map((l) => `<p>${esc(l)}</p>`).join("");
    el.innerHTML = `<div class="dialog-card" role="alertdialog" aria-modal="true"><div class="win-title">${esc(title)}</div><div class="dialog-body">${lines}
      ${input != null ? `<input id="dialog-input" value="${esc(input)}">` : ""}</div>
      <div class="win-buttons"><button class="${danger ? "danger-primary" : "primary"}" id="dialog-ok">${esc(ok)}</button>${cancel ? ` <button id="dialog-cancel">${esc(cancel)}</button>` : ""}</div></div>`;
    el.hidden = false;
    const done = (v) => { el.hidden = true; el.innerHTML = ""; document.removeEventListener("keydown", key, true); resolve(v); };
    const okv = () => input != null ? ($("#dialog-input").value) : true;
    const key = (e) => { if (e.key === "Escape") { e.stopPropagation(); done(input != null ? null : false); } else if (e.key === "Enter") { e.stopPropagation(); e.preventDefault(); done(okv()); } };
    document.addEventListener("keydown", key, true);
    $("#dialog-ok").onclick = () => done(okv());
    const c = $("#dialog-cancel"); if (c) c.onclick = () => done(input != null ? null : false);
    (input != null ? $("#dialog-input") : $("#dialog-ok")).focus();
  });
}
let AFTER = null;

async function api(view, params = {}) {
  const q = new URLSearchParams(params).toString();
  const r = await fetch(`/api/${view}${q ? "?" + q : ""}`);
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || "request failed");
  return j;
}

async function cmd(line, {quiet = false} = {}) {
  setBusy(true);
  try {
    const r = await fetch("/api/command", {method: "POST", headers: {"Content-Type": "application/json"},
                                           body: JSON.stringify({line})});
    const j = await r.json();
    if (!quiet || !j.ok) toast(j.output || (j.ok ? "Done." : "Failed."), !j.ok);
    await refresh();
    return j;
  } finally { setBusy(false); }
}

function setBusy(b) { document.querySelectorAll("#sb-controls button").forEach((x) => x.disabled = b); }

let toastTimer = null;
function toast(text, err = false) {
  // v39 (#12): long console output (help, tables) opens in a console window instead of a toast
  if (text && (text.trim().split("\n").length > 4 || text.length > 400) && typeof consoleOut === "function") { consoleOut(text, err); return; }
  const t = $("#toast");
  t.textContent = text.trim();
  t.className = "toast" + (err ? " err" : "");
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), err ? 12000 : 8000);
}
$("#toast").addEventListener("click", () => ($("#toast").hidden = true));

function ratingClass(v) { return v == null ? "" : v <= 7 ? "r1" : v <= 9 ? "r2" : v <= 13 ? "r3" : "r4"; }
function bar(v, max = 100) {
  const pct = Math.max(0, Math.min(100, (v / max) * 100));
  const cls = pct >= 60 ? "pos" : pct >= 40 ? "" : pct >= 28 ? "warn" : "neg";
  return `<div class="barrow"><div class="bar ${cls}"><span style="width:${pct}%"></span></div><span class="muted">${Math.round(v)}</span></div>`;
}
function panel(title, body, right = "") {
  return `<section class="panel"><h2>${esc(title)}${right ? `<span class="right">${right}</span>` : ""}</h2><div class="body">${body}</div></section>`;
}
function plink(id, name) { return `<a href="#player/${id}" data-pid="${id}">${esc(name)}</a>`; }
function clink(id, name) { return `<a href="#player/${id}" class="card-link" data-card="${id}">${esc(name)}</a>`; }

// sortable tables: columns = [{key, label, num, fmt(row)}]
function table(rows, cols, {id = "", rowClass = () => ""} = {}) {
  const head = cols.map((c, i) => `<th class="sort${c.num ? " num" : ""}" data-i="${i}">${esc(c.label)}</th>`).join("");
  const body = rows.map((r) => `<tr class="${rowClass(r)}">` + cols.map((c) =>
    `<td class="${c.num ? "num " : ""}${c.cls ? c.cls(r) : ""}">${c.fmt ? c.fmt(r) : esc(r[c.key])}</td>`).join("") + "</tr>").join("");
  return `<table data-table="${id}"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}
// v42 (register v39 #4): every simple table on a screen sorts by clicking a column header, not only table()'s
document.addEventListener("click", (e) => {
  const th = e.target.closest("th");
  if (!th || !th.closest("#view") || th.querySelector("input, select, button, a")) return;
  const tbl = th.closest("table"), head = th.parentElement;
  if (!tbl || tbl.classList.contains("nosort") || [...head.cells].some((c) => c.colSpan > 1)) return;
  const i = th.classList.contains("sort") && th.dataset.i != null ? +th.dataset.i : th.cellIndex;
  const rows = [...tbl.rows].filter((r) => r !== head && r.cells.length === head.cells.length && !r.querySelector("th"));
  if (rows.length < 2) return;
  const dir = th.dataset.dir === "asc" ? -1 : 1;
  head.querySelectorAll("th").forEach((x) => delete x.dataset.dir);
  th.dataset.dir = dir === 1 ? "asc" : "desc";
  const val = (r) => {
    const t = r.cells[i].textContent.replace(/[$,%]/g, "").trim();
    const n = parseFloat(t);
    return isNaN(n) || !/^[-+.\d]/.test(t) ? t.toLowerCase() : n;
  };
  rows.sort((a, b) => { const x = val(a), y = val(b);
    if (typeof x !== typeof y) return (typeof x === "number" ? -1 : 1) * dir;
    return (x > y ? 1 : x < y ? -1 : 0) * dir; });
  const parent = rows[0].parentElement;
  rows.forEach((r) => parent.appendChild(r));
});

// ---------------------------------------------------------------- chrome
async function refresh() {
  STATE = await api("state");
  if (!STATE.loaded) { document.body.classList.add("no-game"); return Title.show(); }
  document.body.classList.remove("no-game");
  if (!STATE.started) {
    $("#view").innerHTML = panel("No game", "This save has no game started. Open the Saves menu to start a new career.");
    return;
  }
  $("#tb-save").textContent = STATE.save || "";
  if (STATE.sim_running && !Sim.open) Sim.attach();
  $("#tb-team").textContent = STATE.team;
  $("#tb-season").textContent = `${STATE.season}-${String((STATE.season + 1) % 100).padStart(2, "0")}`;
  const ub = STATE.board && STATE.board.ultimatum;
  $("#tb-board").textContent = ub ? `ULTIMATUM: ${Math.max(0, ub.need)} pts in ${Math.max(0, ub.games)} games` : STATE.board ? `Board: ${STATE.board.label} (${STATE.board.confidence})` : "";
  $("#tb-board").classList.toggle("alarm", !!ub);
  $("#tb-inbox").textContent = `Inbox${STATE.unread ? " (" + STATE.unread + ")" : ""}`;
  $("#sb-date").textContent = STATE.date;
  $("#sb-phase").textContent = STATE.phase.replace("_", " ");
  const r = STATE.record;
  $("#sb-record").textContent = (r ? `${r.w}-${r.l}-${r.otl}${r.t ? "-" + r.t : ""} · ${r.pts} pts` : "") +
    (STATE.phase === "regular_season" && STATE.date <= STATE.trade_deadline ? ` · trade deadline ${STATE.trade_deadline}` : "");
  const c = $("#sb-controls");
  if (STATE.unemployed) c.innerHTML = `<a class="pill link" href="#jobs">Out of work: Job Centre (${STATE.jobs || 0})</a> ` + (STATE.phase === "regular_season"
    ? '<button data-sim="day">Day</button> <button data-sim="week">Week</button> <button data-sim="season">Rest of season</button>'
    : '<button class="primary" data-cmd="offseason">Next offseason phase</button>');
  else if (STATE.phase === "regular_season")
    c.innerHTML = `<button data-sim="day">Day</button> <button data-sim="week">Week</button>
      <button class="primary" data-sim="next">Next game</button> <button data-sim="season">Rest of season</button>`;
  else c.innerHTML = `<button class="primary" data-cmd="offseason">Next offseason phase</button>`;
  await render();
}

const cmdBox = $("#cmd");
if (cmdBox) cmdBox.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && cmdBox.value.trim()) { cmd(cmdBox.value.trim()); cmdBox.value = ""; }
});

document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-cmd]");
  if (!b) return;
  e.preventDefault();
  const line = b.dataset.cmd;
  if (b.dataset.confirm && !(await ask(b.dataset.confirm))) return;
  cmd(line);
});

// v41: renders run one at a time (the latest request wins), so two overlapping renders cannot splice their AFTER
// hooks together (that drew a player's header buttons twice).
let RENDER_Q = Promise.resolve(), RENDER_N = 0;
function render() {
  const n = ++RENDER_N;
  RENDER_Q = RENDER_Q.then(() => (n === RENDER_N ? renderNow() : null)).catch(() => {});
  return RENDER_Q;
}
async function renderNow() {
  const [view, arg] = (location.hash.slice(1) || "dashboard").split("/");
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  const fn = VIEWS[view] || VIEWS.dashboard;
  AFTER = null;
  try {
    $("#view").innerHTML = await fn(arg);
    if (AFTER) { const f = AFTER; AFTER = null; await f(); }  // views that draw (the replay) hook in here
  }
  catch (err) { $("#view").innerHTML = panel("Error", esc(err.message)); }
}
window.addEventListener("hashchange", render);

// ---------------------------------------------------------------- views
const VIEWS = {};

VIEWS.dashboard = async () => {
  const d = await api("dashboard"), s = d.state;
  const club = `<div class="big">${esc(s.abbr)} ${s.record ? `${s.record.w}-${s.record.l}-${s.record.otl}${s.record.t ? "-" + s.record.t : ""}` : ""}</div>
    <dl class="kv"><dt>Points</dt><dd>${s.record ? s.record.pts : 0}</dd>
    <dt>Payroll (${s.cap.season})</dt><dd>${money(s.cap.payroll)}${s.cap.room != null ? ` · room ${money(s.cap.room)}` : ""}</dd>
    <dt>Board</dt><dd>${s.board ? `${esc(s.board.label)} (${s.board.confidence}) ${bar(s.board.confidence)}` : "-"}${s.board && s.board.warning ? ' <span class="tag neg">final warning</span>' : ""}</dd>
    ${d.owner ? `<dt>Owner</dt><dd>${esc(d.owner.summary)}</dd>` : ""}</dl>`;
  const obj = (d.objectives || []).map((o) => `<li><span class="tag ${o.importance === "required" ? "warn" : ""}">${esc(o.importance)}</span> ${esc(o.description)}</li>`).join("") || "<li class='muted'>None set.</li>";
  const room = d.room ? `<div class="row"><b>${esc(d.room.atmosphere)}</b> <span class="muted">cohesion ${d.room.cohesion}, leadership ${d.room.leadership}/20</span></div>${bar(d.room.cohesion)}
      <p class="muted">${esc(d.room.reasons.join(" · "))}</p>
      <ul class="list">${(d.leaders || []).map((l) => `<li><span class="tag">${l.role}</span> ${plink(l.player_id, l.name)}</li>`).join("")}</ul>` : "-";
  const att = d.attention.map((a) => `<li><span class="tag ${a.kind === "meeting" ? "warn" : ""}">${a.kind}</span> ${plink(a.player_id, a.text)} <span class="date">${esc(a.since)}</span></li>`).join("") || "<li class='muted'>Nothing urgent.</li>";
  const news = d.news.map((n) => `<li><span class="date">${esc(n.date)}</span>${n.player_id ? plink(n.player_id, n.text) : esc(n.text)}</li>`).join("") || "<li class='muted'>No news yet.</li>";
  const league = d.league_news.map((n) => `<li><span class="date">${esc(n.date)}</span>${esc(n.text)}</li>`).join("");
  const games = d.next_games.map((g) => `<li>${esc(g.date)} ${g.home ? "vs" : "@"} <b>${esc(g.opponent)}</b></li>`).join("") || "<li class='muted'>No games scheduled.</li>";
  const res = d.recent_results.map((g) => `<li><span class="tag ${g.result === "W" ? "pos" : g.result === "L" ? "neg" : "warn"}">${g.result}</span> ${esc(g.date)} ${g.home ? "vs" : "@"} ${esc(g.opponent)} <a href="#game/${g.game_id}">${g.gf}-${g.ga} ${esc(g.ot)}</a></li>`).join("");
  const stand = Object.entries(d.standings).map(([k, rows]) => panel(k, table(rows, [
    {key: "abbr", label: "Team"}, {key: "gp", label: "GP", num: 1}, {key: "w", label: "W", num: 1}, {key: "l", label: "L", num: 1},
    {key: "otl", label: "OTL", num: 1}, ...(rows.some((x) => x.t) ? [{key: "t", label: "T", num: 1}] : []), {key: "pts", label: "PTS", num: 1}], {rowClass: (r) => r.mine ? "mine" : ""}))).join("");
  return `<div class="grid g3">
    <div class="grid">${panel("Club status", club)}${panel("Objectives", `<ul class="list">${obj}</ul>`)}${stand}</div>
    <div class="grid">${panel("Needs attention", `<ul class="list">${att}</ul>`)}${panel("Locker room", room)}${panel("Club news", `<ul class="list">${news}</ul>`)}</div>
    <div class="grid">${panel("Next games", `<ul class="list">${games}</ul>`)}${panel("Recent results", `<ul class="list">${res || "<li class='muted'>None yet.</li>"}</ul>`)}${panel("Around the league", `<ul class="list">${league}</ul>`)}</div>
  </div>`;
};

const SHORT = {offensive_awareness: "OFF", passing: "PAS", puck_control: "PCK", shot_accuracy: "SHT", positioning: "POS",
  defensive_awareness: "DEF", hitting: "HIT", speed: "SPD", goalie_positioning: "POS", reflexes: "REF", glove: "GLV",
  blocker: "BLK", low_shot_save: "LOW", rebound_control: "REB"};

VIEWS.roster = async (arg) => {
  const system = arg === "system";
  const d = await api("roster", system ? {system: "1"} : {});
  const tabs = `<div class="tabs"><a class="btn${system ? "" : " active"}" href="#roster">NHL roster</a> <a class="btn${system ? " active" : ""}" href="#roster/system">Whole organisation</a></div>`;
  const out = [["F", "Forwards"], ["D", "Defence"], ["G", "Goalies"]].map(([g, title]) => {
    const rows = d.groups[g];
    const cols = [
      {key: "num", label: "#", num: 1, fmt: (r) => `<a class="jn" data-pid="${r.player_id}" data-num="${r.num ?? ""}" title="Change his number">${r.num ?? "-"}</a>`},
      {key: "name", label: "Name", fmt: (r) => `${plink(r.player_id, r.name)}${r.leader ? ` <span class="tag">${r.leader}</span>` : ""}`},
      {key: "pos", label: "Pos"}, {key: "age", label: "Age", num: 1},
      ...d.columns[g].map((k) => ({key: k, label: SHORT[k] || k, num: 1, fmt: (r) => esc(r.ratings[k] ?? "-"), cls: (r) => ratingClass(r.ratings[k])})),
      {key: "value", label: "Val", num: 1},
      g === "G" ? {key: "sv_pct", label: "SV%", num: 1, fmt: (r) => r.sv_pct == null ? "-" : r.sv_pct.toFixed(3)}
                : {key: "pts", label: "G-A", num: 1, fmt: (r) => `${r.g}-${r.a}`},
      {key: "gp", label: "GP", num: 1}, {key: "toi", label: "TOI", num: 1},
      {key: "morale", label: "Morale", fmt: (r) => r.morale == null ? "-" : bar(r.morale)},
      {key: "cap", label: "Cap hit", num: 1, fmt: (r) => r.contract ? mil(r.contract.cap_hit) : "-"},
      {key: "ends", label: "Final season", num: 1, fmt: (r) => r.contract ? `${ssn(r.contract.ends)}${r.contract.expiring ? ` <span class="tag warn">${esc(r.contract.status_at_expiry || "")}</span>` : ""}` : "-"},
      {key: "status", label: "Status", fmt: (r) => r.status === "injured" ? `<span class="tag neg">injured</span>${r.ltir_ok ? ` <button class="mini" data-cmd="ltir ${r.player_id}">LTIR</button>` : ""}`
        : r.status === "ltir" ? `<span class="tag neg">LTIR</span> <button class="mini" data-cmd="activate ${r.player_id}">Activate</button>`
        : r.status === "prospect" ? `<span class="tag">${esc(r.club || "minors")}</span>` : ""},
      {key: "wv", label: "Waivers", fmt: (r) => r.needs_waivers ? `<span class="tag warn" title="${esc(r.waivers)}">required</span>` : `<span class="muted" title="${esc(r.waivers)}">${r.waivers.startsWith("exempt") ? "exempt" : "-"}</span>`},
      {key: "act", label: "", fmt: (r) => r.status === "prospect" ? `<button data-cmd="recall ${r.player_id}">Recall</button>` : r.status === "active" ? `<button data-cmd="senddown ${r.player_id}"${r.needs_waivers ? ` data-confirm="${esc(r.name)} needs waivers (${esc(r.waivers)}). Another club may claim him. Send him down?"` : ""}>Send down</button>` : ""},
    ];
    return panel(`${title} (${rows.length})`, `<div class="scroll">${table(rows, cols)}</div>`);
  }).join("");
  const wire = d.wire.length ? table(d.wire, [{key: "name", label: "On waivers", fmt: (r) => plink(r.player_id, r.name)},
      {key: "pos", label: "Pos"}, {key: "age", label: "Age", num: 1}, {key: "team", label: "From"},
      {key: "cap", label: "Cap hit", num: 1, fmt: (r) => r.cap ? mil(r.cap) : "-"}, {key: "value", label: "Val", num: 1},
      {key: "clears", label: "Clears"}, {key: "priority", label: "Your priority", num: 1, fmt: (r) => r.priority ? `${r.priority}/${r.of}` : "-"},
      {key: "c", label: "", fmt: (r) => r.mine ? '<span class="muted">yours</span>' : r.claimed ? `<button data-cmd="claim remove ${r.player_id}">Withdraw claim</button>` : `<button class="primary" data-cmd="claim ${r.player_id}">Claim</button>`}])
    : `<p class="muted">${d.waiver_period ? "Nobody on waivers." : "Outside the waiver period (it runs from the preseason to the end of the regular season)."}</p>`;
  const lt = d.ltir.players.length ? `<p>On LTIR: ${d.ltir.players.map((x) => `${plink(x.player_id, x.name)} (${mil(x.cap_hit)}, back no earlier than ${esc(x.earliest)})`).join("; ")}.
      Ceiling <b>${mil(d.ltir.ceiling)}</b> against the ${mil(d.ltir.cap)} cap; payroll ${mil(d.ltir.payroll)}.</p>` : "";
  return tabs + `<div class="grid">${lt ? panel("Long-term injured reserve", lt) : ""}${panel("Waiver wire", wire, "claims go to the worst record first")}${out}</div>`;
};

// ---------------------------------------------------------------- lines (hs/game/lineup.py)
VIEWS.lines = async () => {
  const d = await api("lines");
  const lu = d.lineup;
  if (!lu) return panel("Lines", "Your team cannot dress a lineup right now.");
  const byId = Object.fromEntries(d.players.map((p) => [p.player_id, p]));
  const opts = (sel, goalie) => `<option value="">-</option>` + d.players.filter((p) => (p.pos === "G") === goalie).map((p) =>
    `<option value="${p.player_id}"${p.player_id === sel ? " selected" : ""}${p.status === "injured" ? ' class="neg"' : ""}>${esc(p.name)} (${p.pos} ${p.value}${p.status === "injured" ? ", injured" : ""})</option>`).join("");
  const select = (unit, i, sel, goalie = false) => `<select class="ln" data-unit="${unit}" data-i="${i}">${opts(sel, goalie)}</select>`;
  const row = (unit, labels, ids, goalie = false) => `<tr><th>${unit}</th>${labels.map((l, i) => `<td><span class="muted">${l}</span><br>${select(unit, i, ids[i], goalie)}</td>`).join("")}</tr>`;
  const F = [0, 1, 2, 3].map((i) => row(`F${i + 1}`, ["C", "LW", "RW"], lu.F[i] || [])).join("");
  const D = [0, 1, 2].map((i) => row(`D${i + 1}`, ["LD", "RD"], lu.D[i] || [])).join("");
  const G = row("G", ["Starter", "Backup"], lu.G || [], true);
  const PP = [0, 1].map((i) => row(`PP${i + 1}`, ["", "", "", "", ""], (lu.PP[i] || []))).join("");
  const PK = [0, 1].map((i) => row(`PK${i + 1}`, ["", "", "", ""], (lu.PK[i] || []))).join("");
  AFTER = () => {
    const check = () => {
      const counts = {};
      document.querySelectorAll('.ln[data-unit^="F"], .ln[data-unit^="D"]').forEach((s) => { if (s.value) counts[s.value] = (counts[s.value] || 0) + 1; });
      document.querySelectorAll(".ln").forEach((s) => s.classList.toggle("dup", /^[FD]/.test(s.dataset.unit) && counts[s.value] > 1));
      const dressed = new Set(Object.keys(counts));
      document.querySelectorAll('.ln[data-unit^="P"]').forEach((s) => s.classList.toggle("dup", s.value && !dressed.has(s.value)));
      $("#ln-warn").textContent = document.querySelector(".ln.dup") ? "Someone is in two places, or a special-teams player is not in the lines." : "";
    };
    document.querySelectorAll(".ln").forEach((s) => s.addEventListener("change", check));
    check();
    $("#ln-save").addEventListener("click", () => {
      const units = {};
      document.querySelectorAll(".ln").forEach((s) => { (units[s.dataset.unit] = units[s.dataset.unit] || [])[+s.dataset.i] = s.value; });
      const parts = Object.entries(units).map(([u, ids]) => /^P/.test(u) && !ids.some((x) => x) ? `${u} none`
        : `${u} ${ids.filter((x) => x).join(", ")}`).filter((p) => !/ $/.test(p));
      cmd(`lines set ${parts.join("; ")}`);
    });
  };
  const tac = panel("Team system", `<p>Playing <b>${esc(d.system)}</b>${d.owner_identity ? `; the owner wants <b>${esc(d.owner_identity)}</b>${d.owner_identity === d.system ? " (he is pleased: +0.25 confidence a week)" : ""}` : ""}.</p>` +
    table(d.systems, [{key: "system", label: "System", fmt: (r) => `${r.system === d.system ? "<b>" + esc(r.system) + "</b>" : esc(r.system)}${r.system === d.owner_identity ? ' <span class="tag">owner</span>' : ""}`},
      {key: "fit", label: "Roster fit", num: 1, fmt: (r) => (r.fit > 0 ? "+" : "") + r.fit.toFixed(2)},
      {key: "execution", label: "Execution", num: 1, fmt: (r) => r.execution.toFixed(2)},
      {key: "value", label: "Value", num: 1, fmt: (r) => `<span class="${r.value > 0 ? "r4" : r.value < 0 ? "r1" : ""}">${r.value > 0 ? "+" : ""}${r.value.toFixed(1)}</span>`},
      {key: "m", label: "Attempts / allowed / quality / against / penalties", fmt: (r) => ["att", "allow_att", "qual", "allow_qual", "pen"].map((k) => `${((r.multipliers[k] - 1) * 100).toFixed(0)}%`).join(" / ")},
      {key: "x", label: "", fmt: (r) => r.system === d.system ? '<span class="muted">current</span>' : `<button class="mini" data-cmd="tactics ${esc(r.system)}">Play this</button>`}]) +
    `<p class="muted">Fit: your top 18 skaters in the system's attributes against the league's average club. Execution adds your head coach (coaching, and whether his style suits it). Value is a rough goal-difference index against an average club; each system breaks even at average fit.</p>`);
  const replaced = lu.replaced.length ? `<p><span class="tag warn">replaced for now</span> ${lu.replaced.map((p) => esc(byId[p] ? byId[p].name : "#" + p)).join(", ")} (unavailable; the depth chart fills in)</p>` : "";
  return `<div class="tabs"><b>${lu.custom ? "Your lines" : "Automatic lines"}</b> <span class="muted">${lu.custom ? "the engine uses these every game" : "from last season's ice time; edit and save to take over"}</span>
      <span class="spacer"></span><button class="primary" id="ln-save">Save lines</button> <button data-cmd="lines auto" data-confirm="Go back to automatic lines?">Automatic</button></div>
    <p id="ln-warn" class="neg"></p>${replaced}
    <div class="grid g2">${panel("Forwards", `<table class="lines">${F}</table>`, "F1-F4 get 38/31/20/11% of even-strength time")}
      <div class="grid">${panel("Defence", `<table class="lines">${D}</table>`, "40/35/25%")}${panel("Goal", `<table class="lines">${G}</table>`, "the starter plays about 82% of games")}</div>
      ${panel("Power play", `<table class="lines">${PP}</table><p class="muted">Leave a unit empty to have the power play drawn from the top lines. PP1 gets 65% of power-play time.</p>`)}
      ${panel("Penalty kill", `<table class="lines">${PK}</table><p class="muted">Special-teams players must also be in the lines.</p>`)}</div>
    <div class="grid">${tac}</div>`;
};

VIEWS.player = async (id) => {
  const p = await api("player", {id});
  const head = `<div class="row"><div class="big">${esc(p.name)}</div><span class="tag">${esc(p.position)}</span>
    <span class="muted">age ${p.age} · ${esc(p.nationality || "")} · shoots ${esc(p.shoots || "-")} · ${p.height_cm || "-"} cm / ${p.weight_kg || "-"} kg</span></div>
    <dl class="kv"><dt>Club</dt><dd>${esc(p.club)}${p.team ? ` (rights/contract: ${esc(p.team)})` : ""}</dd>
    <dt>Value</dt><dd>${p.value}</dd>${p.projection ? `<dt>Scouts' projection</dt><dd>${esc(p.projection)} <span class="muted">(estimate)</span></dd>` : ""}
    ${p.rights ? `<dt>Draft rights</dt><dd>${esc(p.rights.team)}, pick ${p.rights.pick} (${p.rights.draft_year}), until ${p.rights.expires}</dd>` : ""}
    ${p.contract ? `<dt>Contract</dt><dd>${mil(p.contract.cap_hit)} through ${p.contract.ends + 1}${p.contract.no_trade ? " · no-trade" : ""}</dd>` : ""}</dl>`;
  const attrs = p.attributes.map((g) => panel(g.title, `<div class="attr">${g.items.map((i) => `<span>${esc(i.label)}</span><span class="v ${ratingClass(i.value)}">${i.value}</span>`).join("")}</div>`)).join("");
  const statCols = p.position === "G"
    ? [{key: "season", label: "Season"}, {key: "league", label: "Lg"}, {key: "team", label: "Team"}, {key: "gp", label: "GP", num: 1}, {key: "sv_pct", label: "SV%", num: 1, fmt: (r) => r.sv_pct == null ? "-" : r.sv_pct.toFixed(3)}]
    : [{key: "season", label: "Season"}, {key: "league", label: "Lg"}, {key: "team", label: "Team"}, {key: "gp", label: "GP", num: 1}, {key: "g", label: "G", num: 1}, {key: "a", label: "A", num: 1}, {key: "pts", label: "P", num: 1}, {key: "pim", label: "PIM", num: 1}];
  const stats = panel("Career", `<div class="scroll">${table(p.stats, statCols)}</div>`);
  const ctr = panel("Contract history", table(p.contracts, [{key: "start_year", label: "From"}, {key: "years", label: "Yrs", num: 1},
    {key: "cap_hit", label: "AAV", num: 1, fmt: (r) => mil(r.cap_hit)}, {key: "team", label: "Team"}, {key: "contract_type", label: "Type"}]));
  const val = p.valuation ? panel(`Contract value: ${p.valuation.grade} (${p.valuation.words})`,
    `<p>Worth ${mil(p.valuation.value)} over the rest of the deal, costs ${mil(p.valuation.cost)}: surplus
     <b class="${p.valuation.surplus >= 0 ? "r4" : "r1"}">${p.valuation.surplus >= 0 ? "+" : ""}${mil(p.valuation.surplus)}</b>;
     ${Math.round(p.valuation.p_positive * 100)}% chance it ends up positive.</p>
     ${p.valuation.expected != null ? `<p class="muted">Expected surplus when signed ${mil(p.valuation.expected)}; ${p.valuation.phase === "optimism" ? "still the honeymoon (first four months)" : `regret so far ${p.valuation.regret >= 0 ? "+" : ""}${mil(p.valuation.regret || 0)}`}.</p>` : ""}
     ${p.valuation.elc ? `<p class="muted">Entry-level: signing bonus ${mil(p.valuation.elc.signing_bonus)}/yr, performance bonuses up to ${mil(p.valuation.elc.perf_max)}/yr (earned ${mil(p.valuation.elc.earned)})${p.valuation.elc.slides ? `; slid ${p.valuation.elc.slides} yr` : ""}${p.valuation.elc.leverage ? `; leverage: ${p.valuation.elc.leverage}` : ""}.</p>` : ""}
     ${p.valuation.untradeable ? `<p><span class="tag neg">untradeable without a sweetener</span></p>` : ""}` +
    table(p.valuation.rows, [{key: "season", label: "Season"}, {key: "age", label: "Age", num: 1},
      {key: "proj", label: "Proj", num: 1}, {key: "war", label: "WAR", num: 1}, {key: "worth", label: "Worth", num: 1, fmt: (r) => mil(r.worth)}])) : "";
  let mine = "";
  if (p.mine) {
    const m = p.morale;
    mine = m ? panel("Morale", `<dl class="kv">${["morale", "role", "team", "contract", "trust_mgmt", "trust_coach"].map((k) =>
      `<dt>${k.replace("_mgmt", " in you").replace("_coach", " in coach").replace("_", " ")}</dt><dd>${bar(m[k])}</dd>`).join("")}</dl>
      ${m.trade_request ? '<p><span class="tag neg">has requested a trade</span></p>' : ""}`) : "";
    if (p.personality) mine += panel("Personality", `<div class="attr">${Object.entries(p.personality).map(([k, v]) => `<span>${esc(k.replace("_", " "))}</span><span class="v">${v}</span>`).join("")}</div>`);
    if (p.concern) {
      const opts = [["supportive", "Reassure him"], ["direct", "Be candid"], ["firm", "Restate the standard"], ["diplomatic", "Non-committal"]];
      mine += panel("Wants to talk", `<p>He ${esc(p.concern.detail)} <span class="date">since ${esc(p.concern.since)}</span></p>
        <div class="row">${opts.map(([a, l]) => `<button data-cmd="respond ${p.player_id} ${a}">${l}</button>`).join("")}</div>
        <p><button class="primary" data-cmd="respond ${p.player_id} promise" data-confirm="This is a binding promise: ${esc(p.concern.promise)}. Breaking it will cost trust. Make it?">Promise: ${esc(p.concern.promise)}</button></p>`);
    }
    const actions = [];
    if (p.status === "prospect") actions.push(`<button data-cmd="recall ${p.player_id}">Recall</button>`);
    if (p.status === "active") actions.push(`<button data-cmd="senddown ${p.player_id}">Send down</button>`, `<button data-cmd="captain ${p.player_id}" data-confirm="Make him captain?">Make captain</button>`);
    actions.push(`<button class="danger" data-cmd="release ${p.player_id}" data-confirm="Release him? Any remaining contract is bought out.">Release / buy out</button>`);
    mine += panel("Actions", `<div class="row">${actions.join("")}</div>
      ${p.contract && p.contract.expiring ? `<p class="row"><button class="primary" data-talks="${p.player_id}">Negotiate an extension</button> <span class="muted">or straight to his ask:</span> <input id="ext-aav" size="8" placeholder="e.g. 3.5m"> years <input id="ext-yrs" size="2" value="3"> <button id="ext-go">Offer</button></p>` : ""}`);
  } else if (!p.team && p.status === "active" && !p.rights) {
    mine = panel("Free agent", `<p class="row"><button class="primary" data-talks="${p.player_id}">Negotiate</button> <button data-cmd="sign ${p.player_id}">Sign at his asking price</button></p>`);
  } else if (p.rights && STATE && p.rights.team === STATE.abbr) {
    mine = panel("Your draft pick", `<button class="primary" data-cmd="elc ${p.player_id}">Sign entry-level contract</button>`);
  }
  const ev = panel("History", `<ul class="list">${p.events.map((e) => `<li><span class="date">${esc(e.date)}</span>${esc(e.text)}</li>`).join("") || "<li class='muted'>Nothing yet.</li>"}</ul>`);
  setTimeout(() => {
    const go = $("#ext-go");
    if (go) go.onclick = () => cmd(`extend ${p.player_id} ${$("#ext-aav").value} ${$("#ext-yrs").value}`);
  });
  return `<div class="grid g21"><div class="grid">${panel("Profile", head)}<div class="grid g2">${attrs}</div>${stats}</div>
    <div class="grid">${mine}${val}${ctr}${ev}</div></div>`;
};

VIEWS.contracts = async () => {
  const d = await api("contracts");
  const pct = d.ceiling ? Math.round((d.payroll / d.ceiling) * 100) : null;
  const summary = `<div class="big">${money(d.payroll)}</div><div class="muted">${d.season}-${String((d.season + 1) % 100).padStart(2, "0")} payroll${d.ceiling ? ` of ${money(d.ceiling)} cap (${pct}%) · room ${money(d.room)} · floor ${money(d.floor)}` : " · no salary cap"}${d.max_contracts ? ` · contracts ${d.contracts}/${d.max_contracts}` : ""}</div>
    ${d.ceiling ? `<div class="bar ${pct > 100 ? "neg" : pct > 95 ? "warn" : "pos"}"><span style="width:${Math.min(100, pct)}%"></span></div>` : ""}`;
  const outlook = table(d.outlook, [{key: "season", label: "Season", fmt: (r) => ssn(r.season)}, {key: "payroll", label: "Committed", num: 1, fmt: (r) => money(r.payroll)}, {key: "committed", label: "Contracts", num: 1}]);
  const other = d.other_charges.length ? table(d.other_charges, [{key: "kind", label: "Charge"}, {key: "player", label: "Player"}, {key: "amount", label: "Amount", num: 1, fmt: (r) => money(r.amount)}]) : "<p class='muted'>No retained salary or buyout charges.</p>";
  const rows = d.players.filter((r) => r.contract);
  const cols = [{key: "name", label: "Name", fmt: (r) => plink(r.player_id, r.name)}, {key: "pos", label: "Pos"}, {key: "age", label: "Age", num: 1},
    {key: "value", label: "Val", num: 1}, {key: "hit", label: "Cap hit", num: 1, fmt: (r) => mil(r.contract.cap_hit)},
    {key: "ends", label: "Final season", num: 1, fmt: (r) => ssn(r.contract.ends)}, {key: "type", label: "Type", fmt: (r) => esc(ctype(r.contract.type))},
    {key: "st", label: "Status", fmt: (r) => (r.status === "prospect" ? '<span class="tag">minors</span> ' : "") + (r.contract.expiring ? `<span class="tag warn">${esc(r.contract.status_at_expiry)}</span>` : "")},
    {key: "ask", label: "Asks", num: 1, fmt: (r) => r.asking ? `${mil(r.asking)} <button class="mini" data-talks="${r.player_id}">Talk</button>` : ""},
    {key: "grade", label: "Value", fmt: (r) => r.grade ? `<span class="tag ${"AB".includes(r.grade) ? "pos" : r.grade === "C" ? "" : "neg"}" title="surplus ${mil(r.surplus)}">${r.grade}</span>` : ""}];
  return `<div class="grid g21"><div class="grid">${panel("Cap", summary)}${panel("Contracts", `<div class="scroll">${table(rows, cols)}</div>`)}</div>
    <div class="grid">${panel("Outlook", outlook)}${panel("Retained & buyouts", other)}</div></div>`;
};

VIEWS.offseason = async () => {
  const d = await api("offseason");
  const idx = d.phases.indexOf(d.phase);
  const steps = `<div class="phases">${d.phases.map((p, i) => `<span class="${i < idx ? "done" : i === idx ? "now" : ""}">${esc(p.replace("_", " "))}</span>`).join("")}</div>`;
  const parts = [panel("Phase", steps + (d.phase === "regular_season" ? "<p class='muted'>The offseason opens after the playoffs. Draft rights and free agents are below.</p>" : `<button class="primary" data-cmd="offseason">Next offseason phase</button>`))];
  if (d.draft && (d.phase === "draft" || d.draft.picks.some((p) => p.player))) {
    if (d.draft.board) {
      parts.push(panel(`Draft board ${d.draft.year}${d.draft.on_clock ? " - YOU ARE ON THE CLOCK" : ""}`,
        `<div class="scroll">${boardTable(d.draft.board, d.draft.on_clock)}</div>`));
    }
    const mine = d.draft.picks.filter((p) => p.mine);
    parts.push(panel("Your picks", table(mine, [{key: "overall", label: "Pick", num: 1}, {key: "round", label: "Rd", num: 1},
      {key: "note", label: "Note", fmt: (r) => esc(r.note || "")}, {key: "player", label: "Selection", fmt: (r) => r.player ? plink(r.player_id, r.player) : "-"}])));
  }
  if (d.rights.length) {
    parts.push(panel("Expiring contracts", table(d.rights, [
      {key: "name", label: "Player", fmt: (r) => plink(r.player_id, r.name)}, {key: "status", label: "Sts"},
      {key: "prev_aav", label: "Prev", num: 1, fmt: (r) => mil(r.prev_aav)}, {key: "qo", label: "QO", num: 1, fmt: (r) => r.qo ? mil(r.qo) : "-"},
      {key: "asking", label: "Asks", num: 1, fmt: (r) => mil(r.asking)}, {key: "arb", label: "Arb", fmt: (r) => r.arb_eligible ? "yes" : ""},
      {key: "dec", label: "Decision", fmt: (r) => esc(r.outcome || (r.award ? `award ${r.award_years}y x ${mil(r.award)}` : r.arb_elected_by ? `${r.arb_elected_by}-elected: ask ${mil(r.player_ask)} / offer ${mil(r.team_offer)}` : r.status === "RFA" ? ({1: "qualified", 0: "not qualified"}[r.qualified] ?? "undecided") : "undecided"))},
      {key: "act", label: "", fmt: (r) => r.outcome ? "" : [
        d.phase === "rights" && r.status === "RFA" ? `<button data-cmd="qualify ${r.player_id}">Qualify</button> <button data-cmd="decline ${r.player_id}">Decline</button>` : "",
        ["rights", "arbitration"].includes(d.phase) && r.status === "RFA" && r.arb_eligible && !r.arb_elected_by ? `<button data-cmd="arbitrate ${r.player_id}">Club arbitration</button>` : "",
        d.phase === "awards" && r.award ? `<button class="danger" data-cmd="walkaway ${r.player_id}" data-confirm="Walk away from this award? He becomes a UFA.">Walk away</button>` : "",
        ["finished", "rights", "arbitration"].includes(d.phase) ? `<button class="primary" data-talks="${r.player_id}">Negotiate</button> <button data-cmd="extend ${r.player_id} ${Math.ceil(r.asking / 5000) * 5000} 3">Re-sign at ask (3y)</button>` : ""].join(" ")}])));
  }
  if (d.offer_sheets && d.offer_sheets.length) {
    parts.push(panel("Offer sheets this summer", table(d.offer_sheets, [
      {key: "name", label: "Player", fmt: (r) => plink(r.player_id, r.name)}, {key: "owner", label: "His club"}, {key: "by", label: "Offered by"},
      {key: "aav", label: "Terms", num: 1, fmt: (r) => `${r.years} yr x ${mil(r.aav)}`}, {key: "comp", label: "Compensation"},
      {key: "status", label: "Status", fmt: (r) => esc(r.status + (r.note ? ` (${r.note})` : ""))},
      {key: "go", label: "", fmt: (r) => r.mine && r.status === "pending" ? `<button class="primary" data-cmd="match ${r.player_id}">Match</button>` : ""}])));
  }
  if (d.upcoming && d.upcoming.length) {
    parts.push(panel("Upcoming free agents (market opens 1 July, noon)", `<p class="muted">Offers registered now are heard at noon,
      alongside every other club's. Type in the command box: <code>offer &lt;player&gt; &lt;aav&gt; &lt;years&gt;</code>.</p><div class="scroll">${table(d.upcoming, [
      {key: "name", label: "Player", fmt: (r) => plink(r.player_id, r.name)}, {key: "pos", label: "Pos"}, {key: "age", label: "Age", num: 1},
      {key: "tier", label: "Tier", num: 1}, {key: "team", label: "Club"}, {key: "ask", label: "Wants at noon", num: 1, fmt: (r) => `${r.years} yr x ${mil(r.ask)}`},
      {key: "fair", label: "Fair value", num: 1, fmt: (r) => mil(r.fair)},
      {key: "go", label: "", fmt: (r) => `<button data-cmd="offer ${r.player_id} ${r.ask} ${r.years}">Offer his ask</button>`}])}</div>`));
  }
  if (d.free_agents && d.free_agents.length && d.phase !== "draft") {
    parts.push(panel("Free agents", `<div class="scroll">${table(d.free_agents, [
      {key: "name", label: "Player", fmt: (r) => plink(r.player_id, r.name)}, {key: "pos", label: "Pos"}, {key: "age", label: "Age", num: 1},
      {key: "value", label: "Val", num: 1}, {key: "asking", label: "Asks", num: 1, fmt: (r) => mil(r.asking)},
      {key: "go", label: "", fmt: (r) => `<button class="primary" data-talks="${r.player_id}">Negotiate</button> <button data-cmd="sign ${r.player_id}">Sign at ask</button>`}])}</div>`));
  }
  if (d.prospects.length) {
    parts.push(panel("Your unsigned draft picks", table(d.prospects, [
      {key: "name", label: "Prospect", fmt: (r) => plink(r.player_id, r.name)}, {key: "pos", label: "Pos"}, {key: "age", label: "Age", num: 1},
      {key: "pick", label: "Pick", num: 1}, {key: "expires", label: "Rights to", num: 1}, {key: "club", label: "Playing for"},
      {key: "go", label: "", fmt: (r) => `<button data-cmd="elc ${r.player_id}">Sign ELC</button>`}])));
  }
  return `<div class="grid">${parts.join("")}</div>`;
};

function cm2ftin(cm) { if (!cm) return "-"; const i = Math.round(cm / 2.54); return `${Math.floor(i / 12)}'${i % 12}"`; }
function boardTable(rows, onClock) {
  return table(rows, [
    {key: "rank", label: "#", num: 1}, {key: "name", label: "Prospect", fmt: (r) => plink(r.player_id, r.name)},
    {key: "pos", label: "Pos"}, {key: "age", label: "Age", num: 1},
    {key: "height", label: "Ht", num: 1, fmt: (r) => `${r.height || "-"} <span class="muted">${cm2ftin(r.height)}</span>`},
    {key: "nat", label: "Nat"}, {key: "grade", label: "Scouts' projection"}, {key: "line", label: "Last season", fmt: (r) => esc(r.line || "-")},
    {key: "club", label: "Playing for"},
    {key: "flags", label: "Notes", fmt: (r) => r.flags.map((f) => `<span class="tag ${f.startsWith("KHL") ? "warn" : ""}">${esc(f)}</span>`).join(" ")},
    {key: "go", label: "", fmt: (r) => onClock ? `<button class="primary" data-cmd="pick ${r.player_id}">Draft</button>` : ""}]);
}

VIEWS.scouting = async () => {
  const d = await api("scouting");
  return `<div class="grid">${panel(`Scouting: ${d.year} draft`, `<p>Your director of amateur scouting is <b>${esc(d.style_label)}</b>.
    Projections are your scouts' view, not the truth: the whole league shares some blind spots, and your staff add about
    &plusmn;${d.error} of their own. Small players, Europeans and Russians under KHL contract tend to be marked down by
    traditional scouts; late developers fool everyone. Hire a different director under Staff to change the lens.</p>`)}
    ${panel("Prospects", `<div class="scroll">${boardTable(d.board, false)}</div>`)}</div>`;
};

VIEWS.standings = async (mode = "division") => {
  const d = await api("standings", {mode});
  const tabs = `<div class="tabs">${["division", "conference", "league"].map((m) => `<a class="btn${m === mode ? " active" : ""}" href="#standings/${m}">${m}</a>`).join(" ")}</div>`;
  return tabs + `<div class="grid g2">${Object.entries(d).map(([k, rows]) => panel(k, table(rows, [
    {key: "abbr", label: "Team", fmt: (r) => `${esc(r.abbr)} <span class="muted">${esc(r.name)}</span>`}, {key: "gp", label: "GP", num: 1},
    {key: "w", label: "W", num: 1}, {key: "l", label: "L", num: 1}, {key: "otl", label: "OTL", num: 1},
    ...(rows.some((x) => x.t) ? [{key: "t", label: "T", num: 1}] : []), {key: "pts", label: "PTS", num: 1},
    {key: "gf", label: "GF", num: 1}, {key: "ga", label: "GA", num: 1}, {key: "diff", label: "+/-", num: 1, fmt: (r) => r.gf - r.ga}],
    {rowClass: (r) => r.mine ? "mine" : ""}))).join("")}</div>`;
};

VIEWS.schedule = async () => {
  const d = await api("schedule");
  return `<div class="grid g2">${panel("Upcoming", table(d.upcoming, [{key: "date", label: "Date"}, {key: "opp", label: "Opponent", fmt: (r) => `${r.home ? "vs" : "@"} ${esc(r.opponent)}`}]))}
    ${panel("Results", table(d.results, [{key: "date", label: "Date"}, {key: "opp", label: "Opponent", fmt: (r) => `${r.home ? "vs" : "@"} ${esc(r.opponent)}`},
      {key: "res", label: "Result", fmt: (r) => `<span class="tag ${r.result === "W" ? "pos" : r.result === "L" ? "neg" : "warn"}">${r.result}</span> ${r.gf}-${r.ga} ${esc(r.ot)}${r.playoff ? " (playoffs)" : ""}`},
      {key: "g", label: "", fmt: (r) => `<a class="btn" href="#game/${r.game_id}">Recap &amp; replay</a>`}]))}</div>`;
};

VIEWS.history = async (scope = "club") => {
  const d = await api("history", {scope});
  const tabs = `<div class="tabs"><a class="btn${scope === "club" ? " active" : ""}" href="#history/club">Your club</a> <a class="btn${scope === "league" ? " active" : ""}" href="#history/league">League</a> <a class="btn${scope === "trades" ? " active" : ""}" href="#history/trades">Trades</a> <button data-cmd="jobs">Vacancies</button></div>`;
  return tabs + panel({club: "Organisational history", league: "League news", trades: "League trades"}[scope] || "History", table(d, [{key: "date", label: "Date"}, {key: "type", label: "Type", fmt: (r) => `<span class="tag">${esc(r.type.toLowerCase().replace(/_/g, " "))}</span>`},
    {key: "text", label: "Event", fmt: (r) => r.player_id ? plink(r.player_id, r.text) : esc(r.text)}]));
};

VIEWS.inbox = async () => {
  const d = await api("inbox", {all: "1"});
  return panel("Inbox", `<p><button data-cmd="inbox">Mark all read</button></p><ul class="list">${d.map((m) => `<li><span class="date">${esc(m.date)}</span><b>${esc(m.subject)}</b>${m.read ? "" : ' <span class="tag warn">new</span>'}<br>${esc(m.body)}</li>`).join("") || "<li class='muted'>Empty.</li>"}</ul>`);
};

// ---------------------------------------------------------------- news (hs/game/media.py)
VIEWS.news = async (arg = "headlines") => {
  const [tab, scope] = (arg || "headlines").split(":");
  const d = await api("news", {scope: scope || "club"});
  const t = (k, label) => `<a class="btn${tab === k ? " active" : ""}" href="#news/${k}${scope ? ":" + scope : ""}">${label}</a>`;
  const sc = (k, label) => `<a class="btn${(scope || "club") === k ? " active" : ""}" href="#news/${tab}:${k}">${label}</a>`;
  const tabs = `<div class="tabs">${t("headlines", "Headlines")} ${t("recaps", "Game recaps")} ${t("social", "Social")} ${t("power", "Power rankings")}
    <span class="spacer"></span>${tab === "headlines" || tab === "recaps" ? `${sc("club", "Your club")} ${sc("league", "League")}` : ""}</div>`;
  let body = "";
  if (tab === "headlines") {
    body = panel(`${d.headlines[0] ? esc(d.headlines[0].outlet) : "News"}`, `<ul class="news">${d.headlines.map((h) =>
      `<li><div class="meta"><span class="date">${esc(h.date)}</span> <span class="tag">${esc(h.tag)}</span> ${esc(h.team)}</div>
       <div class="headline"><a href="#article/${h.event_id}">${esc(h.headline)}</a></div>
       <div class="muted">${esc(h.body)}</div></li>`).join("") || "<li class='muted'>Nothing yet.</li>"}</ul>`);
  } else if (tab === "recaps") {
    body = panel("The Morning Skate", `<ul class="news">${d.recaps.map((r) =>
      `<li><div class="meta"><span class="date">${esc(r.date)}</span> ${esc(r.score)}</div>
       <div class="headline"><a href="#game/${r.game_id}">${esc(r.headline)}</a></div><div class="muted">${esc(r.lede)}</div></li>`).join("") || "<li class='muted'>No games yet.</li>"}</ul>`);
  } else if (tab === "social") {
    body = panel("Feed", `<ul class="feed">${d.social.map((p) =>
      `<li class="${p.mine ? "mine" : ""}"><div class="meta"><b>${esc(p.account)}</b> <span class="date">${esc(p.date)}</span></div>
       <div>${p.game_id ? `<a href="#game/${p.game_id}">${esc(p.text)}</a>` : p.player_id ? `<a href="#player/${p.player_id}">${esc(p.text)}</a>` : esc(p.text)}</div>
       ${p.replies.map((r) => `<div class="reply"><b>${esc(r.account)}</b> ${esc(r.text)}</div>`).join("")}</li>`).join("") || "<li class='muted'>Quiet so far.</li>"}</ul>
       <p class="muted">Fictional accounts: @InsiderOnIce (trades, front offices), @CapCrunchHQ (contracts), @PipelineScout (draft and prospects), and your fans.</p>`);
  } else {
    body = panel("Power rankings", table(d.power, [{key: "rank", label: "#", num: 1},
      {key: "move", label: "", num: 1, fmt: (r) => r.move > 0 ? `<span class="r4">&#9650;${r.move}</span>` : r.move < 0 ? `<span class="r1">&#9660;${-r.move}</span>` : `<span class="muted">-</span>`},
      {key: "team", label: "Team", fmt: (r) => `<b>${esc(r.team)}</b> <span class="muted">${esc(r.name)}</span>`},
      {key: "gp", label: "GP", num: 1}, {key: "pts", label: "PTS", num: 1}, {key: "diff", label: "+/-", num: 1, fmt: (r) => (r.diff > 0 ? "+" : "") + r.diff},
      {key: "last10", label: "L10"}, {key: "blurb", label: ""}], {rowClass: (r) => r.mine ? "mine" : ""}));
  }
  return tabs + body;
};

// ---------------------------------------------------------------- one game: recap + 2D replay (replay.js)
VIEWS.game = async (id) => {
  const d = await api("game", {id});
  const r = d.recap;
  const lineHead = `<tr><th></th>${r.periods.map((p) => `<th class="num">${esc(p)}</th>`).join("")}<th class="num">T</th><th class="num">SOG</th></tr>`;
  const lineRows = Object.entries(r.line).map(([ab, cells]) => `<tr><td><b>${esc(ab)}</b></td>${cells.map((c) => `<td class="num">${c[0]}</td>`).join("")}
    <td class="num"><b>${ab === r.home ? r.home_goals : r.away_goals}</b></td>
    <td class="num">${cells.reduce((a, c) => a + c[1], 0)}</td></tr>`).join("");
  const goals = r.goals.map((g) => `<tr><td>${esc(g.period)}</td><td class="num">${esc(g.time)}</td><td>${esc(g.team)}</td>
    <td>${plink(g.scorer_id, g.scorer)}${g.en ? ' <span class="tag">EN</span>' : ""} <span class="muted">${g.assists.length ? g.assists.map((a) => esc(a.name)).join(", ") : "unassisted"}</span></td><td class="num">${esc(g.score)}</td></tr>`).join("");
  const so = r.shootout.length ? `<p><b>Shootout:</b> ${r.shootout.map((x) => `${esc(x.team)} ${esc(x.shooter)} ${x.scored ? "&#10003;" : "&#10007;"}`).join(" · ")}</p>` : "";
  const stars = r.stars.map((s, i) => `<li><b>${i + 1}.</b> ${plink(s.player_id, s.name)} <span class="muted">${esc(s.line)}</span></li>`).join("");
  const pens = r.penalties.map((p) => `<li><span class="date">${esc(p.period)} ${esc(p.time)}</span>${esc(p.team)} ${plink(p.player_id, p.player)} <span class="muted">${esc(p.detail)}</span></li>`).join("") || "<li class='muted'>None.</li>";
  AFTER = () => Replay.mount($("#replay"), d.replay);
  return `<div class="tabs"><a class="btn" href="#schedule">&larr; Schedule</a> <a class="btn" href="#news/recaps">Recaps</a></div>
    <div class="grid g21">
      <div class="grid">${panel(`${r.away} ${r.away_goals} @ ${r.home} ${r.home_goals} ${r.ot}`, `<div id="replay" class="replay"></div>`, esc(r.date) + (r.playoff ? " · playoffs" : ""))}</div>
      <div class="grid">${panel(r.outlet, `<h3 class="headline">${esc(r.headline)}</h3><p>${esc(r.lede)}</p>`)}
        ${panel("Score by period", `<table>${lineHead}${lineRows}</table>${so}`)}
        ${panel("Three stars", `<ul class="list">${stars || "<li class='muted'>-</li>"}</ul>`)}</div>
    </div>
    <div class="grid g2">${panel("Scoring", `<table><tr><th>Per</th><th class="num">Time</th><th>Team</th><th>Goal</th><th class="num">Score</th></tr>${goals || ""}</table>`)}
      ${panel("Penalties", `<ul class="list">${pens}</ul>`)}</div>`;
};

// ---------------------------------------------------------------- trades (hs/game/gm_trades.py)
VIEWS.trade = async (team) => {
  const d = await api("trade", team ? {team} : {});
  const POST = {contender: "contending", middle: "middle of the pack", seller: "rebuilding"};
  const GRP = {F: "forwards", D: "defence", G: "goal"};
  const pick = `<label>Trade with <select id="tr-team"><option value="">choose a club</option>${d.teams.map((t) =>
    `<option value="${t.team_id}"${t.team_id === d.team_id ? " selected" : ""}>${esc(t.abbr)} (${POST[t.posture]}, needs ${GRP[t.need]})</option>`).join("")}</select></label>`;
  const status = d.window.open ? `<span class="muted">Deadline ${esc(d.deadline)}</span>` : `<span class="tag neg">${esc(d.window.why)}</span>`;
  const offers = d.offers.length ? `<ul class="list">${d.offers.map((o) => `<li>${esc(o.text)} <span class="muted">${esc(o.note || "")}</span>
      <button class="primary" data-cmd="accept ${o.offer_id}">Accept</button> <button data-cmd="decline ${o.offer_id}">Decline</button></li>`).join("")}</ul>`
    : `<p class="muted">No offers. Clubs call about three times as often while you have players on the block.</p>`;
  const side = (assets, mine) => {
    const rows = assets.players.map((p) => `<tr class="tr-row${p.moved ? " muted" : ""}"><td><input type="checkbox" class="tr-a" data-side="${mine ? "give" : "get"}" value="${p.key}" data-name="${esc(p.name)}" data-pos="${esc(p.pos)}" data-age="${p.age}" data-cap="${p.cap || 0}" data-val="${p.value.toFixed(0)}" data-pid="${p.player_id}"${p.moved ? " disabled" : ""}></td>
      <td>${clink(p.player_id, p.name)}${p.core ? ' <span class="tag">core</span>' : ""}${p.block ? ' <span class="tag warn">block</span>' : ""}${p.status === "prospect" ? ' <span class="tag">minors</span>' : ""}${p.moved ? ' <span class="tag">just moved</span>' : ""}</td>
      <td>${esc(p.pos)}</td><td class="num">${p.age}</td><td class="num">${p.cap ? mil(p.cap) : "-"}${p.ends ? ` <span class="muted">to ${p.ends}</span>` : ""}</td><td class="num"><b>${p.value.toFixed(0)}</b></td>
      ${mine ? `<td>${p.block ? `<button class="mini" data-cmd="block remove ${p.player_id}">Unblock</button>` : `<button class="mini" data-cmd="block ${p.player_id}">Block</button>`} <button class="mini" data-cmd="shop ${p.player_id}" data-confirm="Shop ${esc(p.name)}? Interested clubs call over the next days; most open low unless they need him." title="Tell the league he is available">Shop</button></td>` : ""}</tr>`).join("");
    const picks = assets.picks.map((k) => `<label class="pickchip"><input type="checkbox" class="tr-a" data-side="${mine ? "give" : "get"}" value="${k.key}" data-name="${esc(k.label)}" data-pos="pick" data-cap="0" data-val="${k.value.toFixed(0)}"> ${esc(k.label)} <span class="muted">${k.value.toFixed(0)}</span></label>`).join("");
    return `<div class="scroll tr-list"><table><tr><th></th><th>Player</th><th>Pos</th><th class="num">Age</th><th class="num">Cap hit</th><th class="num">Value</th>${mine ? "<th></th>" : ""}</tr>${rows}</table></div>
      <div class="picks">${picks || "<span class='muted'>No tradeable picks.</span>"}</div>`;
  };
  AFTER = () => {
    const sel = $("#tr-team");
    sel.addEventListener("change", () => { location.hash = "trade/" + sel.value; });
    if (!d.team_id) return;
    const keys = (s) => [...document.querySelectorAll(`.tr-a[data-side="${s}"]:checked`)].map((x) => x.value);
    const box = $("#tr-eval");
    async function evaluate() {
      const give = keys("give"), get = keys("get");
      if (!give.length && !get.length) { box.innerHTML = '<p class="muted">Tick what you give and what you want.</p>'; return; }
      const e = await api("tradeeval", {team: d.team_id, give: give.join(","), get: get.join(",")});
      const pct = e.ratio == null ? "" : ` <b>${Math.round(e.ratio * 100)}%</b> of what they give (they want ${Math.round(e.need_ratio * 100)}%)`;
      box.innerHTML = `<p><span class="tag ${e.accept ? "pos" : "neg"}">${e.accept ? "they would accept" : "they would say no"}</span>${pct}</p>
        ${bar(Math.min(100, (e.ratio == null ? 1 : e.ratio / e.need_ratio) * 50))}<p class="muted">${esc(e.why)}</p>`;
    }
    document.querySelectorAll(".tr-a").forEach((x) => x.addEventListener("change", evaluate));
    $("#tr-propose").addEventListener("click", () => {
      const give = keys("give"), get = keys("get");
      if (!give.length && !get.length) return toast("Pick something to trade.", true);
      cmd(`trade ${d.their_abbr} give ${give.join(", ")} get ${get.join(", ")}`);
    });
    $("#tr-ask").addEventListener("click", async () => {
      const get = keys("get");
      if (!get.length) return toast("Tick what you want from them first.", true);
      const r = await api("tradeask", {team: d.team_id, get: get.join(",")});
      document.querySelectorAll('.tr-a[data-side="give"]').forEach((x) => (x.checked = r.give.includes(x.value)));
      toast(r.why, !r.give.length);
      evaluate();
    });
    $("#tr-clear").addEventListener("click", () => { document.querySelectorAll(".tr-a").forEach((x) => (x.checked = false)); evaluate(); });
    evaluate();
  };
  const top = `<div class="tabs">${pick} ${status}</div>`;
  if (!d.team_id) return top + `<div class="grid g2">${panel("Offers to you", offers)}${panel(`${d.abbr}: your assets`, side(d.mine, true))}</div>`;
  return top + `<div class="grid g-trade">
      ${panel(`${d.abbr}: you give`, side(d.mine, true))}
      ${panel(`${d.their_abbr}: you get`, side(d.theirs, false), `${POST[d.posture]}, weakest at ${GRP[d.need]}`)}
      <div class="grid">${panel("The proposal", `<div id="tr-tray" class="tray"></div>`)}${panel("Their view", `<div id="tr-eval"></div>
          <p><button class="primary" id="tr-propose">Propose</button> <button id="tr-ask">What would it take?</button> <button id="tr-clear">Clear</button></p>
          <p class="muted">Values are the league's view (ratings and NHL production, contract surplus, picks by slot), weighted by each club's position. Retain salary with the command box: <code>trade ${esc(d.their_abbr)} give ... get ... retain &lt;player&gt;=50</code>.</p>`)}
        ${panel("Offers to you", offers)}</div></div>`;
};

// ---------------------------------------------------------------- staff and board (hs/game/staff.py, hs/game/org.py)
VIEWS.staff = async (role) => {
  const d = await api("staff", role ? {role} : {});
  if (!d.enabled) return panel("Staff", "This save has no staff (start a new game with the management layer).");
  const attr = (r, k) => `<span class="${ratingClass(r[k])}">${r[k] ?? "-"}</span>`;
  const cols = (mine) => [{key: "role_name", label: "Role"}, {key: "name", label: "Name"}, {key: "age", label: "Age", num: 1},
    ...["coaching", "development", "evaluation", "medical", "communication", "leadership"].map((k) => ({key: k, label: k.slice(0, 5), num: 1, fmt: (r) => attr(r, k)})),
    {key: "style", label: "Style", fmt: (r) => esc(r.style || "")}, {key: "salary", label: "Salary", num: 1, fmt: (r) => mil(r.salary)},
    mine ? {key: "contract_end", label: "Through", num: 1, fmt: (r) => r.contract_end === 9999 ? "-" : r.contract_end} : {key: "reputation", label: "Rep", num: 1},
    {key: "act", label: "", fmt: (r) => mine && r.contract_end === 9999 ? '<a class="tag" href="#gm">you</a>' : mine ? `<button class="mini" data-cmd="dismiss ${r.staff_id}" data-confirm="Let ${esc(r.name)} go?">Dismiss</button>`
      : (d.held[r.role] || 0) >= d.limits[r.role] ? `<span class="muted">role full</span>` : `<button class="mini primary" data-cmd="hire ${r.staff_id}">Hire</button>`}];
  const e = d.effects;
  const fx = `<dl class="kv"><dt>Scouting</dt><dd>draft estimates off by about ${e.scout_sd} rating points (league default 0.75; lower is better)</dd>
    <dt>Development</dt><dd>young players develop at x${e.development}</dd><dt>Medical</dt><dd>injuries last x${e.injury}</dd></dl>
    <p class="muted">The head coach's coaching sets how well the team plays to its ratings; the scouting director and scouts set the fog on draft prospects; development coaches speed growth; medical staff shorten injuries.</p>`;
  const roles = `<div class="tabs"><a class="btn${!role ? " active" : ""}" href="#staff">All roles</a> ${Object.entries(d.roles).map(([k, v]) =>
    `<a class="btn${role === k ? " active" : ""}" href="#staff/${k}">${esc(v)} ${d.held[k] || 0}/${d.limits[k]}</a>`).join(" ")}</div>`;
  return roles + `<div class="grid">${panel("What your staff does for you", fx)}${panel("Your staff", table(d.mine, cols(true)))}
    ${panel(`Staff market${role ? ": " + d.roles[role] : ""}`, `<div class="scroll">${table(d.market, cols(false))}</div>`, "best at their main job first")}</div>`;
};

VIEWS.board = async () => {
  const d = await api("board");
  if (!d.enabled) return panel("Board", "This save has no board (start a new game with the management layer).");
  const o = d.owner;
  const trait = (k, label) => `<dt>${label}</dt><dd>${bar(o[k] * 10, 100)}</dd>`;
  const trait01 = (k, label) => `<dt>${label}</dt><dd>${bar((o[k] || 0) * 100, 100)}</dd>`;
  const h = d.hot;
  const hotPanel = h ? panel("Hot seat (weekly)", `<div class="big">${h.T.toFixed(2)} <span class="muted">trigger score</span>
      ${d.ultimatum ? '<span class="tag neg">ultimatum</span>' : h.T <= d.rumour_at ? '<span class="tag warn">rumours</span>' : ""}</div>
      <p class="mono">${h.confidence.toFixed(2)} confidence ${h.velocity >= 0 ? "+" : "-"} ${Math.abs(h.velocity).toFixed(2)} velocity x ${h.patience_impact.toFixed(2)} patience
       - ${h.pressure.toFixed(2)} pressure x ${(h.vocalness || 0).toFixed(2)} vocalness</p>
      <p class="muted">An ultimatum comes at ${d.warn_at}; leaks start at ${d.rumour_at} if the owner talks. Velocity is the four-week change in confidence; pressure is your market plus any losing streak.</p>`) : "";
  const ult = d.ultimatum ? panel("Ultimatum", `<p><b>${d.ultimatum.need} points</b> from <b>${d.ultimatum.games} games</b> (issued ${esc(d.ultimatum.issued)}).</p>
      <p>So far: ${d.ultimatum.got} points from ${d.ultimatum.played} games. ${d.ultimatum.got >= d.ultimatum.need ? "Met." : `${d.ultimatum.need - d.ultimatum.got} more needed in ${Math.max(0, d.ultimatum.games - d.ultimatum.played)} games.`}</p>
      ${bar(Math.min(100, d.ultimatum.got / d.ultimatum.need * 100))}<p class="muted">Miss it and you are fired. Dismissing the head coach buys three more games, once a season.</p>`) : "";
  const dirs = d.directives.length ? panel("Owner's directives", table(d.directives, [{key: "issued", label: "Issued"}, {key: "description", label: "Directive"},
      {key: "deadline", label: "Deadline"}, {key: "status", label: "Status", fmt: (r) => `<span class="tag ${r.status === "met" ? "pos" : r.status === "failed" ? "neg" : "warn"}">${esc(r.status)}</span>`}])) : "";
  const wk = d.weekly.length > 1 ? (() => {
    const w = 320, hh = 70, n = d.weekly.length;
    const line = (f) => d.weekly.map((x, i) => `${(i / (n - 1) * w).toFixed(1)},${(hh - Math.max(0, Math.min(1, f(x))) * hh).toFixed(1)}`).join(" ");
    return `<svg viewBox="0 0 ${w} ${hh}" preserveAspectRatio="none" class="spark tall"><line x1="0" x2="${w}" y1="${hh * (1 - d.warn_at)}" y2="${hh * (1 - d.warn_at)}" class="danger-line"/>
      <polyline points="${line((x) => x.confidence / 100)}"/><polyline class="trig" points="${line((x) => x.trigger)}"/></svg>
      <p class="muted">Weekly: confidence (blue) and trigger score (orange); the dashed line is the ultimatum threshold.</p>`;
  })() : "";
  const spark = d.trend.length > 1 ? (() => {
    const w = 320, h = 60, n = d.trend.length;
    const pts = d.trend.map((t, i) => `${(i / (n - 1) * w).toFixed(1)},${(h - t.confidence / 100 * h).toFixed(1)}`).join(" ");
    return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" class="spark" role="img" aria-label="Board confidence over time"><line x1="0" x2="${w}" y1="${h * 0.65}" y2="${h * 0.65}" class="danger-line"/><polyline points="${pts}"/></svg>
      <p class="muted">Confidence at each review (${esc(d.trend[0].date)} to ${esc(d.trend[n - 1].date)}); the line marks 35, the danger zone.</p>`;
  })() : "";
  const obj = table(d.objectives, [{key: "season_start_year", label: "Season", fmt: (r) => ssn(r.season_start_year)},
    {key: "importance", label: "", fmt: (r) => `<span class="tag ${r.importance === "required" ? "warn" : ""}">${esc(r.importance)}</span>`},
    {key: "description", label: "Objective"}, {key: "status", label: "Status", fmt: (r) => `<span class="tag ${r.status === "met" ? "pos" : r.status === "failed" ? "neg" : ""}">${esc(r.status)}</span>`},
    {key: "result", label: "Result", fmt: (r) => esc(r.result || "")}]);
  const rev = `<ul class="list">${d.reviews.map((r) => `<li><span class="date">${esc(r.date)}</span><b>${esc(r.kind)}</b> <span class="${r.delta >= 0 ? "r4" : "r1"}">${r.delta >= 0 ? "+" : ""}${r.delta}</span> to ${r.confidence}
    <br><span class="muted">${r.reasons.map(esc).join(" · ")}</span></li>`).join("") || "<li class='muted'>No reviews yet.</li>"}</ul>`;
  return `<div class="grid g21"><div class="grid">
      ${ult}${panel("Board confidence", `<div class="big">${d.confidence} <span class="muted">${esc(d.label)}</span>${d.warning ? ' <span class="tag neg">final warning</span>' : ""}</div>${bar(d.confidence)}${wk || spark}`)}
      ${hotPanel}${dirs}
      ${panel("Objectives", obj)}${panel("Reviews", rev)}</div>
    <div class="grid">${panel(`Owner: ${o.name || ""}`, `<p><b>${esc(o.archetype || "")}</b>: ${esc(o.summary)}. Wants ${esc(o.identity || "results")}.</p><dl class="kv">${trait01("vocalness", "Vocalness")}${trait01("analytics", "Analytics bias")}${trait("spend", "Spending")}${trait("ambition", "Ambition")}${trait("patience", "Patience")}
      ${trait("risk", "Appetite for risk")}${trait("youth_pref", "Youth")}${trait("involvement", "Involvement")}</dl>`)}
      ${d.vacancies.length ? panel("GM vacancies", `<p>${d.vacancies.map(esc).join(", ")}</p><p class="muted">Clubs that changed GM this offseason (\`jobs\`, \`takejob\`).</p>`) : ""}</div></div>`;
};

