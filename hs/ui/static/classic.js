"use strict";
// v28: the classic desktop look. The menu bar, the screen header,
// club crests and player portraits (drawn here: no third-party marks), the cinematic launch screen, settings,
// credits, and the calendar, free agent centre, prospects and development screens. Loads last; boots the app.

/* ================================================================ settings */
let SETTINGS = {ui_scale: 100, units: "metric", confirm_phase: true, player_popups: true, sim_pace: 0.6, highlight_team: true, show_console: false, intro: true};
let APP = {desktop: false, version: ""};
async function loadSettings() {
  try { SETTINGS = Object.assign(SETTINGS, await (await fetch("/api/settings")).json()); } catch (e) { /* defaults */ }
  try { APP = await (await fetch("/api/app")).json(); } catch (e) { /* plain server */ }
  applySettings();
}
function applySettings() {
  document.documentElement.style.zoom = (SETTINGS.ui_scale || 100) / 100;
  document.body.classList.toggle("console-on", !!SETTINGS.show_console);
  document.body.classList.toggle("hl-team", !!SETTINGS.highlight_team);
}

/* ================================================================ crests and portraits */
const CREST_COLOURS = [["#b3122e", "#0d2b5c"], ["#0b4ea2", "#e8b70e"], ["#00543d", "#c8c9c7"], ["#f47a38", "#1a1a1a"], ["#6f263d", "#236192"],
  ["#002654", "#c8102e"], ["#111111", "#fcb514"], ["#041e42", "#a2aaad"], ["#ce1126", "#111111"], ["#006847", "#8f8f8c"], ["#00205b", "#ff4c00"],
  ["#5f259f", "#f2a900"], ["#c8102e", "#ffffff"], ["#003e7e", "#ffb81c"], ["#00468b", "#97999b"], ["#4b2a7b", "#c4ced4"], ["#a6192e", "#eaaa00"],
  ["#001e62", "#c8102e"], ["#006d75", "#e57200"], ["#2c5234", "#a4a9ad"], ["#99d9d9", "#001628"], ["#782f40", "#63666a"], ["#0038a8", "#ffffff"],
  ["#d2001c", "#ffd100"], ["#111111", "#a2aaad"], ["#002868", "#bf0d3e"], ["#e03a3e", "#00205b"], ["#5e1a33", "#d6d2c4"], ["#007a33", "#ffffff"],
  ["#1c3f94", "#d1d3d4"], ["#8a0f2c", "#111111"], ["#00843d", "#ffcd00"]];
function hashStr(s) { let h = 2166136261; for (const ch of String(s)) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }
function teamColours(abbr) { return CREST_COLOURS[hashStr(abbr || "?") % CREST_COLOURS.length]; }
function crest(abbr, size = 18) {
  if (!abbr) return "";
  const [a, b] = teamColours(abbr), t = String(abbr).slice(0, 3), fs = t.length > 2 ? 12 : 14;
  return `<svg class="crest" width="${size}" height="${Math.round(size * 1.12)}" viewBox="0 0 40 45" aria-hidden="true"><path d="M20 1.5 37.5 6v15.5C37.5 33 30 40 20 43.5 10 40 2.5 33 2.5 21.5V6Z" fill="${a}" stroke="${b}" stroke-width="2.6"/>
    <path d="M6 30h28" stroke="${b}" stroke-width="3" opacity=".85"/><text x="20" y="${t.length > 2 ? 24 : 25}" text-anchor="middle" font-family="Tahoma, Verdana, sans-serif" font-weight="700" font-size="${fs}" fill="#fff">${esc(t)}</text></svg>`;
}
function rng(seed) { let a = hashStr(seed); return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
function portrait(seed, abbr, pos, size = 84) {
  const r = rng("face-" + seed), pick = (xs) => xs[Math.floor(r() * xs.length)];
  const skin = pick(["#f3d3b8", "#eec4a2", "#e0ac86", "#c98e66", "#a86f4c", "#8a5638", "#f6dcc8", "#d9a27c"]);
  const hairC = pick(["#2b1d14", "#3b2a1d", "#5a3d26", "#8a6340", "#b38a58", "#d8b67a", "#1b1b1b", "#6b4a32", "#a0522d"]);
  const [ja, jb] = abbr ? teamColours(abbr) : ["#33475f", "#d9dee5"];
  const suit = pos === "GM";
  const style = Math.floor(r() * 6), beard = r() < 0.28 ? (r() < 0.5 ? "stubble" : "full") : "";
  const faceW = 15 + r() * 2.5, jaw = 21 + r() * 3, eyeY = 34 + r() * 1.5;
  const hair = [
    `<path d="M${32 - faceW} 30c0-11 7-17 ${faceW} -17s${faceW} 6 ${faceW} 17c-3-6-8-8-${faceW}-8s-12 2-${faceW} 8z" fill="${hairC}"/>`,
    `<path d="M${32 - faceW - 1} 31c-1-12 6-19 ${faceW + 1}-19 9 0 ${faceW + 2} 6 ${faceW + 1} 19-2-7-6-10-11-10-5 3-13 4-${faceW - 5} 0z" fill="${hairC}"/>`,
    `<path d="M${32 - faceW} 28c1-9 7-13 ${faceW}-13s${faceW - 1} 4 ${faceW} 13c-5-3-10-4-${faceW}-4s-11 1-${faceW} 4z" fill="${hairC}" opacity=".9"/>`,
    `<path d="M${32 - faceW - 2} 36c-2-15 5-23 ${faceW + 2}-23s${faceW + 4} 8 ${faceW + 2} 23c-1-8-3-12-5-13-7 1-17 1-${faceW * 2 - 8} 0-2 1-4 5-5 13z" fill="${hairC}"/>`,
    `<path d="M${32 - faceW + 1} 26c3-6 8-8 ${faceW - 1}-8s${faceW - 4} 2 ${faceW - 1} 8c-6-2-10-2-${faceW - 1}-2s-9 0-${faceW - 1} 2z" fill="${hairC}" opacity=".55"/>`,
    `<g fill="${hairC}">${[...Array(9)].map((_, i) => `<circle cx="${32 - faceW + 3 + i * (faceW * 2 - 6) / 8}" cy="${19 + Math.abs(4 - i) * 1.2}" r="4.2"/>`).join("")}</g>`][style];
  const beardSvg = beard === "full" ? `<path d="M${32 - faceW + 1} 38c1 ${jaw - 12} 7 ${jaw - 8} ${faceW - 1} ${jaw - 8}s${faceW - 2}-${4} ${faceW - 1}-${jaw - 8}c-3 5-8 7-${faceW - 1} 7s-${faceW - 3}-2-${faceW - 1}-7z" fill="${hairC}" opacity=".92"/>`
    : beard === "stubble" ? `<path d="M${32 - faceW + 2} 40c2 ${jaw - 14} 7 ${jaw - 10} ${faceW - 2} ${jaw - 10}s${faceW - 4}-4 ${faceW - 2}-${jaw - 10}c-3 4-8 6-${faceW - 2} 6s-${faceW - 4}-2-${faceW - 2}-6z" fill="${hairC}" opacity=".28"/>` : "";
  const body = suit
    ? `<path d="M6 72c2-12 10-17 26-17s24 5 26 17z" fill="#2f3b4c"/><path d="M26 55l6 10 6-10z" fill="#fff"/><path d="M31 57h2l1.6 9-2.6 4-2.6-4z" fill="#8a1c2b"/>`
    : `<path d="M4 72c2-13 11-18 28-18s26 5 28 18z" fill="${ja}"/><path d="M4 72c1-5 3-9 6-11l4 11zM60 72c-1-5-3-9-6-11l-4 11z" fill="${jb}" opacity=".9"/><path d="M24 54.5c2 4 5 5.5 8 5.5s6-1.5 8-5.5" fill="none" stroke="${jb}" stroke-width="3"/>`;
  return `<svg class="portrait" width="${size}" height="${Math.round(size * 1.125)}" viewBox="0 0 64 72" aria-hidden="true">
    <defs><linearGradient id="pbg${hashStr(seed) % 9999}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#eef3f9"/><stop offset="1" stop-color="#c9d6e6"/></linearGradient></defs>
    <rect width="64" height="72" fill="url(#pbg${hashStr(seed) % 9999})"/>${body}
    <rect x="27" y="45" width="10" height="11" rx="3" fill="${skin}"/><ellipse cx="${32 - faceW}" cy="${eyeY + 1}" rx="2.4" ry="3.6" fill="${skin}"/><ellipse cx="${32 + faceW}" cy="${eyeY + 1}" rx="2.4" ry="3.6" fill="${skin}"/>
    <ellipse cx="32" cy="${33 + (jaw - 22) * .3}" rx="${faceW}" ry="${faceW * 1.22 + (jaw - 22) * .25}" fill="${skin}"/>
    ${beardSvg}${hair}
    <path d="M${26 - faceW * .1} ${eyeY - 3.2}h5M${33 + faceW * .1} ${eyeY - 3.2}h5" stroke="${hairC}" stroke-width="1.6" stroke-linecap="round"/>
    <ellipse cx="${28.3 - faceW * .1}" cy="${eyeY}" rx="1.5" ry="1.2" fill="#2a2a2a"/><ellipse cx="${35.7 + faceW * .1}" cy="${eyeY}" rx="1.5" ry="1.2" fill="#2a2a2a"/>
    <path d="M32 ${eyeY + 1}l-1.6 6.2h3" fill="none" stroke="#000" stroke-opacity=".22" stroke-width="1.1" stroke-linejoin="round"/>
    <path d="M28.5 ${eyeY + 11}c2 1.4 5 1.4 7 0" fill="none" stroke="#7a3b2e" stroke-opacity=".6" stroke-width="1.3" stroke-linecap="round"/></svg>`;
}

/* ================================================================ the menu bar */
const MENUS = [
  ["File", [["New Game...", async () => { if (STATE && STATE.loaded && !(await ask("Start a new career? This one is saved as it is."))) return; Title.show("new"); }],
            ["Load Game...", () => Saves.menu()], ["Save Game As...", () => Saves.menu()], "-",
            ["Settings...", () => Settings.open()], ["Console", () => { SETTINGS.show_console = !SETTINGS.show_console; applySettings(); saveSettings(); }, () => SETTINGS.show_console],
            "-", ["Start Screen", async () => { await post("/api/save", {action: "close"}).catch(() => null); refresh(); }], ["Credits", () => Credits.open()], "-", ["Exit", () => App.exit(), null, "Alt+F4"]]],
  ["Manager", [["Office", "#dashboard", null, "Home"], ["Inbox", "#inbox"], ["Press Room", "#press"], "-", ["Job Security", "#board"], ["Manager Profile", "#gm"], "-",
               ["Search...", () => $("#mb-search").focus(), null, "Ctrl+F"]]],
  ["Team", [["Roster", "#roster"], ["Lineup and Tactics", "#lines"], ["Leadership Group...", () => Leaders.open(null)], "-", ["Contracts and Cap", "#contracts"],
            ["Prospects", "#prospects"], ["Development", "#development"], ["Staff", "#staff"], ["Scouting", "#scouting"], "-", ["Trade Offer", "#trade"],
            ["Three-Team Trade", "#trade3"], "-", ["Calendar", "#calendar"], ["Schedule and Results", "#schedule"], ["Team Page", () => { location.hash = `#team/${STATE.team_id}`; }],
            ["Organisation History", "#history/club"]]],
  ["League", [["Standings", "#standings"], ["Playoffs", "#playoffs"], "-", ["Free Agent Centre", "#freeagents"], ["Transactions", "#offseason"],
              ["Re-signing (Rights)", "#rights"], ["Free Agency War Room", "#warroom"], ["Draft Room", "#draft"], "-", ["News", "#news"], ["League Trades", "#history/trades"],
              ["League History", "#stats/history"]]],
  ["Statistics", [["League Leaders", "#stats/leaders"], ["Player Statistics", "#stats/skaters"], ["Goalie Statistics", "#stats/goalies"], ["Team Statistics", "#stats/teams"],
                  "-", ["Advanced Analytics", "#analytics"], ["Playoff Odds", "#analytics/odds"], "-", ["Records and Awards", "#stats/history"]]],
  ["Play", [["Continue (one day)", () => App.sim("day"), null, "Space"], ["One Week", () => App.sim("week")], ["To Next Game", () => App.sim("next")],
            ["Rest of Season", () => App.sim("season")], "-", ["Next Offseason Phase", () => phaseAdvance()]]],
  ["Help", [["Credits", () => Credits.open()], ["About", () => Credits.open(true)]]],
];
const Menu = {
  open: null,
  build() {
    $("#mb-menus").innerHTML = MENUS.map(([name], i) => `<div class="mb-item" data-mi="${i}"><button class="mb-top">${name}</button></div>`).join("");
  },
  show(i) {
    this.close();
    const [, items] = MENUS[i];
    const host = $(`.mb-item[data-mi="${i}"]`);
    host.classList.add("open");
    const html = items.map((it, j) => it === "-" ? '<div class="mb-sep"></div>' : `<button class="mb-entry${it[2] && it[2]() ? " checked" : ""}" data-mj="${j}"><span>${esc(it[0])}</span>${it[3] ? `<kbd>${esc(it[3])}</kbd>` : ""}</button>`).join("");
    host.insertAdjacentHTML("beforeend", `<div class="mb-drop">${html}</div>`);
    this.open = i;
  },
  close() {
    document.querySelectorAll(".mb-item.open").forEach((x) => { x.classList.remove("open"); const d = x.querySelector(".mb-drop"); if (d) d.remove(); });
    this.open = null;
  },
};
document.addEventListener("click", (e) => {
  const top = e.target.closest(".mb-top");
  if (top) { const i = +top.parentNode.dataset.mi; if (Menu.open === i) Menu.close(); else Menu.show(i); return; }
  const ent = e.target.closest(".mb-entry");
  if (ent) {
    const i = +ent.closest(".mb-item").dataset.mi, it = MENUS[i][1][+ent.dataset.mj];
    Menu.close();
    if (typeof it[1] === "string") location.hash = it[1]; else it[1]();
    return;
  }
  if (!e.target.closest(".mb-item")) Menu.close();
});
document.addEventListener("mouseover", (e) => {
  if (Menu.open == null) return;
  const top = e.target.closest(".mb-top");
  if (top && +top.parentNode.dataset.mi !== Menu.open) Menu.show(+top.parentNode.dataset.mi);
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { Menu.close(); $("#mb-results").hidden = true; }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f" && STATE && STATE.loaded) { e.preventDefault(); $("#mb-search").focus(); }
  if (e.key === "Home" && !/input|select|textarea/i.test(document.activeElement.tagName) && STATE && STATE.loaded) location.hash = "#dashboard";
  if (e.key === " " && !/input|select|textarea|button/i.test(document.activeElement.tagName) && STATE && STATE.loaded && $("#modal").hidden && $("#simcentre").hidden && $("#title").hidden) {
    e.preventDefault(); App.continue();
  }
});
$("#nav-home").addEventListener("click", () => { location.hash = "#dashboard"; });

/* ---- search */
let searchTimer = null;
$("#mb-search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  const q = $("#mb-search").value.trim();
  if (q.length < 2) { $("#mb-results").hidden = true; return; }
  searchTimer = setTimeout(async () => {
    const d = await api("search", {q}).catch(() => ({players: [], teams: []}));
    const box = $("#mb-results");
    box.innerHTML = (d.teams.map((t) => `<a href="#team/${t.team_id}">${crest(t.abbr, 14)} ${esc(t.name)}</a>`).join("") +
      d.players.map((p) => `<a href="#player/${p.player_id}"><span class="pos">${esc(p.pos)}</span> ${esc(p.name)} <span class="muted">${esc(p.team || p.status)}</span></a>`).join("")) || '<div class="muted">Nobody by that name.</div>';
    box.hidden = false;
  }, 180);
});
$("#mb-results").addEventListener("click", (e) => { if (e.target.closest("a")) { $("#mb-results").hidden = true; $("#mb-search").value = ""; } });
document.addEventListener("click", (e) => { if (!e.target.closest(".mb-search")) $("#mb-results").hidden = true; });

/* ================================================================ app actions */
const App = {
  sim(mode) {
    const b = document.querySelector(`#sb-controls [data-sim="${mode}"]`);
    if (b) b.click(); else toast(STATE && STATE.phase !== "regular_season" ? "It is the offseason: use Next offseason phase." : "Nothing to play.", true);
  },
  continue() {
    if (!STATE || !STATE.started) return;
    if (STATE.phase === "regular_season" || STATE.phase === "playoffs") this.sim("day");
    else { const b = document.querySelector('#sb-controls [data-cmd="offseason"]'); if (b) b.click(); }
  },
  async exit() {
    if (!(await ask("Exit Hockey Manager? Your career is saved.", {ok: "Exit"}))) return;
    await post("/api/quit", {}).catch(() => null);
    document.body.innerHTML = '<div class="bye"><b>Hockey Manager</b><p>Your career is saved. You can close this window.</p></div>';
    try { window.close(); } catch (e) { /* a browser tab */ }
  },
};

/* ================================================================ the screen header */
const SCREEN_NAMES = {dashboard: "Office", inbox: "Inbox", roster: "Roster", lines: "Lineup and Tactics", contracts: "Contracts and Cap", trade: "Trade Offer",
  trade3: "Three-Team Trade", offseason: "Transactions", rights: "Re-signing", warroom: "Free Agency", draft: "Draft Room", prospects: "Prospects",
  development: "Development", scouting: "Scouting", staff: "Staff", calendar: "Calendar", schedule: "Schedule", standings: "Standings", playoffs: "Playoffs",
  stats: "Statistics", analytics: "Advanced Analytics", leaguehistory: "League History", history: "History", news: "News", board: "Job Security", gm: "Manager Profile",
  press: "Press Room", player: "Player Profile", team: "Team", game: "Game", freeagents: "Free Agent Centre"};
// which top tab lights up for screens that live in the menus
const TAB_OF = {trade3: "trade", rights: "offseason", warroom: "offseason", draft: "offseason", development: "prospects", schedule: "calendar", playoffs: "standings",
  analytics: "stats", leaguehistory: "stats", freeagents: "offseason", board: "dashboard", gm: "dashboard", press: "inbox", history: "dashboard"};
function updateHeader() {
  const view = (location.hash.slice(1) || "dashboard").split("/")[0];
  $("#sh-screen").textContent = SCREEN_NAMES[view] || "Office";
  const tab = TAB_OF[view] || view;
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === tab));
  if (!STATE || !STATE.started) return;
  $("#sh-crest").innerHTML = crest(STATE.abbr, 44);
  $("#tb-team").textContent = STATE.team;
  const d = new Date(STATE.date + "T12:00:00");
  $("#sh-date").textContent = isNaN(d) ? STATE.date : d.toLocaleDateString("en-GB", {weekday: "short", day: "numeric", month: "short", year: "numeric"});
  const r = STATE.record;
  $("#sh-record").textContent = r ? `${r.w}-${r.l}-${r.otl}${r.t ? "-" + r.t : ""}, ${r.pts} pts` : "";
  const title = `${STATE.team} (${STATE.save || ""}) - ${SCREEN_NAMES[view] || "Office"}`;
  document.title = `Hockey Manager - ${title}`;
  if (APP.desktop && App._title !== title) { App._title = title; post("/api/title", {title}).catch(() => null); }
}
const renderV27 = render;
render = async function () {
  updateHeader();
  await renderV27();
  updateHeader();
  decorate($("#view"));
};
window.removeEventListener("hashchange", renderV27);              // app.js bound the original; route through the wrapper
window.addEventListener("hashchange", () => render());
const refreshV27b = refresh;
refresh = async function () {
  await refreshV27b();
  if (STATE && STATE.started) {
    const c = $("#sb-controls");
    // the primary action reads like the classic Continue button
    const nx = c.querySelector('[data-sim="next"]');
    if (nx) nx.textContent = "Continue to next game";
    const day = c.querySelector('[data-sim="day"]');
    if (day) day.title = "Continue one day (Space)";
    updateHeader();
  }
};
// crests next to club abbreviations in tables the older screens draw
function decorate(root) {
  if (!root) return;
  root.querySelectorAll("span.ab:not(.decorated)").forEach((s) => { s.classList.add("decorated"); s.insertAdjacentHTML("beforebegin", crest(s.textContent.trim(), 15)); });
  root.querySelectorAll(".tm-badge:not(.decorated)").forEach((s) => { s.classList.add("decorated"); s.innerHTML = crest(s.textContent.trim(), 64); });
}

/* ================================================================ launch screen (cinematic) */
const Launch = {
  async home() {
    const d = await (await fetch("/api/saves")).json();
    const el = $("#title");
    el.hidden = false; el.className = "titlescreen launch";
    const latest = d.enabled ? d.saves[0] : null;
    const item = (id, icon, title, sub, dis) => `<button class="ln-item${id === "ln-new" ? " hot" : ""}" id="${id}"${dis ? " disabled" : ""}><span class="ln-ico">${icon}</span><span class="ln-txt"><b>${title}</b><i>${sub}</i></span><span class="ln-chev">&#8250;</span></button>`;
    const puckIco = '<svg viewBox="0 0 40 40" width="38" height="38"><ellipse cx="20" cy="24" rx="16" ry="7" fill="#0b0f14"/><rect x="4" y="16" width="32" height="8" fill="#0b0f14"/><ellipse cx="20" cy="16" rx="16" ry="7" fill="#1d232b" stroke="#3a4552"/></svg>';
    const folderIco = '<svg viewBox="0 0 40 40" width="34" height="34"><path d="M4 11h12l3 4h17v18H4z" fill="none" stroke="#e8eef6" stroke-width="2.4" stroke-linejoin="round"/><path d="M4 18h32" stroke="#e8eef6" stroke-width="2.4"/></svg>';
    const gearIco = '<svg viewBox="0 0 40 40" width="34" height="34"><circle cx="20" cy="20" r="6" fill="none" stroke="#e8eef6" stroke-width="2.6"/><path d="M20 5v5M20 30v5M5 20h5M30 20h5M9.4 9.4l3.5 3.5M27.1 27.1l3.5 3.5M9.4 30.6l3.5-3.5M27.1 12.9l3.5-3.5" stroke="#e8eef6" stroke-width="4" stroke-linecap="round"/></svg>';
    const exitIco = '<svg viewBox="0 0 40 40" width="34" height="34"><path d="M17 7H8v26h9" fill="none" stroke="#e8eef6" stroke-width="2.6" stroke-linejoin="round"/><path d="M15 20h19M27 13l7 7-7 7" fill="none" stroke="#e8eef6" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    const credIco = '<svg viewBox="0 0 40 40" width="34" height="34"><path d="M20 6l4.2 8.6 9.4 1.4-6.8 6.6 1.6 9.4-8.4-4.4-8.4 4.4 1.6-9.4L6.4 16l9.4-1.4z" fill="none" stroke="#e8eef6" stroke-width="2.4" stroke-linejoin="round"/></svg>';
    // the six blocks of the backdrop (launch.jpg, 1672 x 941): left edge, top of each block, height, all in % of the picture
    const TOPS = [26.67, 35.6, 44.63, 53.56, 62.49, 71.63];
    const entries = [
      ["ln-cont", puckIco, "CONTINUE", latest ? `${esc(latest.name)} · ${esc(latest.team_name || "")}${latest.date ? " · " + esc(latest.date) : ""}` : "No career yet", !latest],
      ["ln-new", puckIco, "NEW STANDARD GAME", "Start a new season", false],
      ["ln-load", folderIco, "LOAD GAME", "Continue your saved game", !d.enabled || !d.saves.length],
      ["ln-set", gearIco, "SETTINGS", "Configure your game", false],
      ["ln-cred", credIco, "CREDITS", "Who made this, and with what", false],
      ["ln-exit", exitIco, "EXIT", "Quit the game", false]];
    el.innerHTML = `<div class="ln-ver">v${esc(APP.version || "")}</div><div class="ln-stage"><div class="ln-brand">HOCKEY <span>MANAGER</span></div>
      ${entries.map(([id, ico, t, sub, dis], k) => `<button class="ln-block${k === (latest ? 0 : 1) ? " hot" : ""}" id="${id}" style="top:${TOPS[k]}%"${dis ? " disabled" : ""}>
        <span class="ln-ico">${ico}</span><span class="ln-txt"><b>${t}</b><i>${sub}</i></span><span class="ln-chev2">&#8250;</span></button>`).join("")}</div>
      ${APP.desktop ? "" : '<div class="ln-note">Running in a browser tab. Start it with play.sh / PLAY_WINDOWS.bat for its own window.</div>'}`;
    el.querySelectorAll(".ln-block").forEach((b) => b.addEventListener("mouseenter", () => el.querySelectorAll(".ln-block").forEach((x) => x.classList.toggle("hot", x === b && !b.disabled))));
    if (latest) $("#ln-cont").onclick = async () => { await post("/api/save", {action: "load", name: latest.name}).catch((e) => toast(e.message, true)); el.hidden = true; el.className = "titlescreen"; refresh(); };
    $("#ln-new").onclick = () => Title.show("new");
    $("#ln-load").onclick = () => this.load(d);
    $("#ln-set").onclick = () => Settings.open();
    $("#ln-cred").onclick = () => Credits.open();
    $("#ln-exit").onclick = () => App.exit();
  },
  load(d) {
    Modal.open(`<div class="win-title">Load Game</div><p class="muted">Careers in ${esc(d.folder)}</p>${Saves.list(d)}<p class="row right"><button onclick="Modal.close()">Cancel</button></p>`, "win wide");
    Saves.wire(d, () => { $("#title").hidden = true; $("#title").className = "titlescreen"; });
  },
};
const titleV27 = Title.show.bind(Title);
Title.show = async function (page = "home") {
  if (page === "home") return Launch.home();
  if (page === "load") { const d = await (await fetch("/api/saves")).json(); await Launch.home(); return Launch.load(d); }
  $("#title").className = "titlescreen setup";
  return titleV27(page);
};

/* ================================================================ settings */
async function saveSettings() { try { SETTINGS = await post("/api/settings", SETTINGS); } catch (e) { /* not saved */ } applySettings(); }
const Settings = {
  open() {
    const s = SETTINGS;
    const chk = (k, l, h) => `<label class="chkrow"><input type="checkbox" data-set="${k}"${s[k] ? " checked" : ""}> <span><b>${l}</b>${h ? `<i>${h}</i>` : ""}</span></label>`;
    Modal.open(`<div class="win-title">Settings</div>
      <div class="tabs win-tabs"><button class="active" data-stab="iface">Interface</button><button data-stab="play">Gameplay</button></div>
      <div class="set-pane" data-pane="iface">
        <fieldset><legend>Display</legend>
          <label class="frow">Interface size <select data-set="ui_scale">${[80, 90, 100, 110, 125, 140, 150].map((v) => `<option value="${v}"${+s.ui_scale === v ? " selected" : ""}>${v}%</option>`).join("")}</select></label>
          <label class="frow">Units <select data-set="units"><option value="metric"${s.units === "metric" ? " selected" : ""}>Metric (cm, kg)</option><option value="imperial"${s.units === "imperial" ? " selected" : ""}>Imperial (ft/in, lb)</option></select></label>
          ${chk("highlight_team", "Highlight my club", "your club's rows stand out in every table")}
          ${chk("player_popups", "Player cards", "clicking a name in lists opens the quick card")}
          ${chk("show_console", "Show the console", "the command box in the bottom bar (File > Console)")}
          ${chk("schedule_strip", "Schedule strip", "your games from yesterday into next week, in the club header")}
        </fieldset>
        <fieldset><legend>Start-up</legend>${chk("intro", "Show the launch screen", "off: go straight to your last career")}</fieldset>
      </div>
      <div class="set-pane" data-pane="play" hidden>
        <fieldset><legend>Simulation</legend>
          <label class="frow">Sim centre pace <select data-set="sim_pace">${[[0, "Instant"], [0.25, "Fast"], [0.6, "Normal"], [1.5, "Watch"]].map(([v, l]) => `<option value="${v}"${+s.sim_pace === v ? " selected" : ""}>${l}</option>`).join("")}</select></label>
          ${chk("confirm_phase", "Ask before each offseason phase", "says what comes next, and warns about decisions left")}
          <p class="muted small" style="margin:8px 0 2px"><b>Rest of season and Play until stop for:</b></p>
          ${chk("stop_trade_offer", "Trade offers", "a club makes you an offer")}
          ${chk("stop_board", "The owner's office", "ultimatums, directives, dismissals")}
          ${chk("stop_press", "Major press conferences", "captaincy, trade requests, the deadline, the season's end")}
          ${chk("stop_deadline", "The trade deadline", "three days before, and deadline day")}
          ${chk("stop_injury", "Injuries to your players", "")}
          ${chk("stop_room", "Trouble in the dressing room", "")}
          <label class="frow">Your draft pick clock <select data-set="draft_clock">${[[45, "45 seconds"], [90, "90 seconds"], [180, "3 minutes"], [600, "10 minutes"]].map(([v, l]) => `<option value="${v}"${+s.draft_clock === v ? " selected" : ""}>${l}</option>`).join("")}</select></label>
        </fieldset>
        <fieldset><legend>Saves</legend>
          <label class="frow">Rolling backups kept <select data-set="backups">${[[0, "None"], [1, "1"], [3, "3"], [5, "5"], [10, "10"]].map(([v, l]) => `<option value="${v}"${+s.backups === v ? " selected" : ""}>${l}</option>`).join("")}</select></label>
          <p class="muted small">One a game week and at each new phase, in saves/backups. File &gt; Backups restores one as a new save.</p>
        </fieldset>
        <p class="muted small">Settings are kept in the saves folder (settings.json) and apply to every career.</p>
      </div>
      <div class="win-buttons"><button class="primary" id="set-ok">OK</button> <button onclick="Modal.close()">Cancel</button></div>`, "win");
    document.querySelectorAll("[data-stab]").forEach((b) => b.onclick = () => {
      document.querySelectorAll("[data-stab]").forEach((x) => x.classList.toggle("active", x === b));
      document.querySelectorAll(".set-pane").forEach((p) => p.hidden = p.dataset.pane !== b.dataset.stab);
    });
    $("#set-ok").onclick = async () => {
      document.querySelectorAll("[data-set]").forEach((x) => { const k = x.dataset.set; SETTINGS[k] = x.type === "checkbox" ? x.checked : (isNaN(+x.value) || x.value === "" ? x.value : +x.value); });
      await saveSettings();
      Modal.close();
      toast("Settings saved.");
      if (typeof drawStrip === "function") drawStrip();
      if (STATE && STATE.loaded) render();
    };
  },
};

/* ================================================================ credits */
const Credits = {
  open(about = false) {
    Modal.open(`<div class="win-title">${about ? "About Hockey Manager" : "Credits"}</div>
      <div class="credits">
        <div class="cr-logo">HOCKEY <span>MANAGER</span><i>version ${esc(APP.version || "")}</i></div>
        <h4>Design / Architecture / Written by</h4><p>Jeremy Legere</p>
        <h4>Inspired by</h4><p>The classic hockey management games of the early 2000s, reimagined with modern mechanics.</p>
        <h4>Built with</h4><ul>
          <li>Python and SQLite (the game, the save files)</li>
          <li>plotly.js 2.35 (analytics charts; MIT licence)</li>
          <li>pywebview (the desktop window; BSD licence), with WebView2, WebKit or Qt WebEngine underneath</li></ul>
        <h4>Data</h4><p>The world that ships with the game is fictional: every club, town and player is invented. Build your own league from a spreadsheet (docs/BUILD_YOUR_OWN.md) or import your own export of a community database for personal use (File &gt; Import Database). Club crests and player portraits are drawn by the game.</p>
        <h4>Names</h4><p>Real names loaded from your own data stay on your computer, for your personal use.</p>
        <p class="muted small">A personal, open-source project. Thanks for playing.</p>
      </div>
      <div class="win-buttons"><button class="primary" onclick="Modal.close()">Close</button></div>`, "win");
  },
};

/* ================================================================ calendar */
const Cal = {month: null};
VIEWS.calendar = async (arg) => {
  const d = await api("calendar", Cal.month ? {month: Cal.month} : {});
  Cal.month = d.month;
  const [y, m] = d.month.split("-").map(Number);
  const first = new Date(y, m - 1, 1), days = new Date(y, m, 0).getDate();
  const lead = (first.getDay() + 6) % 7;                                     // weeks start on Monday
  const byDate = {}; d.games.forEach((g) => (byDate[g.date] = byDate[g.date] || []).push(g));
  const ev = {}; d.events.forEach((e) => (ev[String(e.date).slice(0, 10)] = ev[String(e.date).slice(0, 10)] || []).push(e.label));
  const cells = [];
  for (let i = 0; i < lead; i++) cells.push('<td class="off"></td>');
  for (let dd = 1; dd <= days; dd++) {
    const ds = `${d.month}-${String(dd).padStart(2, "0")}`;
    const gs = (byDate[ds] || []).map((g) => `<div class="cal-g ${g.home ? "home" : "away"} ${g.result ? "r-" + g.result.toLowerCase() : ""}">${crest(g.opponent, 13)}<span>${g.home ? "vs" : "@"} ${esc(g.opponent)}</span>
      ${g.played ? `<a href="#game/${g.game_id}" class="sc">${esc(g.result)} ${esc(g.score)}${g.ot ? " " + g.ot : ""}</a>` : g.type === "PO" ? '<i>playoffs</i>' : ""}</div>`).join("");
    const es = (ev[ds] || []).map((x) => `<div class="cal-e">${esc(x)}</div>`).join("");
    cells.push(`<td class="${ds === d.today ? "today" : ""}${ds < d.today ? " past" : ""}"><div class="cal-d">${dd}</div>${es}${gs}</td>`);
  }
  while (cells.length % 7) cells.push('<td class="off"></td>');
  const rows = []; for (let i = 0; i < cells.length; i += 7) rows.push(`<tr>${cells.slice(i, i + 7).join("")}</tr>`);
  const mi = d.months.indexOf(d.month);
  const name = first.toLocaleDateString("en-GB", {month: "long", year: "numeric"});
  const played = d.games.filter((g) => g.played && g.date.startsWith(d.month)), w = played.filter((g) => g.result === "W").length;
  const ctl = `<div class="toolbar"><button id="cal-prev"${mi <= 0 ? " disabled" : ""}>&#9664; Previous</button><b class="cal-name">${esc(name)}</b><button id="cal-next"${mi >= d.months.length - 1 ? " disabled" : ""}>Next &#9654;</button>
    <button id="cal-today">Today</button><span class="spacer"></span><span class="muted">${played.length ? `This month: ${w}-${played.length - w}` : ""}</span><a class="btn" href="#schedule">List view</a></div>`;
  AFTER = () => {
    $("#cal-prev").onclick = () => { Cal.month = d.months[mi - 1]; render(); };
    $("#cal-next").onclick = () => { Cal.month = d.months[mi + 1]; render(); };
    $("#cal-today").onclick = () => { Cal.month = d.today.slice(0, 7); render(); };
  };
  return ctl + panel(`Calendar: ${name}`, `<table class="calendar"><thead><tr>${["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((x) => `<th>${x}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>
    <p class="muted small">Home games are shaded. Click a result for the box score and replay.</p>`);
};

/* ================================================================ free agent centre */
const FAC = {pos: ""};
VIEWS.freeagents = async () => {
  const d = await api("freeagents", {pos: FAC.pos});
  const live = d.phase === "free_agency";
  const head = `<div class="toolbar"><label>Position <select id="fa-pos">${["", "C", "LW", "RW", "D", "G"].map((p) => `<option value="${p}"${p === FAC.pos ? " selected" : ""}>${p || "All"}</option>`).join("")}</select></label>
    <span class="spacer"></span><span>Cap room <b>${mil(d.cap_room)}</b> · contracts ${d.contracts}/50</span>${live ? ' <a class="btn primary" href="#warroom">Go to the war room</a>' : ""}</div>`;
  AFTER = () => { $("#fa-pos").onchange = (e) => { FAC.pos = e.target.value; render(); }; };
  const rows = table(d.players, [
    {key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "pos", label: "Pos"}, {key: "age", label: "Age", num: true},
    {key: "nat", label: "Nat"}, {key: "value", label: "Value", num: true}, {key: "ask", label: "Asking", num: true, fmt: (r) => mil(r.ask)},
    {key: "act", label: "", fmt: (r) => live ? "" : `<button class="mini" data-cmd="sign ${r.player_id}" data-confirm="Sign ${esc(r.name)} at his ask (${mil(r.ask)})?">Sign at ask</button>`}]);
  return head + panel(`Free agents (${d.players.length})`, d.players.length ? `<div class="scroll tall">${rows}</div>` :
    `<p class="muted">Nobody is unsigned right now. ${live ? "" : "The market fills on 1 July, and with players clubs release or do not qualify."}</p>`);
};

/* ================================================================ prospects */
// ability and potential as stars (0.5 to 5), the way scouts talk: ability from the value scale, potential from 1-20
function stars(x) {
  if (x == null) return '<span class="muted">-</span>';
  const v = Math.max(0.5, Math.min(5, Math.round(x * 2) / 2));
  return `<span class="stars" title="${v} of 5 stars">${"\u2605".repeat(Math.floor(v))}${v % 1 ? "\u00bd" : ""}<i>${"\u2605".repeat(5 - Math.ceil(v))}</i></span>`;
}
const abilityStars = (value) => stars(value == null ? null : (value - 35) / 5);
const potentialStars = (p) => stars(p == null ? null : p / 4);
VIEWS.prospects = async () => {
  const d = await api("prospects");
  const pot = (v) => potentialStars(v);
  const t1 = table(d.rights, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "pos", label: "Pos"}, {key: "age", label: "Age", num: true},
    {key: "club", label: "Playing for"}, {key: "draft_year", label: "Drafted", fmt: (r) => `${r.draft_year}${r.pick ? ` (#${r.pick})` : ""}`},
    {key: "expires", label: "Rights to", num: true}, {key: "value", label: "Ability", fmt: (r) => `${abilityStars(r.value)} <span class="muted small">${r.value}</span>`}, {key: "potential", label: "Potential", fmt: (r) => pot(r.potential)},
    {key: "act", label: "", fmt: (r) => /\(KHL\)$/.test(r.club || "")
      ? `<button class="mini" data-cmd="elc ${r.player_id} khl" data-confirm="Offer ${esc(r.name)} the maximum entry-level deal so he can buy himself out of his KHL contract? He is more likely to say yes once the KHL season is over (March). One ask a month.">KHL buyout offer</button>`
      : `<button class="mini" data-cmd="elc ${r.player_id}" data-confirm="Sign ${esc(r.name)} to his entry-level contract?${/\(NCAA\)$/.test(r.club || "") ? " College players sign once their season ends (late March); signing during the NHL season starts his deal this year." : ""}">Sign ELC</button>`}]);
  const t2 = table(d.signed, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "pos", label: "Pos"}, {key: "age", label: "Age", num: true},
    {key: "club", label: "Playing for"}, {key: "cap", label: "Cap hit", num: true, fmt: (r) => r.contract ? mil(r.contract.cap_hit) : "-"},
    {key: "ends", label: "Final season", fmt: (r) => r.contract ? ssn(r.contract.ends) : "-"}, {key: "value", label: "Ability", fmt: (r) => `${abilityStars(r.value)} <span class="muted small">${r.value}</span>`},
    {key: "potential", label: "Potential", fmt: (r) => pot(r.potential)},
    {key: "act", label: "", fmt: (r) => `<button class="mini" data-cmd="recall ${r.player_id}">Recall</button>`}]);
  return `<div class="grid">${panel(`Unsigned draft rights (${d.rights.length})`, d.rights.length ? t1 : '<p class="muted">None.</p>')}
    ${panel(`Signed, below the NHL (${d.signed.length})`, d.signed.length ? t2 : '<p class="muted">None.</p>', '<a href="#development">Development &#8250;</a>')}</div>`;
};

/* ================================================================ development */
VIEWS.development = async () => {
  const d = await api("development");
  const ch = (v) => v == null ? '<span class="muted">-</span>' : `<b class="${v > 0.5 ? "r4" : v < -0.5 ? "r1" : ""}">${v > 0 ? "+" : ""}${v}</b>`;
  const t = table(d.players, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "pos", label: "Pos"}, {key: "age", label: "Age", num: true},
    {key: "status", label: "Where", fmt: (r) => r.status === "prospect" ? '<span class="tag">minors</span>' : "NHL"},
    {key: "was", label: "Value last summer", num: true, fmt: (r) => r.was ?? "-"}, {key: "value", label: "Value today", num: true}, {key: "change", label: "Change", num: true, fmt: (r) => ch(r.change)},
    {key: "potential", label: "Potential", num: true, fmt: (r) => r.potential == null ? "-" : `<span class="${ratingClass(r.potential)}">${r.potential}</span>`}]);
  return panel("Development: your organisation", `${d.snapshots.length ? "" : '<p class="muted">Development is measured from each summer\'s snapshot of every player\'s ratings; the first comes at the end of this season. Until then the table shows where everyone stands.</p>'}
    <div class="scroll tall">${t}</div><p class="muted small">Players develop (and age) each summer; your coaches' development rating and ice time matter. A player's ratings history is on his profile (Ratings tab).</p>`);
};

/* ================================================================ smaller touches */
/* ---- boot: called at the end of the last script (v29.js) ---- */
function bootApp() {
  Menu.build();
  (async () => {
    await loadSettings();
    if (!SETTINGS.intro) {                     // straight to the last career
      try {
        const st = await api("state");
        if (!st.loaded) { const d = await (await fetch("/api/saves")).json(); if (d.enabled && d.saves.length) await post("/api/save", {action: "load", name: d.saves[0].name}); }
      } catch (e) { /* the launch screen will show */ }
    }
    refresh();
  })();
}
