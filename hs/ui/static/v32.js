"use strict";
// v32, phase A2: your manager. Ratings with points to spend, reputation, GM only or GM and head coach, a career
// that cannot end in a firing, starting unemployed and the Job Centre, the assistant GM, and Find Players.

/* ================================================================ out of work: only the screens that need no club */
const UNEMPLOYED_VIEWS = new Set(["jobs", "gm", "news", "standings", "stats", "player", "team", "leagueday", "season", "reports", "milestones", "draftlog",
  "rules", "article", "game", "inbox", "playoffs", "champions", "awards", "find", "teaminfo", "txnlog", "transactions", "notes"]);
const renderV32 = render;
render = async function () {
  const view = (location.hash.slice(1) || "dashboard").split("/")[0];
  if (STATE && STATE.unemployed && !UNEMPLOYED_VIEWS.has(view)) { location.replace("#jobs"); return renderV32(); }
  document.body.classList.toggle("unemployed", !!(STATE && STATE.unemployed));
  return renderV32();
};

/* ================================================================ the Job Centre */
VIEWS.jobs = async () => {
  const d = await api("jobs");
  const pct = (x) => `<b class="${x >= 0.6 ? "r4" : x >= 0.35 ? "r3" : "r1"}">${Math.round(x * 100)}%</b>`;
  const t = d.jobs.length ? table(d.jobs, [{key: "abbr", label: "Club", fmt: (r) => `${crest(r.abbr, 18)} <a href="#team/${r.team_id}">${esc(r.name)}</a>`},
    {key: "projected", label: "Projected", num: true, fmt: (r) => ordinal(r.projected)}, {key: "owner", label: "Owner", fmt: (r) => r.owner ? `${esc(r.owner.name)} <span class="muted small">${esc(r.owner.archetype || "")}</span>` : "-"},
    {key: "demand", label: "Reputation wanted", num: true}, {key: "chance", label: "Your chance", num: true, fmt: (r) => pct(r.chance)},
    {key: "x", label: "", fmt: (r) => d.unemployed ? (r.last_applied && STATE && r.last_applied.slice(0, 7) === STATE.date.slice(0, 7)
      ? '<span class="muted">interviewed this month</span>' : `<button class="mini primary" data-cmd="apply ${esc(r.abbr)}" data-confirm="Apply to be the GM of the ${esc(r.name)}? They interview you and decide at once.">Apply</button>`) : ""}])
    : empty("Nobody is looking for a general manager right now. Jobs open when owners fire their GMs, most often at the end of a season.");
  const intro = d.unemployed
    ? `<div class="jc-intro"><b>You are out of work.</b> The league plays on (Continue in the bottom bar). Apply for any opening: a club hires a GM whose reputation fits what it expects, and each club interviews you once a month.</div>`
    : `<div class="jc-intro muted">You run a club. This is the job market as it stands; you can apply once you are out of work.</div>`;
  return intro + `<div class="grid two">${panel(`Clubs looking for a GM (${d.jobs.length})`, t)}${panel("Your standing", `<div class="jc-rep"><b>${Math.round(d.reputation)}</b><span>${esc(d.label)}</span></div>
    ${bar(d.reputation)}<p class="muted small">Reputation grows with playoff runs and championships and falls with firings. Better clubs want a bigger name.</p><p><a class="btn" href="#gm">Manager profile</a></p>`)}</div>`;
};

/* ================================================================ the manager profile: ratings, reputation, role */
const gmV32 = VIEWS.gm;
VIEWS.gm = async () => {
  const [html, m] = await Promise.all([gmV32(), api("manager")]);
  const s = m.settings;
  const rows = m.ratings.map((r) => {
    const off = (r.key === "coaching" || r.key === "development") && !m.is_coach;
    return `<tr class="${off ? "dim" : ""}"><th>${esc(r.label)}</th><td class="num"><b class="${ratingClass(r.value)}">${r.value}</b></td><td><span class="rbar"><i style="width:${r.value * 5}%"></i></span></td>
      <td class="small muted">${esc(r.what)}</td><td>${s.points > 0 && r.value < 20 ? `<button class="mini" data-cmd="improve ${r.key}">+1</button>` : ""}</td></tr>`;
  }).join("");
  const log = (s.rep_log || []).slice(-8).reverse().map(([d, x, w]) => `<li><span class="muted">${esc(d)}</span> ${x > 0 ? "+" : ""}${x} ${esc(w)}</li>`).join("");
  const role = m.unemployed ? `<p class="muted">You will take the role you chose (${esc(m.role_label)}) with your next club.</p>`
    : m.is_coach ? `<p>You are the <b>general manager and head coach</b>: your coaching, development and motivation are the coach's ratings the engine and the room use.</p>
      <button data-cmd="gmrole gm" data-confirm="Hand over the bench? You will need to hire a head coach (Staff).">Hand over the bench</button>`
    : `<p>You are the <b>general manager</b>; a head coach runs the bench.</p><button data-cmd="gmrole coach" data-confirm="Coach the team yourself? Your head coach goes to the staff market.">Coach the team yourself</button>`;
  const extra = `<div class="grid two">${panel(`Manager ratings${s.points ? ` · ${s.points} point${s.points > 1 ? "s" : ""} to spend` : ""}`,
      `<table class="kvt mr">${rows}</table><p class="muted small">You earn a point for each season you complete. Coaching and youth development count only while you also coach.</p>`)}
    <div>${panel("Reputation", `<div class="jc-rep"><b>${Math.round(s.reputation)}</b><span>${esc(m.reputation_label)}</span></div>${bar(s.reputation)}
      ${log ? `<ul class="plain small">${log}</ul>` : '<p class="muted small">It moves at the end of each season and when you are fired.</p>'}`)}
    ${panel("Role", role + (s.unfireable ? '<p class="tag">This career: you cannot be fired</p>' : ""))}</div></div>`;
  return html.replace(/(<\/div><\/div>)/, `$1`) + extra;
};

/* ================================================================ the assistant GM */
VIEWS.assistant = async () => {
  const d = await api("assistant");
  const lvl = {1: ["Now", "neg"], 2: ["Soon", "warn"], 3: ["Worth a look", ""]};
  const items = d.items.length ? d.items.map((x, i) => `<div class="as-item l${x.level}"><span class="tag ${lvl[x.level][1]}">${lvl[x.level][0]}</span><b>${esc(x.area)}</b>
      <span class="as-text">${esc(x.text)}</span><span class="spacer"></span>${x.actions.map((a, j) => a.href ? `<a class="btn mini" href="${a.href}">${esc(a.label)}</a>`
        : `<button class="mini${j === 0 ? " primary" : ""}" data-as="${i}:${j}">${esc(a.label)}</button>`).join(" ")}</div>`).join("")
    : empty("Nothing needs your attention. The assistant will speak up when something does.");
  AFTER = () => {
    const run = async (a) => {
      if (a.confirm && !(await ask(a.confirm))) return false;
      const r = await post("/api/command", {line: a.cmd});
      if (!r.ok) { toast(r.output, true); return false; }
      if (a.then) { const r2 = await post("/api/command", {line: a.then}); if (!r2.ok) { toast(r2.output, true); return false; } }
      return true;
    };
    document.querySelectorAll("[data-as]").forEach((b) => (b.onclick = async () => {
      const [i, j] = b.dataset.as.split(":").map(Number);
      if (await run(d.items[i].actions[j])) { toast("Done."); refresh(); }
    }));
    const all = $("#as-all");
    if (all) all.onclick = async () => {
      let n = 0;
      for (const x of d.items.filter((y) => y.routine)) { const a = x.actions.find((y) => y.cmd); if (a && await run({...a, confirm: null})) n++; }
      toast(`The assistant did ${n} routine job${n === 1 ? "" : "s"}.`); refresh();
    };
  };
  return `<div class="toolbar"><b>Assistant GM</b><span class="muted">reads your organisation each time you open this screen; it never acts on its own</span><span class="spacer"></span>
    ${d.routine ? `<button class="primary" id="as-all">Do the routine ones (${d.routine})</button>` : ""}</div>` + panel(`Suggestions (${d.items.length})`, items)
    + '<p class="muted small">Routine: recalls to fill a short position, sending down extras on an oversized roster, resetting lines that name players who are gone.</p>';
};

/* ================================================================ find players */
const FIND = {q: "", pos: "", age_min: "", age_max: "", league: "", status: "", nat: "", value_min: "", cap_max: ""};
VIEWS.find = async () => {
  const d = await api("find", FIND);
  const sel = (k, opts) => `<select data-f="${k}">${opts.map(([v, l]) => `<option value="${esc(v)}"${String(FIND[k]) === String(v) ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
  const inp = (k, ph, size = 4) => `<input data-f="${k}" value="${esc(FIND[k])}" placeholder="${esc(ph)}" size="${size}">`;
  const form = `<div class="toolbar find">${inp("q", "Name", 14)}
    <label>Pos ${sel("pos", [["", "Any"], ["F", "Forward"], ["C", "C"], ["LW", "LW"], ["RW", "RW"], ["D", "D"], ["G", "G"]])}</label>
    <label>Age ${inp("age_min", "min", 2)}-${inp("age_max", "max", 2)}</label>
    <label>League ${sel("league", [["", "Any"], ...d.leagues.map((l) => [l, l])])}</label>
    <label>Status ${sel("status", [["", "Any"], ["fa", "Free agent"], ["expiring", "Contract ending"], ["block", "On the block"], ["rights", "Unsigned rights"], ["mine", "Your organisation"]])}</label>
    <label>Nat ${sel("nat", [["", "Any"], ...d.nats.map((n) => [n, n])])}</label>
    <label>Value from ${inp("value_min", "0", 2)}</label><label>Cap hit to ${inp("cap_max", "$M", 3)}M</label>
    <button class="primary" id="fd-go">Find</button> <button id="fd-clear">Clear</button></div>`;
  AFTER = () => {
    const read = () => document.querySelectorAll("[data-f]").forEach((x) => { FIND[x.dataset.f] = x.value.trim(); });
    $("#fd-go").onclick = () => { read(); render(); };
    $("#fd-clear").onclick = () => { Object.keys(FIND).forEach((k) => (FIND[k] = "")); render(); };
    document.querySelectorAll("[data-f]").forEach((x) => x.addEventListener("keydown", (e) => { if (e.key === "Enter") { read(); render(); } }));
    document.querySelectorAll("select[data-f]").forEach((x) => (x.onchange = () => { read(); render(); }));
  };
  const t = table(d.rows, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "pos", label: "Pos"}, {key: "age", label: "Age", num: true},
    {key: "nat", label: "Nat"}, {key: "team", label: "Club", fmt: (r) => r.team && !r.club ? tm(r.team, r.team_id) : esc(r.club || (r.team_id ? r.team : "free agent"))},
    {key: "value", label: "Value", num: true}, {key: "potential", label: "Potential", fmt: (r) => potentialStars(r.potential)},
    {key: "cap_hit", label: "Cap hit", num: true, fmt: (r) => mil(r.cap_hit)}, {key: "ends", label: "Final season", fmt: (r) => ssn(r.ends)}],
    {rowClass: (r) => STATE && r.team_id === STATE.team_id ? "mine" : ""});
  return form + panel(`Players (${d.rows.length}${d.total > d.rows.length ? ` of ${d.total >= 6000 ? "6000+" : d.total}, best first` : ""})`,
    d.rows.length ? `<div class="scroll tall">${t}</div>` : empty("Nobody matches. Loosen a filter."), "right-click a name for the short list");
};

/* ================================================================ new game setup: the manager step and starting unemployed */
Title.show = (function (prev) {
  return async function (page = "home") {
    if (page !== "new") return prev(page);
    const S0 = this.setup || {};
    const d = await (await fetch("/api/saves" + (S0.world ? "?world=" + encodeURIComponent(S0.world) : ""))).json();
    const M = d.manager;
    const el = $("#title");
    el.hidden = false; el.className = "titlescreen setup";
    const S = this.setup = this.setup || {step: 1, name: "", nat: "CAN", bg: "former_player", age: 45, league: null, team: null, save: "", seed: Math.floor(Math.random() * 9000) + 1000,
      template: "balanced", ratings: {...M.templates.balanced.ratings}, reputation: "respected", role: "gm", unfireable: false, unemployed: false, world: ""};
    const steps = ["Your GM", "Manager", "World", "Club", "Start"];
    const head = `<div class="ts-brand"><i class="live-dot"></i>HOCKEY <em>MANAGER</em></div>`;
    const barS = `<div class="ts-steps">${steps.map((x, i) => `<span class="${i + 1 === S.step ? "on" : i + 1 < S.step ? "done" : ""}">${i + 1}. ${x}</span>`).join("")}</div>`;
    const used = Object.values(S.ratings).reduce((a, b) => a + b, 0);
    let body = "";
    if (S.step === 1) {
      body = `<h2>Create your GM</h2><div class="ts-form2"><label>Name <input id="su-name" value="${esc(S.name)}" placeholder="Your name"></label>
        <label>Nationality <select id="su-nat">${["CAN", "USA", "SWE", "FIN", "CZE", "SVK", "RUS", "GER", "SUI", "AUS", "GBR", "OTH"].map((n) => `<option${n === S.nat ? " selected" : ""}>${n}</option>`).join("")}</select></label>
        <label>Age <input id="su-age" size="3" value="${S.age}"></label></div>
        <h4>Background</h4><div class="ts-bgs">${Object.entries(d.backgrounds).map(([k, b]) => `<button class="ts-bg${k === S.bg ? " on" : ""}" data-bg="${k}"><b>${esc(b.label)}</b><span>${esc(b.text)}</span></button>`).join("")}</div>`;
    } else if (S.step === 2) {
      body = `<h2>Your strengths</h2><p class="muted">Pick a template, then move points around: ${M.pool} to spend, each rating ${M.r_min} to ${M.r_max}. You earn a point every season.</p>
        <div class="ts-tpl">${Object.entries(M.templates).map(([k, t]) => `<button class="ts-bg${k === S.template ? " on" : ""}" data-tpl="${k}"><b>${esc(t.label)}</b></button>`).join("")}</div>
        <table class="kvt mr">${M.ratings.map((r) => `<tr><th>${esc(r.label)}</th><td><button class="mini" data-r="${r.key}" data-d="-1">-</button> <b class="${ratingClass(S.ratings[r.key])}">${S.ratings[r.key]}</b> <button class="mini" data-r="${r.key}" data-d="1">+</button></td>
          <td class="small muted">${esc(r.what)}</td></tr>`).join("")}</table><p><b>${M.pool - used}</b> points left</p>
        <div class="ts-form2"><label>Reputation <select id="su-rep">${Object.entries(M.reputations).map(([k, r]) => `<option value="${k}"${k === S.reputation ? " selected" : ""}>${esc(r.label)} (${r.value})</option>`).join("")}</select></label>
          <label>Role <select id="su-role">${Object.entries(M.roles).map(([k, l]) => `<option value="${k}"${k === S.role ? " selected" : ""}>${esc(l)}</option>`).join("")}</select></label>
          <label class="chk"><input type="checkbox" id="su-unf"${S.unfireable ? " checked" : ""}> I cannot be fired</label></div>
        <p class="muted small">A bigger name opens better jobs and starts the owner warmer. As GM and head coach you are also the coach the engine and the room see.</p>`;
    } else if (S.step === 3) {
      const worlds = (d.worlds || []).map((w) => `<button class="ts-lg${(w.key || "") === (S.world || "") ? " on" : ""}" data-world="${esc(w.key)}"><b>${esc(w.name)}</b>
        <span>${w.players.toLocaleString()} players${w.season ? " · " + w.season + "-" + String((+w.season + 1) % 100).padStart(2, "0") : ""}</span><i>${w.personal ? "personal use only" : esc(w.source)}</i></button>`).join("");
      body = `<h2>Choose your world</h2><div class="ts-leagues">${worlds}<button class="ts-lg" id="su-import"><b>Import a database...</b><span>From your own export folder</span><i>players, clubs, contracts, staff</i></button></div>
        <h2>Choose your league</h2><div class="ts-leagues">${d.leagues.map((l) => `<button class="ts-lg${l.playable ? "" : " off"}${S.league === l.league_id ? " on" : ""}" data-lg="${l.league_id}"${l.playable ? "" : " disabled"}>
        <b>${esc(l.abbr)}</b><span>${esc(l.name)}</span><i>${l.clubs} clubs${l.playable ? "" : " · coming later"}</i></button>`).join("")}</div>
        <p class="muted">For now you can run an NHL club. The other leagues play on around you.</p>`;
    } else if (S.step === 4) {
      const byDiv = {};
      d.teams.forEach((t) => (byDiv[`${t.conference} · ${t.division}`] = byDiv[`${t.conference} · ${t.division}`] || []).push(t));
      const t = d.teams.find((x) => x.abbr === S.team);
      body = `<h2>Choose your club</h2><label class="chk ts-unemp"><input type="checkbox" id="su-unemp"${S.unemployed ? " checked" : ""}> Start unemployed: no club, a few openings, the job market</label>
        ${S.unemployed ? '<p class="muted">You start without a club. A handful of clubs (most of them weaker ones) are looking for a GM; apply from the Job Centre. The league plays on while you look.</p>'
        : `<div class="ts-club"><div class="ts-divs">${Object.entries(byDiv).map(([k, ts]) => `<div class="ts-div"><h4>${esc(k)}</h4>${ts.map((x) => `<button class="ts-team${x.abbr === S.team ? " on" : ""}" data-team="${esc(x.abbr)}"><b>${esc(x.abbr)}</b> ${esc(x.name)}</button>`).join("")}</div>`).join("")}</div>
        <div class="ts-detail">${t ? `<div class="dr-big">${esc(t.name)}</div><p class="muted">${esc(t.conference)} · ${esc(t.division)}</p><p>Outlook: <b>${esc(t.outlook)}</b> (roster strength ${t.strength})</p>
          <h4>Stars</h4><ul>${t.stars.map((s) => `<li>${esc(s.name)} <span class="muted">${esc(s.pos)}</span></li>`).join("")}</ul>` : '<p class="muted">Pick a club to see its outlook.</p>'}</div></div>`}`;
    } else {
      const t = d.teams.find((x) => x.abbr === S.team);
      S.save = S.save || (S.unemployed ? `${S.name || "GM"} career` : `${S.team} career`);
      body = `<h2>Ready</h2><p><b>${esc(S.name || "The GM")}</b> (${esc(d.backgrounds[S.bg].label)}, ${esc(M.templates[S.template] ? M.templates[S.template].label : "custom")}, ${esc(M.reputations[S.reputation].label.toLowerCase())}),
        ${S.unemployed ? "<b>out of work</b>, looking for a club" : `${esc(M.roles[S.role].toLowerCase())} of the <b>${esc(t ? t.name : S.team)}</b>`}${S.unfireable ? "; cannot be fired" : ""}.</p>
        <div class="ts-form2"><label>Save name <input id="su-save" value="${esc(S.save)}"></label><label>World seed <input id="su-seed" size="6" value="${S.seed}"></label></div>
        ${S.unemployed ? "" : `<div class="ts-form2 ts-chal"><label class="chk"><input type="checkbox" id="su-chm"${S.chm ? " checked" : ""}> Challenge mode (no editor, in-season sims of a week at most, you can be fired; for good)</label>
        <label>Challenge <select id="su-chal">${[["", "none"], ["turnaround", "Turnaround: the playoffs within two seasons"], ["rebuild", "Rebuild: a playoff round within four seasons"],
          ["win_now", "Win now: the championship within three seasons"], ["cap_hell", "Cap hell: cap-compliant on opening night, the playoffs within two"],
          ["dynasty", "Dynasty: three championships in eight seasons"], ["expansion", "Expansion: take over a new club and make the playoffs"]].map(([k, l]) =>
          `<option value="${k}"${(S.chal || "") === k ? " selected" : ""}>${l}</option>`).join("")}</select></label></div>`}`;
    }
    el.innerHTML = `<div class="ts-wrap">${head}<div class="ts-panel">${barS}${body}<div class="row ts-nav"><button id="su-back">${S.step === 1 ? "Main menu" : "Back"}</button><span class="spacer"></span>
      <button class="primary big-btn" id="su-next">${S.step === 5 ? "Start career" : "Next"}</button></div></div></div>`;
    const keep = () => {
      if ($("#su-name")) { S.name = $("#su-name").value; S.nat = $("#su-nat").value; S.age = +$("#su-age").value || 45; }
      if ($("#su-rep")) { S.reputation = $("#su-rep").value; S.role = $("#su-role").value; S.unfireable = $("#su-unf").checked; }
      if ($("#su-unemp")) S.unemployed = $("#su-unemp").checked;
      if ($("#su-save")) { S.save = $("#su-save").value; S.seed = +$("#su-seed").value || 1; }
      if ($("#su-chm")) { S.chm = $("#su-chm").checked; S.chal = $("#su-chal").value; }
    };
    const again = () => this.show("new");
    el.querySelectorAll("[data-bg]").forEach((b) => (b.onclick = () => { keep(); S.bg = b.dataset.bg; again(); }));
    el.querySelectorAll("[data-tpl]").forEach((b) => (b.onclick = () => { keep(); S.template = b.dataset.tpl; S.ratings = {...M.templates[S.template].ratings}; again(); }));
    el.querySelectorAll("[data-r]").forEach((b) => (b.onclick = () => {
      keep(); const k = b.dataset.r, dlt = +b.dataset.d, v = S.ratings[k] + dlt;
      if (v < M.r_min || v > M.r_max || (dlt > 0 && used >= M.pool)) return;
      S.ratings[k] = v; S.template = "custom"; again();
    }));
    el.querySelectorAll("[data-lg]").forEach((b) => (b.onclick = () => { S.league = +b.dataset.lg; again(); }));
    el.querySelectorAll("[data-world]").forEach((b) => (b.onclick = () => { S.world = b.dataset.world; S.team = null; S.league = null; again(); }));
    const imp = $("#su-import"); if (imp) imp.onclick = () => ImportDB.open((key) => { S.world = key; S.team = null; S.league = null; again(); });
    el.querySelectorAll("[data-team]").forEach((b) => (b.onclick = () => { S.team = b.dataset.team; again(); }));
    const ue = $("#su-unemp"); if (ue) ue.onchange = () => { keep(); again(); };
    $("#su-back").onclick = () => { keep(); if (S.step === 1) { this.setup = null; Title.show("home"); } else { S.step--; again(); } };
    $("#su-next").onclick = async () => {
      keep();
      if (S.step === 1 && !S.name.trim()) return toast("Give your GM a name.", true);
      if (S.step === 3 && !S.league) { const nhl = d.leagues.find((l) => l.playable); S.league = nhl ? nhl.league_id : null; }
      if (S.step === 4 && !S.team && !S.unemployed) return toast("Pick a club, or start unemployed.", true);
      if (S.step < 5) { S.step++; return again(); }
      $("#su-next").disabled = true; $("#su-next").textContent = "Building the league...";
      const team = S.team || (d.teams[0] && d.teams[0].abbr);
      try {
        await post("/api/save", {action: "new", team, name: S.save, seed: S.seed, world: S.world || "", profile: {name: S.name, nationality: S.nat, background: S.bg, age: S.age,
          ratings: S.ratings, template: S.template === "custom" ? null : S.template, reputation: S.reputation, role: S.role, unfireable: S.unfireable && !S.chm, unemployed: S.unemployed,
          challenge_mode: !!S.chm && !S.unemployed, challenge: S.unemployed ? null : (S.chal || null)}});
        this.setup = null; el.hidden = true; location.hash = S.unemployed ? "#jobs" : "#dashboard"; await refresh();
      } catch (err) { toast(err.message, true); $("#su-next").disabled = false; $("#su-next").textContent = "Start career"; }
    };
  };
})(Title.show.bind(Title));

/* ================================================================ header, menus, names */
const updateHeaderV32 = updateHeader;
updateHeader = function () {
  updateHeaderV32();
  if (STATE && STATE.unemployed) { $("#sh-crest").innerHTML = ""; $("#tb-team").textContent = "Out of work"; $("#sh-record").textContent = `reputation ${Math.round(STATE.reputation)}`; }
};
(() => {
  const find = (name) => MENUS.find((m) => m[0] === name)[1];
  const at = (list, label) => list.findIndex((it) => it !== "-" && it[0] === label);
  const mgr = find("Manager");
  mgr.splice(at(mgr, "Inbox") + 1, 0, ["Assistant GM", "#assistant"]);
  mgr.splice(at(mgr, "Manager Profile") + 1, 0, ["Job Centre", "#jobs"]);
  mgr.splice(at(mgr, "Search..."), 0, ["Find Players...", "#find"]);
  Object.assign(SCREEN_NAMES, {jobs: "Job Centre", assistant: "Assistant GM", find: "Find Players"});
  Object.assign(TAB_OF, {jobs: "dashboard", assistant: "dashboard", find: "transactions"});
})();

/* ---- boot: moved to the last script (v33.js) ---- */
