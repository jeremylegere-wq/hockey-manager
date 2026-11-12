"use strict";
// v29: the defects pass (docs/DEFECTS.md). News articles, the champions screen and awards night, tab badges,
// back / forward on the club header, the phase report. Loads last; boots the app.

/* ================================================================ a news story */
VIEWS.article = async (id) => {
  const d = await api("article", {id});
  const people = d.players.map((p) => `<tr><td>${portrait(p.player_id, p.team, p.pos, 34)}</td><td>${clink(p.player_id, p.name)}<div class="muted small">${esc(p.pos)} · ${esc(p.team || "free agent")} · age ${p.age ?? "-"}</div></td>
    <td class="num">${p.last ? `${p.last.gp} GP, ${p.last.g}-${p.last.a}-${p.last.g + p.last.a}` : "-"}</td><td class="num">${p.cap_hit ? mil(p.cap_hit) : "-"}</td><td class="num">${p.ends ? ssn(p.ends) : ""}</td></tr>`).join("");
  const clubs = d.clubs.map((c) => `<a class="art-club" href="#team/${c.team_id}">${crest(c.abbr, 22)} ${esc(c.name)}</a>`).join("");
  const reaction = d.reaction ? `<div class="art-post"><b>${esc(d.reaction.account.name || d.reaction.account)}</b> ${esc(d.reaction.account.handle || "")}<p>${esc(d.reaction.text)}</p>
    ${(d.reaction.replies || []).map((r) => `<div class="art-reply"><b>${esc(r.account.name || r.account)}</b> ${esc(r.text)}</div>`).join("")}</div>` : '<p class="muted">No reaction yet.</p>';
  return `<div class="toolbar"><button onclick="history.back()">&#9664; Back</button><a class="btn" href="#news">All news</a><span class="spacer"></span><span class="muted">${esc(d.outlet)}</span></div>
    <div class="grid g21"><section class="panel article"><h2>${esc(d.outlet)} <span class="right">${esc(d.date)} · ${esc(d.tag)}</span></h2><div class="body">
      <h1 class="art-head">${esc(d.headline)}</h1><div class="art-clubs">${clubs}</div>${d.paragraphs.map((p) => `<p>${esc(p)}</p>`).join("")}
      ${people ? `<h4>In this story</h4><table class="art-people"><thead><tr><th></th><th>Player</th><th class="num">Last season</th><th class="num">Cap hit</th><th class="num">Through</th></tr></thead><tbody>${people}</tbody></table>` : ""}</div></section>
    <div class="grid">${panel("Reaction", reaction)}${panel("Related", `<ul class="list">${d.related.map((r) => `<li><span class="date">${esc(r.date)}</span><a href="#article/${r.event_id}">${esc(r.text)}</a></li>`).join("") || '<li class="muted">Nothing else.</li>'}</ul>`)}</div></div>`;
};

/* ================================================================ the champions, and awards night */
VIEWS.champions = async (season) => {
  const d = await api("playoffs", season ? {season} : {});
  if (!d.champion) return panel("Champions", '<p class="muted">The playoffs are not over yet.</p><p><a class="btn" href="#playoffs">The bracket</a></p>');
  const c = d.champion, cs = d.awards.find((a) => a.key === "conn_smythe");
  const fin = d.final, opp = fin ? fin.teams.find((t) => !t.won) : null;
  const games = fin ? fin.games.map((g) => `<tr><td>Game ${g.no}</td><td>${esc(g.away)} ${g.ag} @ ${esc(g.home)} ${g.hg}${g.ot ? " " + g.ot : ""}</td><td><a href="#game/${g.game_id}">Recap</a></td></tr>`).join("") : "";
  return `<div class="champ-hero"><div class="champ-crest">${crest(c.abbr, 110)}</div><div><div class="champ-kicker">${ssn(d.season)} Stanley Cup champions</div>
      <div class="champ-name">${esc(c.name)}</div>
      <div class="champ-sub">${opp ? `Beat ${esc(opp.name)} ${fin.teams.find((t) => t.won).wins}-${opp.wins} in the final.` : ""}${c.mine ? " <b>That is your club.</b>" : ""}</div>
      <div class="champ-path">${d.champ_path.map((p) => `<span>Round ${p.round}: ${esc(p.opp)} ${esc(p.score)}</span>`).join("")}</div></div>
      <div class="champ-links"><a class="btn primary" href="#awards/${d.season}">Awards night</a> <a class="btn" href="#playoffs">The bracket</a></div></div>
    <div class="grid g3">
      ${panel("Conn Smythe Trophy (playoff MVP)", cs ? `<div class="aw-card">${cs.player_id ? portrait(cs.player_id, cs.team, "", 64) : ""}<div><div class="aw-who">${cs.player_id ? clink(cs.player_id, cs.who) : esc(cs.who)}</div><div class="muted">${esc(cs.team || "")} · ${esc(cs.detail || "")}</div><div class="muted small">voted by ${esc(cs.by)}</div></div></div>` : '<p class="muted">-</p>')}
      ${panel("Playoff scoring", table(d.champ_leaders, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "pos", label: "Pos"}, {key: "gp", label: "GP", num: true}, {key: "g", label: "G", num: true}, {key: "a", label: "A", num: true}, {key: "p", label: "P", num: true, fmt: (r) => r.g + r.a}]))}
      ${panel("The final", games ? `<table><tbody>${games}</tbody></table>` : "-")}</div>`;
};
VIEWS.awards = async (season) => {
  const d = await api("playoffs", season ? {season} : {});
  d.awards = d.awards || []; d.seasons = d.seasons || (d.season ? [d.season] : []);   // v39 (#19): before any awards exist
  const cards = d.awards.filter((a) => a.key !== "conn_smythe").map((a) => `<div class="aw-night"><div class="aw-trophy">${esc(a.award)}</div><div class="aw-what">${esc(a.what)}</div>
    <div class="aw-card">${a.player_id ? portrait(a.player_id, a.team, "", 58) : crest(a.team, 40)}<div><div class="aw-who">${a.player_id ? clink(a.player_id, a.who) : esc(a.who || "")}</div>
    <div class="muted">${esc(a.team || "")}${a.detail ? " · " + esc(a.detail) : ""}</div></div></div><div class="aw-by">Decided by ${esc(a.by || "")}</div></div>`).join("");
  if (!d.season) return panel("Awards night", '<p class="muted">The first awards night comes once this season\'s playoffs end.</p>');
  return `<div class="toolbar"><b>NHL Awards: ${ssn(d.season)}</b><span class="spacer"></span><label>Season <select id="aw-season">${d.seasons.map((y) => `<option value="${y}"${y === d.season ? " selected" : ""}>${ssn(y)}</option>`).join("")}</select></label>
      <a class="btn" href="#champions/${d.season}">The champions</a></div>
    ${d.awards.length ? `<div class="aw-grid2">${cards}</div>` : panel("Awards night", '<p class="muted">The awards are handed out once the playoffs end.</p>')}
    ${(() => { AFTER = () => { const s = $("#aw-season"); if (s) s.onchange = () => { location.hash = `#awards/${s.value}`; }; }; return ""; })()}`;
};
SCREEN_NAMES.article = "News"; SCREEN_NAMES.champions = "Champions"; SCREEN_NAMES.awards = "Awards Night";
TAB_OF.article = "news"; TAB_OF.champions = "standings"; TAB_OF.awards = "standings";
MENUS[3][1].splice(2, 0, ["Champions", "#champions"], ["Awards Night", "#awards"]);
Menu.build();

/* ================================================================ back / forward on the club header */
(function () {
  const sh = $("#screenhead");
  if (!sh || $("#sh-back")) return;
  sh.insertAdjacentHTML("afterbegin", `<span class="sh-nav"><button id="sh-back" title="Back (Alt+Left)">&#9664; Back</button><button id="sh-fwd" title="Forward (Alt+Right)">Forward &#9654;</button></span>`);
  $("#sh-back").onclick = () => history.back();
  $("#sh-fwd").onclick = () => history.forward();
  const sync = () => { $("#sh-back").disabled = NavHist.i <= 0; $("#sh-fwd").disabled = NavHist.i >= NavHist.stack.length - 1; };
  window.addEventListener("hashchange", () => setTimeout(sync, 0));
  sync();
})();

/* ================================================================ badges on the tabs */
function badges() {
  if (!STATE || !STATE.started) return;
  const b = STATE.badges || {};
  const want = {inbox: STATE.unread || 0, trade: b.offers || 0, dashboard: b.meetings || 0};
  document.querySelectorAll("#nav a").forEach((a) => {
    let n = want[a.dataset.view] || 0;
    let el = a.querySelector(".nbadge");
    if (!n) { if (el) el.remove(); return; }
    if (!el) { el = document.createElement("span"); el.className = "nbadge"; a.appendChild(el); }
    el.textContent = n > 99 ? "99+" : n;
    a.title = {inbox: `${STATE.unread || 0} unread`, trade: `${n} trade offer${n === 1 ? "" : "s"} waiting`, dashboard: `${n} meeting request${n === 1 ? "" : "s"}`}[a.dataset.view] || "";
  });
}
const refreshV28 = refresh;
refresh = async function () { await refreshV28(); badges(); };

/* ================================================================ moving through the offseason */
const PHASE_NEXT = {
  finished: ["The draft", "The lottery is drawn and the draft room opens (26 June). The buyout window is open until 30 June."],
  draft: ["Re-signing", "Your expiring contracts: qualify, extend or let them walk (29 June). Picks you have not made are made by your scouts."],
  rights: ["Free agency", "The market opens at noon on 1 July and the war room opens. Players you have not qualified or signed become free agents."],
  free_agency: ["Salary arbitration", "Filings for arbitration (5 July). Free agency carries on in the background."],
  arbitration: ["Arbitration awards", "Hearings and awards (1 August). Clubs with a case get a second 48-hour buyout window."],
  awards: ["Training camp", "Camp and the pre-season (15 September): the schedule comes out and media day follows."],
  preseason: ["Opening night", "The regular season starts."],
};
async function phaseAdvance(asked = false) {
  const ph = STATE && STATE.phase;
  const nx = PHASE_NEXT[ph];
  if (nx && !asked && SETTINGS.confirm_phase && !(await ask(`Move on: ${nx[0]}.\n${nx[1]}`, {ok: `Go to ${nx[0].toLowerCase()}`, title: "Next offseason phase"}))) return;
  setBusy(true);
  let r;
  try { r = await quietCmd("offseason"); } finally { setBusy(false); }
  await refresh();
  if (!r.ok) return toast(r.output, true);
  PhaseReport.show(nx ? nx[0] : "Next phase", r.output);
}
const PhaseReport = {
  // group the offseason's output into sections the reader can scan instead of one long toast
  groups: [["Your club", /\b(you|your)\b/i], ["Trades", /trade|acquire|swap/i], ["Draft", /lottery|draft|pick|auto-picked/i],
    ["Signings and departures", /sign|walk|qualif|free agen|offer sheet|re-sign|elc/i], ["Staff", /staff|coach|fired|hire/i],
    ["Retirements", /retire/i], ["The phase", /phase|date/i]],
  show(title, text) {
    const lines = String(text || "").split("\n").map((l) => l.trim()).filter((l) => l);
    if (!lines.length) return;
    const me = STATE && STATE.abbr;
    const buckets = new Map(this.groups.map(([g]) => [g, []]));
    buckets.set("Around the league", []);
    for (const l0 of lines) {
      const l = me ? l0.replace(new RegExp(`\\b${me}\\b`, "g"), `${me}`) : l0;
      const g = (me && new RegExp(`\\b${me}\\b`).test(l)) ? "Your club" : (this.groups.slice(1).find(([, re]) => re.test(l)) || ["Around the league"])[0];
      // "Draft-day trades (6): a; b; c" style lines become one bullet each
      const m = l.match(/^([^:]{3,40}):\s*(.+;.+)$/);
      if (m) m[2].split(/;\s*/).forEach((x) => buckets.get(g).push(`${m[1].replace(/\s*\(\d+\)$/, "").replace(/s$/, "")}: ${x}`));
      else buckets.get(g).push(l);
    }
    const sec = [...buckets].filter(([, v]) => v.length).map(([g, v]) => `<fieldset><legend>${esc(g)} (${v.length})</legend><ul class="pr-list">${v.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></fieldset>`).join("");
    Modal.open(`<div class="win-title">${esc(title)}: what happened</div><div class="phase-report">${sec}</div>
      <div class="win-buttons"><a class="btn" href="#news" onclick="Modal.close()">News</a><a class="btn" href="#inbox" onclick="Modal.close()">Inbox</a><button class="primary" onclick="Modal.close()">Continue</button></div>`, "win wide");
  },
};


/* ================================================================ draft day: the clock and pick deals (v30) */
const DraftDeals = {
  timer: null,
  html(d) {
    const x = d.deals || {};
    const parts = [];
    if (x.buy) parts.push(`<div class="dd-offer"><b>Trade up:</b> ${esc(x.buy.abbr)} would give you #${x.buy.get[0]} for #${x.buy.give.join(" + #")}
      <span class="muted small">(chart ${x.buy.value_in} for ${x.buy.value_out})</span> <button class="mini primary" data-cmd="pickswap ${esc(x.buy.abbr)} give ${x.buy.give.join(",")} get ${x.buy.get.join(",")}"
      data-confirm="Trade pick${x.buy.give.length > 1 ? "s" : ""} #${x.buy.give.join(", #")} to ${esc(x.buy.abbr)} for #${x.buy.get[0]}, the pick on the clock?">Make the trade</button></div>`);
    if (x.down && x.down.length) parts.push(`<div class="dd-offer"><b>Trade-down offers for your pick:</b><ul>${x.down.map((o) => `<li>${esc(o.abbr)}: #${o.get.join(" + #")} for #${o.give[0]}
      <span class="muted small">(chart ${o.value_in} for ${o.value_out})</span> <button class="mini" data-cmd="pickswap ${esc(o.abbr)} give ${o.give.join(",")} get ${o.get.join(",")}"
      data-confirm="Move down: give #${o.give[0]} to ${esc(o.abbr)} for #${o.get.join(" and #")}?">Accept</button></li>`).join("")}</ul></div>`);
    if (d.mine_on_clock && !(x.down && x.down.length)) parts.push('<div class="dd-offer muted">No club is offering to move up into your pick right now.</div>');
    parts.push('<div class="dd-offer muted small">Any pick deal: <code>pickswap ABBR give 24 get 18</code> in the console, priced on the pick chart.</div>');
    return `<div class="dd">${parts.join("")}</div>`;
  },
  clock(d) {
    clearInterval(this.timer);
    const el = $("#dr-clock");
    if (!el || !d.on_clock || d.done) return;
    // your pick: the clock from Settings (default 90 s); the AI's: the room's pace when it is running
    let left = d.mine_on_clock ? (+SETTINGS.draft_clock || 90) : Math.round(DraftRoom.pace(d) / 1000) || 1;
    const show = () => { el.textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`; el.classList.toggle("low", left <= 15); };
    show();
    if (!d.mine_on_clock && !DraftRoom.auto) { el.textContent = "paused"; return; }
    this.timer = setInterval(async () => {
      if (!location.hash.startsWith("#draft")) return clearInterval(this.timer);
      left -= 1; show();
      if (left <= 0) {
        clearInterval(this.timer);
        if (d.mine_on_clock && d.board && d.board.length) {
          toast(`Time: your scouts take ${d.board[0].name}.`);
          await quietCmd(`pick ${d.board[0].player_id}`);
          render();
        }
      }
    }, 1000);
  },
};


/* ================================================================ the 2D game on the game page (v30) */
const gameV29 = VIEWS.game;
VIEWS.game = async (id) => {
  const html = await gameV29(id);
  const old = AFTER;
  AFTER = () => {                                       // v59: the rebuilt 2D game; the v30 viewer, then the event replay, as fallbacks
    Ice.mount($("#replay"), id).catch((e) => { console.warn("2D game (v59) unavailable:", e);
      Rink.mount($("#replay"), id).catch((e2) => { console.warn("2D game unavailable:", e2); if (old) old(); }); }); };
  return html;
};

/* ---- boot: moved to the last script (v31.js) ---- */
