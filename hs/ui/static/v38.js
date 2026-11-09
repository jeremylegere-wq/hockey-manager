"use strict";
// v38: the native ratings model and importing your own database. The player screen's ratings tab shows the 42
// ratings (technical, mental, physical; goalkeeping for goalies), ability and potential as stars, the position and
// role ratings, and on request the engine attributes derived from them. File > Import Database builds a world from
// your own export folder (docs/DB_IMPORT.md); new careers pick their world in setup.

const caStars = (v) => {
  if (v == null) return '<span class="muted" title="Only your own staff can judge his ceiling">?</span>';
  const full = Math.floor(v), half = v - full >= 0.5 ? 1 : 0;
  return `<span class="stars" title="${v.toFixed(1)} of 5">${"&#9733;".repeat(full)}${half ? '<span class="half">&#9733;</span>' : ""}${'<span class="off">&#9733;</span>'.repeat(Math.max(0, 5 - full - half))}</span>`;
};

const ImportDB = {
  open(done) {
    const body = Modal.open(`<div class="win-title">Import Database</div><div class="pad">
      <p>Build a world from <b>your own</b> plain-English export of a hockey-management database: the folder that holds
      <code>players_hockey_profiles_*.csv</code>, <code>staff_normalized.csv</code>, <code>clubs_lookup.csv</code> and
      <code>player_rights_normalized.csv</code> (it can be the exporter's top folder; it is searched).</p>
      <table class="kvt"><tr><th>Export folder</th><td><input id="im-path" size="60" placeholder="C:\\HockeyData\\Export or ~/hockeydata/export"></td></tr>
      <tr><th>Database file</th><td><input id="im-db" size="60" placeholder="optional: database.db (found in the folder if it is there)"></td></tr>
      <tr><th>World name</th><td><input id="im-name" size="30" value="My world 2026-27"></td></tr></table>
      <p class="muted small">With the database file, every player's career (season by season, every league) and the past NHL drafts come in too.</p>
      <p class="muted small">Personal use only: the world it builds stays on this computer (worlds/ next to your saves) and must not be shared.
      The game's own players and clubs are untouched; start a new career in the new world from File &gt; New Game.</p>
      <div class="win-buttons"><button class="primary" id="im-go">Import</button> <button onclick="Modal.close()">Cancel</button></div></div>`, "win wide");
    body.querySelector("#im-go").onclick = async () => {
      const path = body.querySelector("#im-path").value.trim(), name = body.querySelector("#im-name").value.trim();
      if (!path) return toast("Give the export folder.", true);
      const b = body.querySelector("#im-go"); b.disabled = true; b.textContent = "Importing...";
      try {
        const r = await post("/api/save", {action: "import_world", path, name, db_file: body.querySelector("#im-db").value.trim()});
        Modal.close(); toast(r.output);
        if (done) done(r.world);
      } catch (e) { toast(e.message, true); b.disabled = false; b.textContent = "Import"; }
    };
  },
};

const Rt = {engine: false};
const playerV38 = VIEWS.player;
VIEWS.player = async (id) => {
  const html = await playerV38(id);
  const prev = AFTER;
  AFTER = async () => {
    if (prev) await prev();
    const tab = location.hash.split("/")[2] || "overview";
    const p = await api("player", {id}).catch(() => null);
    if (!p) return;
    const hero = $(".pp-id");
    if (!p.ability) return;
    if (hero && !$(".pp-ability")) hero.insertAdjacentHTML("beforeend", `<div class="pp-ability"><span>Ability ${caStars(p.ability.current)}</span><span>Potential ${caStars(p.ability.potential)}</span></div>`);
    if (tab !== "ratings") return;
    const view = $("#view");
    const pos = p.ability.positions, roles = p.ability.roles;
    const posRow = Object.entries(pos).filter(([, v]) => v > 1).sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `<span class="posr"><b>${esc(k)}</b><span class="v ${ratingClass(v)}">${v}</span></span>`).join("");
    const strip = panel("Ability and positions", `<div class="pp-ratingstrip"><div><span class="muted">Current ability</span> ${caStars(p.ability.current)}</div>
      <div><span class="muted">Potential</span> ${caStars(p.ability.potential)}</div><div class="posrs">${posRow}</div>
      ${p.position !== "G" ? `<div><span class="muted">Offensive role</span> <b class="${ratingClass(roles.offensive)}">${roles.offensive}</b> <span class="muted">Defensive role</span> <b class="${ratingClass(roles.defensive)}">${roles.defensive}</b></div>` : ""}
      <label class="chk"><input type="checkbox" id="rt-engine"${Rt.engine ? " checked" : ""}> Show the engine attributes</label></div>`);
    const nav = view.querySelector(".pp-tabs");
    if (nav) nav.insertAdjacentHTML("afterend", strip); else view.insertAdjacentHTML("afterbegin", strip);
    if (Rt.engine && p.engine_attributes) {
      (view.querySelector(".pp-tabs + .panel") || view).insertAdjacentHTML("afterend", panel("Engine attributes (derived from the ratings)", `<div class="grid g2">${p.engine_attributes.map((g) => panel(g.title,
        `<div class="attr">${g.items.map((i) => `<span>${esc(i.label)}</span><span class="v ${ratingClass(i.value)}">${i.value}</span>`).join("")}</div>`)).join("")}</div>
        <p class="muted small">What the match engine reads. They are worked out from the ratings, so they cannot be edited directly.</p>`));
    }
    const cb = $("#rt-engine"); if (cb) cb.onchange = () => { Rt.engine = cb.checked; render(); };
  };
  return html;
};

(() => {
  const file = MENUS.find((m) => m[0] === "File")[1];
  const i = file.findIndex((it) => it !== "-" && it[0] === "Save Game As...");
  file.splice(i + 1, 0, "-", ["Import Database...", () => ImportDB.open(() => toast("Start a career in it from File > New Game."))]);
})();


/* ================================================================ v38 (#34, #35, #6): an Outlook-style inbox */
const OL = {q: ""};
const olBody = (text) => {                            // paragraphs, "- " lists, `commands` as inline buttons, CAPS: headings
  const cmdBtn = (c) => `<button class="mini ol-inl" data-cmd="${esc(c)}">${esc(c)}</button>`;
  const out = []; let list = [];
  const flush = () => { if (list.length) { out.push(`<ul>${list.map((x) => `<li>${x}</li>`).join("")}</ul>`); list = []; } };
  for (const raw of String(text || "").split(/\n/)) {
    const t = raw.trim();
    if (!t) { flush(); continue; }
    let l = esc(t).replace(/`([^`]{1,40})`/g, (m, c) => cmdBtn(c));
    l = l.replace(/^([A-Z][A-Z ,'&-]{3,}):/, '<b class="ol-cap">$1</b>');
    if (/^- /.test(t)) list.push(l.slice(2)); else { flush(); out.push(`<p>${l}</p>`); }
  }
  flush();
  return out.join("");
};
const olGroup = (date, today) => {
  const d = (new Date(today + "T12:00:00") - new Date(date + "T12:00:00")) / 864e5;
  return d <= 0 ? "Today" : d < 2 ? "Yesterday" : d < 7 ? "Earlier this week" : d < 14 ? "Last week" : d < 31 ? "Earlier this month" : "Older";
};
const initials = (s) => String(s || "?").split(",")[0].split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
VIEWS.inbox = async (arg = "") => {
  const [folder = "all", sel = ""] = arg.split(":");
  const d = await api("inbox2", {folder, q: OL.q});
  const today = (STATE && STATE.date) || (d.messages[0] && d.messages[0].date) || "";
  const cur = d.messages.find((m) => String(m.msg_id) === sel) || null;
  if (cur && !cur.read) { quietCmd(`read ${cur.msg_id}`).then(() => api("state").then((st) => { const b = $("#tb-inbox"); if (b) b.textContent = `Inbox${st.unread ? " (" + st.unread + ")" : ""}`; })); cur.read = true; }
  const icon = {all: "&#128229;", unread: "&#9993;", flagged: "&#9873;", board: "&#127970;", players: "&#128101;", trades: "&#8644;", staff: "&#128203;", league: "&#127954;", archived: "&#128451;"};
  const fav = ["all", "unread", "flagged"];
  const fl = (f) => `<a class="olf${f.key === folder ? " on" : ""}" href="#inbox/${f.key}"><span class="i">${icon[f.key] || ""}</span><span class="n">${esc(f.label)}</span>${
    f.key === "unread" || f.key === "all" ? (f.key === "all" ? (d.unread ? `<b>${d.unread}</b>` : "") : (f.count ? `<b>${f.count}</b>` : "")) : (f.count ? `<i>${f.count}</i>` : "")}</a>`;
  const nav = `<div class="olh">Favourites</div>${d.folders.filter((f) => fav.includes(f.key)).map(fl).join("")}<div class="olh">Folders</div>${d.folders.filter((f) => !fav.includes(f.key)).map(fl).join("")}`;
  let lastG = null;
  const rows = d.messages.map((m) => {
    const g = olGroup(m.date, today);
    const head = g !== lastG ? `<div class="olg">${g}</div>` : "";
    lastG = g;
    return head + `<a class="olm${m.read ? "" : " unread"}${cur && cur.msg_id === m.msg_id ? " on" : ""}" href="#inbox/${folder}:${m.msg_id}" style="--c:${m.colour}">
      <span class="av">${esc(initials(m.sender))}</span><span class="mb"><span class="mh"><b>${esc(m.sender)}</b><span class="date">${esc(dshort(m.date))}</span></span>
      <span class="ms">${esc(m.subject)}</span><span class="mp">${esc(m.snippet)}</span></span>
      <span class="olq"><button class="olflag${m.flagged ? " on" : ""}" data-flag="${m.msg_id}" title="${m.flagged ? "Unflag" : "Flag"}">&#9873;</button>${m.actions.length ? '<span class="olact" title="Needs you">&#9888;</span>' : ""}</span></a>`;
  }).join("") || '<p class="muted pad">Nothing here.</p>';
  const ribbon = `<div class="olr"><button data-ol="read"${cur ? "" : " disabled"}>&#9993; ${cur && cur.read ? "Mark unread" : "Mark read"}</button>
    <button data-ol="flag"${cur ? "" : " disabled"}>&#9873; ${cur && cur.flagged ? "Unflag" : "Flag"}</button>
    <button data-ol="archive"${cur ? "" : " disabled"}>&#128451; ${cur && cur.archived ? "Move to inbox" : "Archive"}</button>
    <span class="sep"></span><button data-cmd="inbox">&#10003; Mark all read</button><span class="spacer"></span>
    <input id="ol-q" type="search" placeholder="Search mail" value="${esc(OL.q)}"></div>`;
  let read = '<div class="mr-empty"><div>&#9993;</div><p>Select a message to read it.</p></div>';
  if (cur) {
    const acts = cur.actions.map((a) => a.href ? `<a class="btn${a.primary ? " primary" : ""}" href="${esc(a.href)}">${esc(a.label)}</a>`
      : `<button class="btn${a.primary ? " primary" : ""}" data-cmd="${esc(a.cmd)}"${a.confirm ? ` data-confirm="${esc(a.confirm)}"` : ""}>${esc(a.label)}</button>`).join(" ");
    read = `<div class="olread"><h2 class="ols">${esc(cur.subject)}</h2>
      <div class="olfrom"><span class="av" style="--c:${cur.colour}">${esc(initials(cur.sender))}</span><div><b>${esc(cur.sender)}</b>
        <div class="muted small">To: You (General Manager)${STATE && STATE.team ? ", " + esc(STATE.team) : ""}</div></div><span class="spacer"></span><span class="muted small">${dlong(cur.date)}</span></div>
      ${acts ? `<div class="olacts">${acts}</div>` : ""}
      <div class="olbody">${olBody(cur.body)}</div></div>`;
  }
  AFTER = () => {
    const q = $("#ol-q"); if (q) q.onkeydown = (e) => { if (e.key === "Enter") { OL.q = q.value; render(); } };
    document.querySelectorAll("[data-flag]").forEach((b) => (b.onclick = async (e) => {
      e.preventDefault(); e.stopPropagation();
      await quietCmd(`mail ${b.classList.contains("on") ? "unflag" : "flag"} ${b.dataset.flag}`); render();
    }));
    document.querySelectorAll("[data-ol]").forEach((b) => (b.onclick = async () => {
      if (!cur) return;
      const k = b.dataset.ol;
      if (k === "read") await quietCmd(`read ${cur.msg_id}${cur.read ? " unread" : ""}`);
      if (k === "flag") await quietCmd(`mail ${cur.flagged ? "unflag" : "flag"} ${cur.msg_id}`);
      if (k === "archive") { await quietCmd(`mail ${cur.archived ? "restore" : "archive"} ${cur.msg_id}`); location.hash = `#inbox/${folder}`; return; }
      render();
    }));
  };
  return `<div class="ol">${ribbon}<div class="olgrid"><aside class="olnav">${nav}</aside><section class="ollist">${rows}</section><section class="olpane">${read}</section></div></div>`;
};


/* ================================================================ v38 (#8): About is not Credits */
const creditsV38 = Credits.open.bind(Credits);
Credits.open = async function (about = false) {
  if (!about) return creditsV38(false);
  const app = await (await fetch("/api/app")).json().catch(() => ({}));
  const sv = await (await fetch("/api/saves")).json().catch(() => ({}));
  const w = (sv.worlds || []).map((x) => `<li><b>${esc(x.name)}</b> · ${x.players.toLocaleString()} players · ${x.season ? x.season + "-" + String((+x.season + 1) % 100).padStart(2, "0") : ""}${x.personal ? " · personal use only" : ""}</li>`).join("");
  Modal.open(`<div class="win-title">About Hockey Manager</div><div class="pad about">
    <div class="cr-logo">HOCKEY <span>MANAGER</span><i>version ${esc(app.version || "")}</i></div>
    <p>A hockey management simulation: you run an NHL club's hockey operations (roster, contracts, the cap, trades, the draft,
    scouting, tactics, staff, the room, the money and the press) while a whole hockey world plays on around you, game by game.</p>
    <table class="kvt"><tr><th>Version</th><td>${esc(app.version || "-")}</td></tr>
      <tr><th>Window</th><td>${app.desktop ? "desktop window" : "browser"}</td></tr>
      <tr><th>Career</th><td>${STATE && STATE.loaded ? `${esc(STATE.team || "")} · ${esc(String(STATE.season || ""))} · ${esc(STATE.date || "")}` : "none loaded"}</td></tr>
      <tr><th>Saves folder</th><td><code>${esc(sv.folder || "-")}</code></td></tr></table>
    <h4>Worlds you can start a career in</h4><ul>${w || "<li>none</li>"}</ul>
    <h4>Keys</h4><p class="small">Space: continue one day · Ctrl+U: play until · Ctrl+F: find a player or club · Alt+F4: exit</p>
    <p class="muted small">Docs are in the docs folder next to the game (README.md first). For who made what, see Help &gt; Credits.</p>
    </div><div class="win-buttons"><button class="primary" onclick="Modal.close()">Close</button></div>`, "win");
};


/* ================================================================ v38 (#10, #21): the cap, year by year */
const CG = {mode: "grid"};
const contractsV38 = VIEWS.contracts;
VIEWS.contracts = async () => {
  const html = await contractsV38();
  const d = await api("contracts");
  if (!d.grid) return html;
  const S = d.grid_seasons, cap = d.ceiling || 0;
  const up = d.grid.filter((g) => g.status !== "prospect");     // the cap counts the NHL roster (and retained and buyouts)
  const tot = S.map((_, i) => up.reduce((a, g) => a + (g.cells[i] || 0), 0) + Math.max(0, d.dead_by_season[i] || 0));
  const tabs = `<div class="tabs"><button class="btn${CG.mode === "grid" ? " active" : ""}" data-cg="grid">Cap hits by season</button>
    <button class="btn${CG.mode === "chart" ? " active" : ""}" data-cg="chart">Cap commitments chart</button>
    <button class="btn${CG.mode === "cash" ? " active" : ""}" data-cg="cash">Salary by season</button></div>`;
  let body;
  if (CG.mode === "chart") {
    const W = 760, H = 260, pad = 46, bw = 80, gap = (W - pad - 20 - S.length * bw) / Math.max(1, S.length - 1);
    const max = Math.max(cap * 1.08, ...tot) || 1;
    const y = (v) => H - 24 - (v / max) * (H - 44);
    const grp = {F: "#2f6fb5", D: "#3f9b5c", G: "#c07a12", X: "#9a9a9a"};
    const bars = S.map((s, i) => {
      const x = pad + i * (bw + gap);
      let acc = 0;
      const parts = [["F", (g) => !["D", "G"].includes(g.pos)], ["D", (g) => g.pos === "D"], ["G", (g) => g.pos === "G"]].map(([k, f]) => {
        const v = up.filter(f).reduce((a, g) => a + (g.cells[i] || 0), 0);
        const r = `<rect x="${x}" y="${y(acc + v)}" width="${bw}" height="${Math.max(0, y(acc) - y(acc + v))}" fill="${grp[k]}"><title>${k}: ${mil(v)}</title></rect>`;
        acc += v; return r;
      }).join("");
      const dead = Math.max(0, d.dead_by_season[i] || 0);
      const dr = dead ? `<rect x="${x}" y="${y(acc + dead)}" width="${bw}" height="${y(acc) - y(acc + dead)}" fill="${grp.X}"><title>Retained and buyouts: ${mil(dead)}</title></rect>` : "";
      return parts + dr + `<text x="${x + bw / 2}" y="${H - 8}" text-anchor="middle" font-size="12">${ssn(s)}</text><text x="${x + bw / 2}" y="${y(tot[i]) - 4}" text-anchor="middle" font-size="11">${mil(tot[i])}</text>`;
    }).join("");
    const capLine = cap ? `<line x1="${pad - 6}" x2="${W - 10}" y1="${y(cap)}" y2="${y(cap)}" stroke="#b3261e" stroke-dasharray="5 4"/><text x="${W - 12}" y="${y(cap) - 4}" text-anchor="end" font-size="11" fill="#b3261e">cap ${mil(cap)} (today's)</text>` : "";
    body = `<svg viewBox="0 0 ${W} ${H}" class="capchart">${bars}${capLine}</svg>
      <p class="small"><span class="pk" style="background:${grp.F};color:#fff">forwards</span> <span class="pk" style="background:${grp.D};color:#fff">defence</span> <span class="pk" style="background:${grp.G};color:#fff">goalies</span> <span class="pk" style="background:${grp.X};color:#fff">retained and buyouts</span>
      · the NHL roster's committed contracts: the space under the line is what you have to fill each summer. Minor-league deals are in the grid but do not count.</p>`;
  } else {
    const head = `<tr><th>Player</th><th>Pos</th><th>Type</th>${S.map((s) => `<th class="num">${ssn(s)}</th>`).join("")}</tr>`;
    const cashMode = CG.mode === "cash" && d.cash_by_season;       // v41: the ledger's salary and bonus
    const row = (g) => `<tr><td>${clink(g.player_id, g.name)}${g.status === "prospect" ? ' <span class="tag">minors</span>' : ""}</td><td>${esc(g.pos)}</td><td>${esc(ctype(g.type))}</td>${g.cells.map((c0, i) => {
      const c = cashMode ? (g.cash || [])[i] : c0, b = cashMode ? (g.bonus || [])[i] : 0;
      return `<td class="num${c ? (S[i] === g.ends ? " last" : " on") : ""}"${b ? ` title="salary ${mil(c - b)} + signing bonus ${mil(b)} (paid 1 July)"` : ""}>${c ? mil(c) + (b ? ' <span class="tag">B</span>' : "") : (S[i] - 1 === g.ends ? '<span class="tag warn">expired</span>' : "")}</td>`; }).join("")}</tr>`;
    const foot = cashMode ? `<tr class="tot"><th colspan="3">Cash payroll (salaries and bonuses, retained, buyouts)</th>${d.cash_by_season.map((t) => `<th class="num">${mil(t)}</th>`).join("")}</tr>`
      : `<tr class="tot"><th colspan="3">Committed (NHL roster, retained and buyouts)</th>${tot.map((t) => `<th class="num">${mil(t)}</th>`).join("")}</tr>
      ${cap ? `<tr class="tot"><th colspan="3">Room under today's cap</th>${tot.map((t) => `<th class="num ${cap - t < 0 ? "r1" : "r4"}">${mil(cap - t)}</th>`).join("")}</tr>` : ""}`;
    body = `<div class="scroll"><table class="data capgrid"><thead>${head}</thead><tbody>${d.grid.map(row).join("")}</tbody><tfoot>${foot}</tfoot></table></div>`
      + (CG.mode === "cash" ? '<p class="muted small">What each contract pays each season (salary plus signing bonus, marked B, paid on 1 July). Long, big deals are front-loaded; the cap counts the average. The owner pays the cash.</p>' : "");
  }
  const prev = AFTER;
  AFTER = async () => { if (prev) await prev(); document.querySelectorAll("[data-cg]").forEach((b) => (b.onclick = () => { CG.mode = b.dataset.cg; render(); })); decorate($("#view")); };
  return html + panel("Contracts year by year", tabs + body);
};


/* ================================================================ v38 (#13): other clubs' prospects, and the league's best */
const PR = {view: ""};
const prospectsV38 = VIEWS.prospects;
VIEWS.prospects = async () => {
  const clubs = (await api("prospects", {scope: ""}).catch(() => ({clubs: []}))).clubs || [];
  const pick = `<div class="toolbar"><label>Show <select id="pr-view"><option value="">Your club</option><option value="league"${PR.view === "league" ? " selected" : ""}>The league's best prospects</option>
    ${clubs.filter((c) => !STATE || c.team_id !== STATE.team_id).map((c) => `<option value="${c.team_id}"${String(PR.view) === String(c.team_id) ? " selected" : ""}>${esc(c.abbr)}</option>`).join("")}</select></label>
    <span class="spacer"></span><a class="btn" href="#scouting/bureau">Central scouting</a> <a class="btn" href="#scouting/mock">Mock draft</a></div>`;
  const hook = () => { const prev = AFTER; AFTER = async () => { if (prev) await prev(); const s = $("#pr-view"); if (s) s.onchange = () => { PR.view = s.value; render(); }; decorate($("#view")); }; };
  if (!PR.view) { const html = await prospectsV38(); hook(); return pick + html; }
  const pot = (r) => r.potential == null ? `<span class="muted" title="Your scouts do not know him well enough (knowledge ${esc(r.known || "E")})">?</span>` : potentialStars(r.potential);
  if (PR.view === "league") {
    const d = await api("prospects", {scope: "league"});
    hook();
    return pick + panel(`The league's best prospects (${d.rows.length})`, `<div class="scroll tall">${table(d.rows, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)},
      {key: "pos", label: "Pos"}, {key: "age", label: "Age", num: true}, {key: "team", label: "Rights / club", fmt: (r) => tm(r.team, r.team_id)}, {key: "club", label: "Playing for"},
      {key: "value", label: "Ability", fmt: (r) => `${abilityStars(r.value)} <span class="muted small">${r.value}</span>`}, {key: "potential", label: "Potential", fmt: pot},
      {key: "known", label: "Known", fmt: (r) => `<span class="tag">${esc(r.known)}</span>`}])}</div>
      <p class="muted small">Potential is what your scouts can see: A and B knowledge shows it; C rounds it; D and E do not know. The Scouting screen sends scouts where you need them.</p>`);
  }
  const d = await api("prospects", {team: PR.view});
  hook();
  const cols = [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "pos", label: "Pos"}, {key: "age", label: "Age", num: true}, {key: "club", label: "Playing for"},
    {key: "value", label: "Ability", fmt: (r) => `${abilityStars(r.value)} <span class="muted small">${r.value}</span>`}];
  const ab = (clubs.find((c) => String(c.team_id) === String(PR.view)) || {}).abbr || "";
  return pick + `<div class="grid">${panel(`${esc(ab)}: unsigned draft rights (${d.rights.length})`, d.rights.length ? table(d.rights, [...cols, {key: "draft_year", label: "Drafted"}]) : empty("None."))}
    ${panel(`${esc(ab)}: signed, below the NHL (${d.signed.length})`, d.signed.length ? table(d.signed, cols) : empty("None."))}</div>`;
};


/* ================================================================ v38 (#24): the sim centre's side panel cycles */
(() => {
  const VIEWS_ = [["standings", null], ["points", "Points leaders"], ["goals", "Goal leaders"], ["goalies", "Save % leaders"]];
  const attachV38 = Sim.attach.bind(Sim), standV38 = Sim.stand.bind(Sim), closeV38 = Sim.close.bind(Sim);
  Sim.rot = 0;
  Sim.stand = function (st) { this.lastSt = st; if (VIEWS_[this.rot][0] === "standings") standV38(st); };
  Sim.showLeaders = async function () {
    const [k, title] = VIEWS_[this.rot];
    if (k === "standings") { if (this.lastSt) standV38(this.lastSt); return; }
    if (!this.lead || this.leadAt !== (this.last && this.last.day)) { this.lead = await api("simleaders").catch(() => null); this.leadAt = this.last && this.last.day; }
    const rows = (this.lead && this.lead[k]) || [];
    const t = $("#sc-st-title"), box = $("#sc-stand");
    if (!t || !box) return;
    t.textContent = title;
    box.innerHTML = rows.length ? `<table class="sc-st">${rows.map((r, i) => `<tr class="${STATE && r.team === STATE.abbr ? "mine" : ""}"><td>${i + 1}</td><td><b>${esc(r.name)}</b></td><td>${esc(r.team || "")}</td><td class="num pts">${esc(String(r.value))}</td></tr>`).join("")}</table>`
      : '<div class="sc-empty">Not enough games yet.</div>';
  };
  Sim.attach = function (mode) {
    attachV38(mode);
    clearInterval(this.rotTimer);
    this.rot = 0;
    this.rotTimer = setInterval(() => { if (!this.open) return clearInterval(this.rotTimer); this.rot = (this.rot + 1) % VIEWS_.length; this.showLeaders(); }, 6000);
  };
  Sim.close = function () { clearInterval(this.rotTimer); return closeV38(); };
})();

/* ---- boot: moved to the last script (v39.js) ---- */
