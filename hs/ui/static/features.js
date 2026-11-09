"use strict";
// v26: back/forward, pop-ups (player cards, contract talks), the sim centre, saves and the title screen,
// broadcast standings, the mail inbox, the news archive, three-team trades and the analytics suite.
// Loaded after app.js; uses its helpers ($, esc, api, cmd, panel, table, toast, mil, money, bar, VIEWS, STATE).

async function post(path, body) {
  const r = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body || {})});
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.ok === false) throw new Error(j.output || j.error || "request failed");
  return j;
}
function mailBody(text) {                          // paragraphs, and "- " lines as a list
  const out = []; let list = [];
  const flush = () => { if (list.length) { out.push(`<ul>${list.map((x) => `<li>${x}</li>`).join("")}</ul>`); list = []; } };
  for (const raw of String(text || "").split(/\n+/)) {
    const l = esc(raw.trim()).replace(/\[([^\]]+)\]$/, '<span class="muted small">($1)</span>');
    if (!l) continue;
    if (/^- /.test(raw.trim())) list.push(l.slice(2)); else { flush(); out.push(`<p>${l}</p>`); }
  }
  flush();
  return out.join("");
}
async function quietCmd(line) {                     // a command without re-rendering the screen
  const r = await fetch("/api/command", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({line})});
  return r.json();
}
const pct1 = (v) => v == null ? "-" : (v * 100).toFixed(1) + "%";
const sign = (v) => v == null ? "-" : (v > 0 ? "+" : "") + v;
const yrs = (s) => `${s}-${String((s + 1) % 100).padStart(2, "0")}`;

/* ================================================================ back / forward */
const NavHist = {stack: [location.hash || "#dashboard"], i: 0};
function navUpdate() {
  $("#nav-back").disabled = NavHist.i <= 0;
  $("#nav-fwd").disabled = NavHist.i >= NavHist.stack.length - 1;
}
window.addEventListener("hashchange", () => {
  const h = location.hash || "#dashboard";
  if (NavHist.stack[NavHist.i - 1] === h) NavHist.i--;
  else if (NavHist.stack[NavHist.i + 1] === h) NavHist.i++;
  else if (NavHist.stack[NavHist.i] !== h) { NavHist.stack = NavHist.stack.slice(0, NavHist.i + 1); NavHist.stack.push(h); NavHist.i++; }
  navUpdate();
});
$("#nav-back").addEventListener("click", () => history.back());
$("#nav-fwd").addEventListener("click", () => history.forward());
navUpdate();

/* ================================================================ modal */
const Modal = {
  onclose: null,
  open(html, cls = "") {
    $("#modal-body").innerHTML = html;
    $("#modal .modal-card").className = "modal-card " + cls;
    $("#modal").hidden = false;
    return $("#modal-body");
  },
  close() {
    $("#modal").hidden = true;
    $("#modal-body").innerHTML = "";
    const f = this.onclose; this.onclose = null;
    if (f) f();
  },
};
$("#modal .modal-x").addEventListener("click", () => Modal.close());
$("#modal").addEventListener("mousedown", (e) => { if (e.target.id === "modal") Modal.close(); });
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!$("#modal").hidden) Modal.close();
  else if (Sim.open && !Sim.running) Sim.close();
});

/* ================================================================ player card */
document.addEventListener("click", (e) => {
  const a = e.target.closest("[data-card]");
  if (!a || e.ctrlKey || e.metaKey || (typeof SETTINGS !== "undefined" && !SETTINGS.player_popups)) return;
  e.preventDefault();
  Card.open(+a.dataset.card);
});
const Card = {
  async open(id) {
    Modal.open('<p class="muted">Loading...</p>', "card");
    const c = await api("card", {id});
    const rat = c.ratings.map((r) => `<div class="cr-row"><span>${esc(r.label)}</span><div class="cr-bar"><i style="width:${(r.value || 0) / 20 * 100}%" class="${ratingClass(r.value)}"></i></div><b class="${ratingClass(r.value)}">${r.value ?? "-"}</b></div>`).join("");
    const s = c.season;
    const line = s ? (c.position === "G" ? `${s.gp} GP · ${s.sv_pct != null ? s.sv_pct.toFixed(3) : "-"} SV%` : `${s.gp} GP · ${s.g} G · ${s.a} A · ${s.g + s.a} P · ${s.sog} SOG · ${s.toi} min`) : "no games this season";
    Modal.open(`<div class="card-head"><div class="card-face">${portrait(id, c.team_abbr || c.team, c.position, 64)}</div><div><div class="card-name">${esc(c.name)}</div>
        <div class="muted">${esc(c.team)} · age ${c.age ?? "-"} · ${esc(c.nationality || "")}</div></div>
        <div class="card-val"><b>${c.value}</b><span>value</span></div></div>
      <div class="card-grid"><div><h4>This season</h4><p>${line}</p>
        ${c.last ? `<p class="muted">Last full season: ${c.last.gp} GP, ${c.last.g}-${c.last.a}</p>` : ""}
        <h4>Contract</h4><p>${c.contract ? `${mil(c.contract.cap_hit)} through ${c.contract.ends}${c.contract.no_trade ? ' <span class="tag">no-trade</span>' : ""}` : "none"}</p>
        ${c.fair3 ? `<p class="muted">Fair value on a 3-year deal: ${mil(c.fair3)}</p>` : ""}</div>
        <div><h4>Ratings</h4>${rat}</div></div>
      <div class="row card-actions"><a class="btn primary" href="#player/${c.player_id}" onclick="Modal.close()">Full profile</a>
        ${c.mine || c.team === "Free agent" ? `<button data-talks="${c.player_id}">Contract talks</button>` : ""}</div>`, "card");
  },
};

/* ================================================================ contract talks */
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-talks]");
  if (!b) return;
  e.preventDefault();
  Talks.open(+b.dataset.talks);
});
const Talks = {
  pid: null, years: null, aav: null, ntc: false,
  async open(pid) {
    this.pid = pid;
    Modal.open('<p class="muted">Calling his agent...</p>', "talks");
    const pre = await api("negotiation", {id: pid});
    if (pre.blocked) return this.render(pre);
    if (!pre.open && !(pre.status === "agreed")) {
      const r = await quietCmd(`negotiate ${pid}`);
      if (!r.ok) { this.render(Object.assign(pre, {blocked: r.output.replace(/^Error:\s*/, "")})); return; }
    }
    this.render(await api("negotiation", {id: pid}));
    Modal.onclose = () => refresh();
  },
  render(v) {
    const ag = v.agent;
    const initials = ag.name.split(" ").map((x) => x[0]).join("");
    const left = `<div class="tk-agent"><div class="tk-avatar">${esc(initials)}</div><div><b>${esc(ag.name)}</b><div class="muted">${esc(ag.agency)}</div>
        <span class="tag">${esc(ag.style_label)}</span></div></div>
      <div class="tk-player"><div class="card-name">${esc(v.name)}</div><div class="muted">${esc(v.position)} · age ${v.age} · value ${v.value}</div>
        ${v.current ? `<p>Now: ${mil(v.current.cap_hit)} through ${v.current.ends}</p>` : v.kind === "sign" ? "<p>Free agent</p>" : ""}</div>`;
    const log = (v.log || []).map((e) => `<div class="bub ${e.who}"><div class="who">${e.who === "you" ? "You" : e.who === "agent" ? esc(ag.name) : esc(v.name)}</div>${esc(e.text)}</div>`).join("");
    if (v.blocked && v.status !== "agreed") {
      Modal.open(`<div class="tk">${left}<div class="tk-main"><h3>No talks</h3><p>${esc(v.blocked)}</p>
        ${done ? `<p class="tk-sum">${esc(v.name)} is signed. You can see the new contract on his profile (Contract tab) and in Contracts and Cap.</p>` : ""}
        <div class="tk-log">${log}</div><p class="row"><button class="primary" onclick="Modal.close()">Close</button>
        ${done ? `<a class="btn" href="#player/${v.player_id}/contract" onclick="Modal.close()">His contract</a>` : ""}</p></div></div>`, "talks");
      return;
    }
    if (!v.open) {
      const done = v.status === "agreed";
      Modal.open(`<div class="tk">${left}<div class="tk-main"><div class="tk-banner ${done ? "pos" : "neg"}">${done ? "DEAL DONE" : v.status === "broken" ? `TALKS BROKEN OFF${v.cooldown_until ? " until " + esc(v.cooldown_until) : ""}` : "TALKS ENDED"}</div>
        <div class="tk-log">${log}</div><p class="row"><button class="primary" onclick="Modal.close()">Close</button>
        ${!done && v.status !== "broken" ? `<button data-talks="${v.player_id}">Reopen talks</button>` : ""}</p></div></div>`, "talks");
      return;
    }
    const pref = v.pref_years;
    this.years = this.years && this.years <= v.max_term ? this.years : pref;
    const asks = this.ntc && v.asks_ntc ? v.asks_ntc : v.asks;
    const ask = asks[this.years];
    this.aav = this.aav || Math.round(ask * 0.9 / 25000) * 25000;
    const pips = Array.from({length: v.max_patience}, (_, i) => `<i class="${i < v.patience ? "on" : ""}"></i>`).join("");
    const mood = v.mood >= 65 ? "warm" : v.mood >= 50 ? "neutral" : v.mood >= 40 ? "cool" : "frosty";
    const terms = Object.entries(asks).map(([y, a]) => `<button class="term${+y === this.years ? " on" : ""}${+y === pref ? " pref" : ""}" data-y="${y}"><b>${y} yr</b><span>${mil(a)}</span></button>`).join("");
    const fair = v.fair && v.fair[this.years];
    Modal.open(`<div class="tk">${left}
        <div class="tk-meters"><div>Patience <span class="pips">${pips}</span></div><div>Mood <b class="mood ${mood}">${mood}</b> ${bar(v.mood)}</div></div>
        <div class="tk-wants"><h4>What matters to him</h4>${v.wants.map((w) => `<span class="chip">${esc(w.text)}</span>`).join("")}</div>
      <div class="tk-main"><div class="tk-log" id="tk-log">${log}</div>
        <div class="tk-offer"><div class="tk-terms">${terms}</div>
          <div class="row"><label>AAV <input id="tk-aav" type="range" min="${Math.round(ask * 0.5 / 25000) * 25000}" max="${Math.round(ask * 1.3 / 25000) * 25000}" step="25000" value="${this.aav}"></label>
            <input id="tk-aav-n" class="tk-num" value="${(this.aav / 1e6).toFixed(3)}">M
            ${v.wants_ntc ? `<label class="chk"><input type="checkbox" id="tk-ntc"${this.ntc ? " checked" : ""}> no-trade clause</label>` : ""}</div>
          <p class="muted">His ask at ${this.years} years: <b>${mil(ask)}</b>${fair ? ` · our analysts' fair value: ${mil(fair)}` : ""} · round ${v.rounds + 1}</p>
          <p class="row"><button class="primary" id="tk-go">Make offer</button> <button id="tk-meet">Offer his ask</button>
            <span class="spacer"></span><button class="danger" id="tk-walk">Walk away</button></p></div></div></div>`, "talks");
    const box = $("#tk-log"); box.scrollTop = box.scrollHeight;
    const slider = $("#tk-aav"), num = $("#tk-aav-n");
    slider.oninput = () => { this.aav = +slider.value; num.value = (this.aav / 1e6).toFixed(3); };
    num.onchange = () => { const x = parseFloat(num.value); if (!isNaN(x)) { this.aav = Math.round(x * 1e6); slider.value = this.aav; } };
    document.querySelectorAll(".tk-terms .term").forEach((b) => b.onclick = () => { this.years = +b.dataset.y; this.render(v); });
    const ntc = $("#tk-ntc"); if (ntc) ntc.onchange = () => { this.ntc = ntc.checked; this.render(v); };
    $("#tk-meet").onclick = () => { this.aav = ask; this.send(); };
    $("#tk-go").onclick = () => this.send();
    $("#tk-walk").onclick = async () => { await quietCmd(`endtalks ${this.pid}`); this.render(await api("negotiation", {id: this.pid})); };
  },
  async send() {
    const box = $("#tk-log");
    box.insertAdjacentHTML("beforeend", `<div class="bub you"><div class="who">You</div>${this.years} yr x ${mil(this.aav)}${this.ntc ? " with a no-trade clause" : ""}</div><div class="bub agent typing"><i></i><i></i><i></i></div>`);
    box.scrollTop = box.scrollHeight;
    document.querySelectorAll(".tk-offer button").forEach((b) => b.disabled = true);
    const r = await quietCmd(`propose ${this.pid} ${Math.round(this.aav)} ${this.years}${this.ntc ? " ntc" : ""}`);
    await new Promise((res) => setTimeout(res, 650));
    if (!r.ok) toast(r.output, true);
    this.render(await api("negotiation", {id: this.pid}));
  },
};

/* ================================================================ the sim centre */
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-sim]");
  if (!b) return;
  e.preventDefault();
  Sim.start(b.dataset.sim);
});
const PACES = [["Watch", 1.6], ["Normal", 0.6], ["Fast", 0.15], ["Instant", 0]];
const Sim = {
  open: false, running: false, since: 0, timer: null, last: null, lastMine: null, scores: [], news: [], alerts: [],
  pace() { try { const v = localStorage.getItem("simPace"); if (v != null) return +v; } catch (e) { /* private window */ } return typeof SETTINGS !== "undefined" ? +SETTINGS.sim_pace : 0.6; },
  async start(mode) {
    try { await post("/api/sim", {mode, pace: this.pace()}); }
    catch (err) { return toast(err.message, true); }
    this.attach(mode);
  },
  attach(mode) {
    Object.assign(this, {open: true, running: true, since: 0, last: null, lastMine: null, scores: [], news: [], alerts: [], mode, tickAt: 0});
    const el = $("#simcentre");
    el.hidden = false;
    ["sc-goto", "sc-day", "sc-next"].forEach((x) => { const b = document.getElementById(x); if (b) b.remove(); });
    el.innerHTML = `<div class="sc-top"><div class="sc-brand"><i class="live-dot"></i>SIM <em>CENTRE</em></div>
        <div class="sc-date" id="sc-date">-</div><div class="sc-prog"><i id="sc-bar"></i></div><div id="sc-count" class="sc-count"></div>
        <div class="sc-pace">${PACES.map(([l, v]) => `<button data-pace="${v}" class="${Math.abs(v - this.pace()) < 1e-6 ? "on" : ""}">${l}</button>`).join("")}</div>
        <button id="sc-stop" class="sc-stop">STOP</button></div>
      <div class="sc-main"><section class="sc-col"><h3>Scores</h3><div id="sc-scores" class="sc-scores"></div></section>
        <section class="sc-col sc-center"><div id="sc-box"><div class="sc-empty">Waiting for the first games...</div></div></section>
        <section class="sc-col"><h3 id="sc-st-title">Standings</h3><div id="sc-stand"></div><h3>Your club</h3><ul id="sc-alerts" class="sc-alerts"></ul></section></div>
      <div class="sc-ticker news"><span class="lab">NEWS</span><div class="track"><div id="sc-news" class="run"></div></div></div>
      <div class="sc-ticker scores"><span class="lab">SCORES</span><div class="track"><div id="sc-tick" class="run"></div></div></div>`;
    el.querySelectorAll("[data-pace]").forEach((b) => b.onclick = async () => {
      try { localStorage.setItem("simPace", b.dataset.pace); } catch (e) { /* private window */ }
      el.querySelectorAll("[data-pace]").forEach((x) => x.classList.toggle("on", x === b));
      await post("/api/simpace", {pace: +b.dataset.pace}).catch(() => {});
    });
    $("#sc-stop").onclick = () => this.running ? post("/api/simstop").then(() => { $("#sc-stop").textContent = "STOPPING..."; }) : this.close();
    clearInterval(this.timer);
    this.timer = setInterval(() => this.poll(), 350);
    this.poll();
  },
  async poll() {
    let s;
    try { s = await (await fetch(`/api/simstatus?since=${this.since}`)).json(); } catch (e) { return; }
    this.since = s.next;
    for (const d of s.feed) this.day(d);
    const n = s.target_days;
    $("#sc-bar").style.width = n ? `${Math.min(100, s.done_days / n * 100)}%` : (s.running ? "50%" : "100%");
    $("#sc-count").textContent = `${s.done_days} day${s.done_days === 1 ? "" : "s"}${n && s.mode !== "day" ? ` of ~${n}` : ""}`;
    this.running = s.running;
    if (!s.running) {
      clearInterval(this.timer);
      const why = s.error ? `Stopped by an error: ${s.error}` : s.finished ? "Season complete" : s.stop_reason ? `Stopped: ${s.stop_reason}` : s.stopped ? "Stopped" : "Done";
      if (s.stop_reason && !$("#sc-goto")) {          // v38 (#24): why it stopped, and a way straight there
        const m = /\(([^)]+)\)\s*$/.exec(s.stop_reason);
        const where = m ? {"Inbox": "#inbox", "Press room": "#press", "Trade screen": "#trade"}[m[1]] : null;
        if (where) $("#sc-stop").insertAdjacentHTML("beforebegin", `<button id="sc-goto" class="sc-go primary">Go to the ${esc(m[1].toLowerCase())}</button>`);
        const g = $("#sc-goto"); if (g) g.onclick = () => { this.close(); location.hash = where; };
      }
      $("#sc-stop").textContent = "CLOSE";
      $("#sc-stop").classList.add("done");
      document.querySelector("#simcentre .sc-top").classList.add("stopped");     // v42 (register v39 #11): room for the buttons
      if (!s.finished && !$("#sc-next") && STATE && STATE.phase === "regular_season") {   // carry on without leaving the sim centre
        $("#sc-stop").insertAdjacentHTML("beforebegin", '<button id="sc-day" class="sc-go">Continue one day</button><button id="sc-next" class="sc-go primary">Continue to next game</button>');
        $("#sc-day").onclick = () => this.start("day");
        $("#sc-next").onclick = () => this.start("next");
      }
      $("#sc-date").insertAdjacentHTML("beforeend", ` <span class="sc-state">${esc(why)}</span>`);
      if (s.lines && s.lines.length && !s.finished) {
        const ul = $("#sc-alerts");
        if (!ul.children.length) ul.innerHTML = s.lines.map((l) => `<li>${esc(l)}</li>`).join("");
      }
    }
  },
  day(d) {
    this.last = d;
    $("#sc-date").textContent = new Date(d.day + "T12:00:00").toLocaleDateString(undefined, {weekday: "short", month: "short", day: "numeric", year: "numeric"});
    $("#sc-scores").innerHTML = d.scores.length ? d.scores.map((g) => `<a class="sc-game${g.mine ? " mine" : ""}" href="#game/${g.game_id}" onclick="Sim.open && !Sim.running && Sim.close()">
        <span class="st">FINAL${g.ot ? " " + g.ot : ""}</span><div class="ln${g.ag > g.hg ? " win" : ""}"><b>${esc(g.away)}</b><b>${g.ag}</b></div>
        <div class="ln${g.hg > g.ag ? " win" : ""}"><b>${esc(g.home)}</b><b>${g.hg}</b></div></a>`).join("") : '<div class="sc-empty">No games today.</div>';
    if (d.mine) { this.lastMine = d.mine; this.box(d.mine, true); }
    else if (this.lastMine) this.box(this.lastMine, false);
    if (d.standings) this.stand(d.standings);
    const dd = new Date(d.day + "T12:00:00").toLocaleDateString("en-GB", {day: "numeric", month: "short"});
    for (const g of d.scores) this.scores.unshift(`<span class="${g.mine ? "mine" : ""}"><em class="tk-d">${esc(dd)}</em> ${esc(g.away)} ${g.ag} <i>@</i> ${esc(g.home)} ${g.hg}${g.ot ? " " + g.ot : ""}</span>`);
    this.scores = this.scores.slice(0, 40);
    for (const n of d.news) this.news.unshift(`<span class="${n.mine ? "mine" : ""}"><em class="tk-d">${esc(dd)}</em> <b>${esc(n.type.replace(/_/g, " ").toLowerCase())}</b> ${esc(n.text)}</span>`);
    this.news = this.news.slice(0, 30);
    const now = Date.now();
    if (!this.tickAt || now - this.tickAt > 15000 || !this.running) {      // refresh the tickers now and then, so they scroll
      this.tickAt = now;
      $("#sc-tick").innerHTML = this.scores.join("");
      $("#sc-news").innerHTML = this.news.join("") || "<span>Quiet around the league.</span>";
    }
    if (d.alerts.length) $("#sc-alerts").insertAdjacentHTML("afterbegin", d.alerts.map((a) => `<li><span class="date">${esc(d.day)}</span>${esc(a)}</li>`).join(""));
    if (d.champion) $("#sc-box").innerHTML = `<div class="sc-champ"><div>STANLEY CUP CHAMPIONS</div><b>${esc(d.champion)}</b>
      <p><a class="btn primary" href="#champions" onclick="Sim.close()">The champions</a> <a class="btn" href="#awards" onclick="Sim.close()">Awards night</a> <a class="btn" href="#playoffs" onclick="Sim.close()">The bracket</a></p></div>`;
    if (d.press && d.press.length) $("#sc-alerts").insertAdjacentHTML("afterbegin", `<li><a href="#press" onclick="Sim.running || Sim.close()">Press conference waiting: ${esc(d.press.join(", ").replace(/_/g, " "))}</a></li>`);
  },
  box(b, fresh) {
    const mine = b.mine_home ? b.home : b.away;
    const won = (b.mine_home ? b.home_goals > b.away_goals : b.away_goals > b.home_goals);
    const tm = (ab, g, side) => `<div class="sb-t ${side}${(side === "home") === b.mine_home ? " me" : ""}"><span class="ab">${esc(ab)}</span><span class="g">${g}</span></div>`;
    const sk = (tid) => (b.skaters[tid] || []).map((s) => `<tr><td>${clink(s.player_id, s.name)}</td><td class="num">${s.g}</td><td class="num">${s.a}</td><td class="num">${s.sog}</td></tr>`).join("");
    $("#sc-box").innerHTML = `<div class="sc-flash${fresh ? " in" : ""}"><div class="sc-label">${fresh ? "YOUR GAME" : "LAST GAME"} · ${won ? "WIN" : b.ot ? b.ot + " LOSS" : "LOSS"}</div>
      <div class="sc-board">${tm(b.away, b.away_goals, "away")}<div class="sb-mid">FINAL${b.ot ? "<br>" + esc(b.ot) : ""}</div>${tm(b.home, b.home_goals, "home")}</div>
      <div class="sc-head">${esc(b.headline)}</div><p class="sc-lede">${esc(b.lede)}</p>
      <div class="sc-cols"><div><h4>Scoring</h4><ul class="sc-goals">${b.goals.map((g) => `<li><span>${esc(g.period)} ${esc(g.time)}</span> <b>${esc(g.team)}</b> ${esc(g.scorer)}${g.en ? " (EN)" : ""} <i>${esc(g.score)}</i></li>`).join("") || "<li>No goals.</li>"}</ul>
        <h4>Three stars</h4><ol class="sc-stars">${b.stars.map((s) => `<li>${clink(s.player_id, s.name)} <span>${esc(s.line)}</span></li>`).join("")}</ol></div>
        <div><h4>${esc(b.away)}</h4><table class="sc-sk"><tr><th></th><th class="num">G</th><th class="num">A</th><th class="num">SOG</th></tr>${sk(b.away_id)}</table>
          <h4>${esc(b.home)}</h4><table class="sc-sk"><tr><th></th><th class="num">G</th><th class="num">A</th><th class="num">SOG</th></tr>${sk(b.home_id)}</table></div></div>
      <p><a class="btn" href="#game/${b.game_id}" onclick="Sim.running || Sim.close()">Full recap &amp; replay</a></p></div>`;
  },
  stand(st) {
    const g = st.groups[0];
    if (!g) return;
    $("#sc-st-title").textContent = g.title;
    $("#sc-stand").innerHTML = `<table class="sc-st sc-st-h"><tr><td></td><td>Team</td><td class="num">GP</td><td class="num pts">PTS</td><td class="num">STRK</td></tr></table>` + g.sections.map((sec) => `${sec.title ? `<div class="sc-sec">${esc(sec.title)}</div>` : ""}<table class="sc-st">${sec.rows.map((r, i) =>
      `<tr class="${r.mine ? "mine" : ""}${sec.cut && i === sec.cut - 1 ? " cut" : ""}"><td>${i + 1}</td><td><b>${esc(r.abbr)}</b></td><td class="num">${r.gp}</td><td class="num pts">${r.pts}</td><td class="num">${r.streak}</td></tr>`).join("")}</table>`).join("");
  },
  close() {
    clearInterval(this.timer);
    this.open = false;
    $("#simcentre").hidden = true;
    $("#simcentre").innerHTML = "";
    refresh();
  },
};

/* ================================================================ saves and the title screen */
$("#tb-menu").addEventListener("click", () => Saves.menu());
const Saves = {
  async menu() {
    const d = await (await fetch("/api/saves")).json();
    if (!d.enabled) {
      Modal.open(`<h3>Saves</h3><p>This server was started with a single save (${esc(d.current || "")}); it saves as you play.
        Start it with <code>--saves &lt;folder&gt; --template &lt;world.db&gt;</code> (the launchers do) to get save slots, new careers and a title screen.</p>`, "saves");
      return;
    }
    Modal.open(`<h3>Saves</h3><p class="muted">The game saves as you play: every move and every simulated day is written to
        <b>${esc(d.current)}</b>. "Save as" keeps a copy you can come back to.</p>
      <div class="row"><input id="sv-name" placeholder="Name for the copy" value="${esc(d.current)} ${esc(STATE.date || "")}">
        <label class="chk"><input type="checkbox" id="sv-switch"> keep playing in the copy</label><button class="primary" id="sv-go">Save as</button></div>
      <h4>Your careers</h4>${this.list(d)}
      <p class="row"><button id="sv-new">New career...</button> <button id="sv-title">Main menu</button></p>`, "saves");
    $("#sv-go").onclick = async () => {
      try { const r = await post("/api/save", {action: "saveas", name: $("#sv-name").value, switch: $("#sv-switch").checked}); toast(r.output); Modal.close(); refresh(); }
      catch (e) { toast(e.message, true); }
    };
    $("#sv-new").onclick = () => { Modal.close(); Title.show("new"); };
    $("#sv-title").onclick = async () => { await post("/api/save", {action: "close"}); Modal.close(); refresh(); };
    this.wire(d);
  },
  list(d) {
    return `<div class="saves">${d.saves.map((s) => `<div class="save${s.current ? " current" : ""}"><div class="sv-team">${esc(s.team || "?")}</div>
      <div class="sv-info"><b>${esc(s.name)}</b><div class="muted">${esc(s.team_name || "no game")}${s.date ? " · " + esc(s.date) : ""}${s.record ? " · " + esc(s.record) : ""}</div>
      <div class="muted small">saved ${esc(s.modified.replace("T", " "))}</div></div>
      <div class="sv-act">${s.current ? '<span class="tag pos">playing</span>' : `<button class="primary" data-load="${esc(s.name)}">Load</button>
        <button data-rename="${esc(s.name)}">Rename</button> <button class="danger" data-del="${esc(s.name)}">Delete</button>`}</div></div>`).join("") || '<p class="muted">No saves yet.</p>'}</div>`;
  },
  wire(d, after) {
    const done = async (body, msg) => {
      try { const r = await post("/api/save", body); toast(msg || r.output); Modal.close(); $("#title").hidden = true; await refresh(); if (after) after(); }
      catch (e) { toast(e.message, true); }
    };
    document.querySelectorAll("[data-load]").forEach((b) => b.onclick = () => done({action: "load", name: b.dataset.load}));
    document.querySelectorAll("[data-del]").forEach((b) => b.onclick = async () => {
      if (!(await ask(`Delete ${b.dataset.del}? This cannot be undone.`, {ok: "Delete", danger: true}))) return;
      try { await post("/api/save", {action: "delete", name: b.dataset.del}); toast("Deleted."); b.closest(".save").remove(); } catch (e) { toast(e.message, true); }
    });
    document.querySelectorAll("[data-rename]").forEach((b) => b.onclick = async () => {
      const to = await ask("New name for the save", {input: b.dataset.rename, ok: "Rename"});
      if (!to) return;
      try { await post("/api/save", {action: "rename", name: b.dataset.rename, to}); toast("Renamed."); Title.visible() ? Title.show("load") : Saves.menu(); } catch (e) { toast(e.message, true); }
    });
  },
};
const Title = {
  visible() { return !$("#title").hidden; },
  async show(page = "home") {
    const d = await (await fetch("/api/saves")).json();
    const el = $("#title");
    el.hidden = false;
    if (!d.enabled) {
      el.innerHTML = `<div class="ts-card"><h1>HOCKEY <em>MANAGER</em></h1><p>No save is open. Start the server with a save, or with
        <code>--saves saves --template save/hockey_2025.db</code> for save slots.</p></div>`;
      return;
    }
    const latest = d.saves[0];
    const head = `<div class="ts-brand"><i class="live-dot"></i>HOCKEY <em>MANAGER</em></div>`;
    if (page === "new") {
      const byDiv = {};
      d.teams.forEach((t) => (byDiv[`${t.conference} · ${t.division}`] = byDiv[`${t.conference} · ${t.division}`] || []).push(t));
      el.innerHTML = `<div class="ts-wrap">${head}<div class="ts-panel"><h2>New career</h2><p class="muted">Pick the club you will run. The world is the 2025-26 season; the owner, staff and roster come with the job.</p>
        <div class="ts-divs">${Object.entries(byDiv).map(([k, ts]) => `<div class="ts-div"><h4>${esc(k)}</h4>${ts.map((t) => `<button class="ts-team" data-team="${esc(t.abbr)}"><b>${esc(t.abbr)}</b> ${esc(t.name)}</button>`).join("")}</div>`).join("")}</div>
        <div class="row ts-form"><label>Save name <input id="ts-name" placeholder="e.g. MTL career"></label><label>Seed <input id="ts-seed" size="6" value="${Math.floor(Math.random() * 9000) + 1000}"></label>
          <button class="primary big-btn" id="ts-start" disabled>Start career</button> <button id="ts-back">Back</button></div></div></div>`;
      let team = null;
      el.querySelectorAll(".ts-team").forEach((b) => b.onclick = () => {
        team = b.dataset.team;
        el.querySelectorAll(".ts-team").forEach((x) => x.classList.toggle("on", x === b));
        if (!$("#ts-name").value || /career$/.test($("#ts-name").value)) $("#ts-name").value = `${team} career`;
        $("#ts-start").disabled = false;
      });
      $("#ts-back").onclick = () => this.show();
      $("#ts-start").onclick = async () => {
        $("#ts-start").disabled = true; $("#ts-start").textContent = "Building the league...";
        try { await post("/api/save", {action: "new", team, name: $("#ts-name").value, seed: +$("#ts-seed").value || 1}); el.hidden = true; location.hash = "#dashboard"; await refresh(); }
        catch (e) { toast(e.message, true); $("#ts-start").disabled = false; $("#ts-start").textContent = "Start career"; }
      };
      return;
    }
    if (page === "load") {
      el.innerHTML = `<div class="ts-wrap">${head}<div class="ts-panel"><h2>Load a career</h2>${Saves.list(d)}<p><button id="ts-back">Back</button></p></div></div>`;
      $("#ts-back").onclick = () => this.show();
      Saves.wire(d, () => { el.hidden = true; });
      return;
    }
    el.innerHTML = `<div class="ts-wrap">${head}<div class="ts-menu">
        ${latest ? `<button class="ts-big primary" id="ts-cont"><b>Continue</b><span>${esc(latest.name)} · ${esc(latest.team_name || "")}${latest.date ? " · " + esc(latest.date) : ""}${latest.record ? " · " + esc(latest.record) : ""}</span></button>` : ""}
        <button class="ts-big" id="ts-new"><b>New career</b><span>take over any club in the 2025-26 world</span></button>
        <button class="ts-big" id="ts-load"${d.saves.length ? "" : " disabled"}><b>Load career</b><span>${d.saves.length} save${d.saves.length === 1 ? "" : "s"} in ${esc(d.folder)}</span></button></div></div>`;
    if (latest) $("#ts-cont").onclick = async () => { await post("/api/save", {action: "load", name: latest.name}).catch((e) => toast(e.message, true)); el.hidden = true; refresh(); };
    $("#ts-new").onclick = () => this.show("new");
    $("#ts-load").onclick = () => this.show("load");
  },
};

/* ================================================================ standings (broadcast style) */
VIEWS.standings = async (mode = "wildcard") => {
  if (!["wildcard", "division", "league"].includes(mode)) mode = "wildcard";
  const d = await api("standings2", {mode});
  const tabs = `<div class="tabs">${[["wildcard", "Wild card"], ["division", "Divisions"], ["league", "League"]].map(([m, l]) => `<a class="btn${m === mode ? " active" : ""}" href="#standings/${m}">${l}</a>`).join(" ")}
    <span class="spacer"></span><a class="btn" href="#analytics/odds">Playoff odds</a></div>`;
  const ties = d.groups.some((g) => g.sections.some((s) => s.rows.some((r) => r.t)));
  const head = `<tr><th></th><th>Team</th><th class="num">GP</th><th class="num">W</th><th class="num">L</th><th class="num">OT</th>${ties ? '<th class="num">T</th>' : ""}<th class="num">PTS</th><th class="num">P%</th>
    <th class="num wide">RW</th><th class="num">ROW</th><th class="num">GF</th><th class="num">GA</th><th class="num">DIFF</th><th class="num">L10</th><th class="num">STRK</th><th class="num wide">HOME</th><th class="num wide">AWAY</th></tr>`;
  const row = (r, i, cut) => `<tr class="${r.mine ? "mine" : ""}${cut && i === cut - 1 ? " cut" : ""}"><td class="rk">${i + 1}</td>
    <td class="tm">${r.clinch ? `<span class="cl cl-${r.clinch}">${r.clinch}</span>` : ""}<span class="ab">${esc(r.abbr)}</span> <a class="bc-team" href="#team/${r.team_id}">${esc(r.nickname || r.name)}</a></td>
    <td class="num">${r.gp}</td><td class="num">${r.w}</td><td class="num">${r.l}</td><td class="num">${r.otl}</td>${ties ? `<td class="num">${r.t}</td>` : ""}
    <td class="num pts">${r.pts}</td><td class="num">${r.pct.toFixed(3).replace(/^0/, "")}</td><td class="num wide">${r.rw}</td><td class="num">${r.row}</td>
    <td class="num">${r.gf}</td><td class="num">${r.ga}</td><td class="num ${r.diff > 0 ? "up" : r.diff < 0 ? "down" : ""}">${sign(r.diff)}</td>
    <td class="num">${esc(r.l10)}</td><td class="num ${/^W/.test(r.streak) ? "up" : /^L/.test(r.streak) ? "down" : ""}">${esc(r.streak)}</td><td class="num wide">${esc(r.home)}</td><td class="num wide">${esc(r.away)}</td></tr>`;
  const groups = d.groups.map((g) => `<section class="bc-panel"><h2>${esc(g.title)}</h2><table class="bc-table">${head}${g.sections.map((s) =>
    (s.title ? `<tr class="sec"><td colspan="${ties ? 19 : 18}">${esc(s.title)}</td></tr>` : "") + s.rows.map((r, i) => row(r, i, s.cut)).join("")).join("")}</table></section>`).join("");
  const sub = {wildcard: `Division leaders${d.format === "division_wildcard" ? ` (top ${d.per_division}) + ${d.wildcards} wild cards per conference` : ""}`, division: `Top ${d.per_division || 3} in each division qualify`, league: "Every club, by the league's tiebreakers"}[mode];
  return tabs + `<div class="bc"><div class="bc-title">STANDINGS <em>${mode === "wildcard" ? "WILD CARD" : mode.toUpperCase()}</em><span>${esc(sub)} · ${yrs(d.season)}</span></div>
    <div class="bc-grid ${mode === "league" ? "one" : ""}">${groups}</div>
    <p class="bc-legend"><span class="cl cl-x">x</span> clinched a playoff spot <span class="cl cl-y">y</span> division <span class="cl cl-z">z</span> conference <span class="cl cl-p">p</span> best record <span class="cl cl-e">e</span> eliminated
    · the dashed line is the playoff cut · RW regulation wins, ROW regulation + overtime wins</p></div>`;
};

/* ================================================================ inbox (mail client) */
VIEWS.inbox = async (arg = "") => {
  const [folder = "all", sel = ""] = arg.split(":");
  const q = Inbox.q || "";
  const d = await api("inbox2", {folder, q});
  const cur = d.messages.find((m) => String(m.msg_id) === sel) || null;
  if (cur && !cur.read) { quietCmd(`read ${cur.msg_id}`).then(() => api("state").then((s) => { $("#tb-inbox").textContent = `Inbox${s.unread ? " (" + s.unread + ")" : ""}`; })); cur.read = true; }
  const folders = d.folders.map((f) => `<a class="mf${f.key === folder ? " on" : ""}" href="#inbox/${f.key}"><span>${esc(f.label)}</span>${f.key === "unread" ? (f.count ? `<b>${f.count}</b>` : "") : `<i>${f.count}</i>`}</a>`).join("");
  const list = d.messages.map((m) => `<a class="ml${m.read ? "" : " unread"}${cur && cur.msg_id === m.msg_id ? " on" : ""}" href="#inbox/${folder}:${m.msg_id}" style="--c:${m.colour}">
      <span class="av">${esc(m.sender[0])}</span><span class="mb"><span class="mh"><b>${esc(m.sender)}</b><span class="date">${esc(m.date)}</span></span>
      <span class="ms">${esc(m.subject)}</span><span class="mp">${esc(m.snippet)}</span></span></a>`).join("") || '<p class="muted pad">Nothing here.</p>';
  let read = '<div class="mr-empty"><div>&#9993;</div><p>Select a message to read it.</p></div>';
  if (cur) {
    const actions = [];
    const s = cur.subject.toLowerCase();
    if (s.includes("trade offer")) actions.push('<a class="btn primary" href="#trade">Open the trade screen</a>');
    if (s.includes("directive") || s.includes("board") || s.includes("urgent")) actions.push('<a class="btn primary" href="#board">Go to the board</a>');
    if (s.includes("meeting")) actions.push('<a class="btn primary" href="#dashboard">See who needs a meeting</a>');
    if (s.includes("qualifying") || s.includes("contract")) actions.push('<a class="btn primary" href="#offseason">Contract decisions</a>');
    if (s.includes("injury") || s.includes("recovered")) actions.push('<a class="btn" href="#roster">Roster</a> <a class="btn" href="#lines">Lines</a>');
    const idx = d.messages.findIndex((m) => m.msg_id === cur.msg_id);
    const prev = d.messages[idx - 1], next = d.messages[idx + 1];
    read = `<div class="mr-band" style="--c:${cur.colour}"><div class="kick">${esc(cur.sender)}</div><div class="subj">${esc(cur.subject)}</div></div>
      <div class="mr-meta"><span class="av" style="--c:${cur.colour}">${esc(cur.sender[0])}</span><div><b>${esc(cur.sender)}</b><div class="muted">to you · ${esc(cur.date)}</div></div>
        <span class="spacer"></span>${prev ? `<a class="btn" href="#inbox/${folder}:${prev.msg_id}" title="Newer">&#9650;</a>` : ""}${next ? `<a class="btn" href="#inbox/${folder}:${next.msg_id}" title="Older">&#9660;</a>` : ""}
        <button class="btn" id="mr-unread">Mark unread</button></div>
      <div class="mr-body">${mailBody(cur.body)}</div>
      ${actions.length ? `<div class="mr-actions">${actions.join(" ")}</div>` : ""}`;
    AFTER = () => { const b = $("#mr-unread"); if (b) b.onclick = async () => { await quietCmd(`read ${cur.msg_id} unread`); location.hash = `#inbox/${folder}`; }; };
  }
  setTimeout(() => {
    const s = $("#mail-q");
    if (s) s.onkeydown = (e) => { if (e.key === "Enter") { Inbox.q = s.value; render(); } };
  });
  return `<div class="mail"><aside class="mail-side"><div class="mail-brand"><div class="kick">FRONT OFFICE</div><div class="name">Inbox</div></div>${folders}
      <button class="mail-all" data-cmd="inbox">Mark all read</button></aside>
    <section class="mail-list"><div class="mail-search"><input id="mail-q" type="search" placeholder="Search mail" value="${esc(q)}"></div>${list}</section>
    <section class="mail-read">${read}</section></div>`;
};
const Inbox = {q: ""};

/* ================================================================ news archive */
const newsOrig = VIEWS.news;
VIEWS.news = async (arg = "headlines") => {
  if ((arg || "").startsWith("archive")) return NewsArchive.view(arg);
  const html = await newsOrig(arg);
  return html.replace(/(Power rankings<\/a>)/, '$1 <a class="btn" href="#news/archive">Archive</a>');
};
const NewsArchive = {
  state: {kind: "headlines", scope: "league", season: "", month: ""},
  async view() {
    const s = this.state;
    const d = await api("newsfeed", {kind: s.kind, scope: s.scope, season: s.season, month: s.month, offset: 0});
    const sel = (id, opts, cur) => `<select id="${id}">${opts.map(([v, l]) => `<option value="${esc(v)}"${String(v) === String(cur) ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
    const tabs = `<div class="tabs"><a class="btn" href="#news/headlines">Headlines</a> <a class="btn" href="#news/recaps">Game recaps</a> <a class="btn" href="#news/social">Social</a> <a class="btn" href="#news/power">Power rankings</a> <a class="btn active" href="#news/archive">Archive</a></div>`;
    const ctl = `<div class="row arch-ctl">Season ${sel("ar-season", d.seasons.map((y) => [y, yrs(y)]), d.season)}
      ${sel("ar-kind", d.kinds.map((k) => [k, k[0].toUpperCase() + k.slice(1)]), d.kind)} ${sel("ar-scope", [["league", "Whole league"], ["club", "Your club"]], d.scope)}
      <span class="muted">${d.total} stories</span></div>
      <div class="months"><button data-m="" class="${!d.month ? "on" : ""}">All</button>${d.months.slice().reverse().map((m) => `<button data-m="${m}" class="${m === d.month ? "on" : ""}">${new Date(m + "-15").toLocaleDateString(undefined, {month: "short", year: "2-digit"})}</button>`).join("")}</div>`;
    AFTER = () => {
      const upd = () => { Object.assign(s, {season: $("#ar-season").value, kind: $("#ar-kind").value, scope: $("#ar-scope").value}); render(); };
      ["#ar-season", "#ar-kind", "#ar-scope"].forEach((x) => $(x).onchange = upd);
      document.querySelectorAll(".months [data-m]").forEach((b) => b.onclick = () => { s.month = b.dataset.m; render(); });
      this.offset = d.items.length; this.total = d.total; this.d = d;
      const sentinel = $("#arch-more");
      if (!sentinel) return;
      const io = new IntersectionObserver(async (ents) => {
        if (!ents[0].isIntersecting || this.loading || this.offset >= this.total) return;
        this.loading = true;
        const more = await api("newsfeed", {kind: s.kind, scope: s.scope, season: d.season, month: s.month, offset: this.offset});
        this.offset += more.items.length;
        $("#arch-list").insertAdjacentHTML("beforeend", this.items(more.items, this.lastDate));
        if (this.offset >= this.total) { sentinel.textContent = "End of the archive."; io.disconnect(); }
        this.loading = false;
      }, {root: $("#view")});
      io.observe(sentinel);
    };
    this.lastDate = null;
    return tabs + panel("News archive", ctl + `<ul class="news arch" id="arch-list">${this.items(d.items)}</ul><p id="arch-more" class="muted">${d.items.length < d.total ? "Loading more as you scroll..." : d.total ? "End of the archive." : "Nothing in this period."}</p>`);
  },
  items(items) {
    let out = "";
    for (const it of items) {
      if (it.date !== this.lastDate) { out += `<li class="dhead">${new Date(it.date + "T12:00:00").toLocaleDateString(undefined, {weekday: "long", month: "long", day: "numeric", year: "numeric"})}</li>`; this.lastDate = it.date; }
      out += `<li class="${it.mine ? "mine" : ""}"><div class="meta"><span class="tag">${esc(it.tag)}</span> ${esc(it.team)}</div>
        ${it.headline ? `<div class="headline"><a href="#article/${it.event_id}">${esc(it.headline)}</a></div><div class="muted">${esc(it.text)}</div>` : `<div>${it.player_id ? clink(it.player_id, it.text) : esc(it.text)}</div>`}</li>`;
    }
    return out;
  },
};

/* ================================================================ three-team trades */
const tradeOrig = VIEWS.trade;
VIEWS.trade = async (team) => {
  const html = await tradeOrig(team);
  return html.replace('<div class="tabs">', '<div class="tabs"><a class="btn active" href="#trade">Two clubs</a> <a class="btn" href="#trade3">Three clubs</a> <span class="spacer"></span>');
};
VIEWS.trade3 = async (arg = "") => {
  const [a, b] = arg.split(":").map((x) => x ? +x : null);
  const base = await api("trade", a ? {team: a} : {});
  const POST = {contender: "contending", middle: "middle", seller: "rebuilding"};
  const opt = (sel, not) => `<option value="">choose</option>${base.teams.filter((t) => t.team_id !== not).map((t) => `<option value="${t.team_id}"${t.team_id === sel ? " selected" : ""}>${esc(t.abbr)} (${POST[t.posture]})</option>`).join("")}`;
  const top = `<div class="tabs"><a class="btn" href="#trade">Two clubs</a> <a class="btn active" href="#trade3">Three clubs</a> <span class="spacer"></span>
    <label>Club A <select id="t3-a">${opt(a, b)}</select></label> <label>Club B <select id="t3-b">${opt(b, a)}</select></label>
    ${base.window.open ? `<span class="muted">Deadline ${esc(base.deadline)}</span>` : `<span class="tag neg">${esc(base.window.why)}</span>`}</div>`;
  AFTER = () => {
    const go = () => { const x = $("#t3-a").value, y = $("#t3-b").value; location.hash = `trade3/${x}:${y}`; };
    $("#t3-a").onchange = go; $("#t3-b").onchange = go;
  };
  if (!a || !b) return top + panel("Three-team trade", `<p>Pick two clubs. Every asset you tick goes to one of the other two clubs; each AI club accepts if what it receives (from either club) is worth 105% of what it gives up, as in a two-club deal. A club can act as a facilitator, taking a contract and passing on a pick.</p>`);
  const bView = await api("trade", {team: b});
  const ab = {me: base.abbr, [a]: base.their_abbr, [b]: bView.their_abbr};
  const clubs = [["me", base.mine], [a, base.theirs], [b, bView.theirs]];
  const dests = (from) => ["me", a, b].filter((x) => String(x) !== String(from));
  const col = (from, assets) => {
    const sel = (key) => `<select class="t3-to" data-key="${key}" data-from="${from}"><option value="">stays</option>${dests(from).map((t) => `<option value="${t}">&rarr; ${esc(ab[t])}</option>`).join("")}</select>`;
    const rows = assets.players.map((p) => `<tr class="${p.moved ? "muted" : ""}"><td>${p.moved ? "" : sel(p.key)}</td><td>${clink(p.player_id, p.name)}${p.core ? ' <span class="tag">core</span>' : ""}${p.status === "prospect" ? ' <span class="tag">minors</span>' : ""}</td>
      <td>${esc(p.pos)}</td><td class="num">${p.age}</td><td class="num">${p.cap ? mil(p.cap) : "-"}</td><td class="num"><b>${p.value.toFixed(0)}</b></td></tr>`).join("");
    const picks = assets.picks.map((k) => `<tr><td>${sel(k.key)}</td><td colspan="4">${esc(k.label)}</td><td class="num">${k.value.toFixed(0)}</td></tr>`).join("");
    return `<div class="scroll tr-list"><table><tr><th>Send</th><th>Asset</th><th>Pos</th><th class="num">Age</th><th class="num">Cap</th><th class="num">Val</th></tr>${rows}${picks}</table></div>`;
  };
  const prevAfter = AFTER;
  AFTER = () => {
    prevAfter();
    const legs = () => [...document.querySelectorAll(".t3-to")].filter((s) => s.value).map((s) => ({key: s.dataset.key, from: s.dataset.from, to: s.value}));
    const box = $("#t3-eval");
    const evaluate = async () => {
      const L = legs();
      document.querySelectorAll(".t3-to").forEach((s) => s.closest("tr").classList.toggle("sel", !!s.value));
      if (!L.length) { box.innerHTML = '<p class="muted">Choose where each asset goes.</p>'; return; }
      const e = await api("tradeeval3", {a, b, legs: L.map((l) => `${l.key}>${l.to}`).join(",")});
      if (e.invalid) { box.innerHTML = `<p class="muted">${esc(e.invalid)}</p>`; return; }
      box.innerHTML = Object.values(e.clubs).map((c) => `<div class="t3-v"><b>${esc(c.abbr)}</b> <span class="tag ${c.accept ? "pos" : "neg"}">${c.accept ? "yes" : "no"}</span>
        ${c.ratio != null ? `${Math.round(c.ratio * 100)}% (want ${Math.round(c.need_ratio * 100)}%)` : ""}${bar(Math.min(100, (c.ratio == null ? 1 : c.ratio / c.need_ratio) * 50))}<p class="muted">${esc(c.why)}</p></div>`).join("")
        + `<p><span class="tag ${e.accept ? "pos" : "neg"}">${e.accept ? "both clubs would do it" : "not yet"}</span></p>`;
    };
    document.querySelectorAll(".t3-to").forEach((s) => s.addEventListener("change", evaluate));
    $("#t3-go").onclick = () => {
      const L = legs();
      if (!L.length) return toast("Choose where each asset goes.", true);
      const name = (x) => x === "me" ? "me" : ab[x];
      const groups = {};
      L.forEach((l) => { const k = `${name(l.from)}>${name(l.to)}`; (groups[k] = groups[k] || []).push(l.key); });
      cmd(`trade3 ${ab[a]} ${ab[b]}; ` + Object.entries(groups).map(([k, ks]) => `${k}: ${ks.join(", ")}`).join("; "));
    };
    $("#t3-clear").onclick = () => { document.querySelectorAll(".t3-to").forEach((s) => (s.value = "")); evaluate(); };
    evaluate();
  };
  return top + `<div class="grid g-trade3">${panel("Their verdicts", `<div class="t3-top"><div id="t3-eval" class="t3-evals"></div><div><p><button class="primary" id="t3-go">Propose</button> <button id="t3-clear">Clear</button></p>
      <p class="muted">Pick a destination for each asset. All or nothing: both clubs must say yes. No salary retention in three-team deals. Click a name for his card.</p></div></div>`)}
    ${clubs.map(([t, as]) => panel(t === "me" ? `${ab.me} (you)` : ab[t], col(t, as))).join("")}</div>`;
};

/* ================================================================ analytics (Plotly, bundled) */
let plotlyLoading = null;
function ensurePlotly() {
  if (window.Plotly) return Promise.resolve();
  if (!plotlyLoading) plotlyLoading = new Promise((res, rej) => {
    const s = document.createElement("script");
    s.src = "vendor/plotly-2.35.2.min.js"; s.onload = res; s.onerror = () => rej(new Error("Could not load the charting library."));
    document.head.appendChild(s);
  });
  return plotlyLoading;
}
const C = {blue: "#2f6fd6", cyan: "#00a8c8", mine: "#e0384b", grey: "#8a98ad", good: "#1f8a4c", bad: "#c0392b", amber: "#c98a12"};
function layout(extra = {}) {
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  const ink = dark ? "#d8e1ee" : "#14223b", grid = dark ? "#2d3a4f" : "#e3e8ef";
  return Object.assign({paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", font: {color: ink, family: "Segoe UI, system-ui, sans-serif", size: 12},
    margin: {l: 52, r: 16, t: 30, b: 44}, xaxis: {gridcolor: grid, zerolinecolor: grid}, yaxis: {gridcolor: grid, zerolinecolor: grid},
    legend: {orientation: "h", y: -0.2}, hoverlabel: {font: {family: "Segoe UI, sans-serif"}}}, extra);
}
const PCFG = {displaylogo: false, responsive: true, modeBarButtonsToRemove: ["lasso2d", "select2d"]};
function plot(id, data, lay) { Plotly.newPlot(id, data, layout(lay), PCFG); }
function rolling(xs, n) { return xs.map((_, i) => { const w = xs.slice(Math.max(0, i - n + 1), i + 1); return w.reduce((a, b) => a + b, 0) / w.length; }); }

VIEWS.analytics = async (arg = "teams") => {
  const [tab = "teams", team = ""] = arg.split(":");
  if (!STATE.record || !STATE.record.gp) return panel("Analytics", "<p>No games played yet this season. Analytics fill in as the season goes: sim a few days and come back.</p>");
  const [d] = await Promise.all([api("analytics", team ? {tab, team} : {tab}), ensurePlotly()]);
  const T = [["teams", "League"], ["team", "Team"], ["players", "Players & goalies"], ["contracts", "Contracts"], ["odds", "Playoff odds"]];
  const tabs = `<div class="tabs">${T.map(([k, l]) => `<a class="btn${k === tab ? " active" : ""}" href="#analytics/${k}">${l}</a>`).join(" ")}
    ${tab === "team" ? `<span class="spacer"></span><label>Club <select id="an-team">${d.teams.map((t) => `<option value="${t.team_id}"${t.team_id === d.team ? " selected" : ""}>${esc(t.abbr)}</option>`).join("")}</select></label>` : ""}
    <span class="spacer"></span><span class="muted">${yrs(d.season)} regular season · <a href="#" id="an-help">what these mean</a></span></div>`;
  const help = `<div class="gloss"><dl>
    <dt>Attempts (Corsi)</dt><dd>Shots on goal, misses and blocked shots. CF% is your share of all attempts while you play.</dd>
    <dt>xG</dt><dd>Expected goals: the chance each shot had of going in, added up.</dd>
    <dt>G-xG</dt><dd>Goals above expected: finishing, or luck.</dd>
    <dt>PDO</dt><dd>Shooting % plus save % (x1000). Far above 1000 is usually luck that fades.</dd>
    <dt>GSAx</dt><dd>Goals saved above expected: the xG a goalie faced minus the goals he allowed.</dd>
    <dt>Expected points</dt><dd>What a club's goal difference is usually worth in the standings (Pythagorean).</dd>
    <dt>Playoff odds</dt><dd>2,000 simulations of the rest of the schedule from each club's goal and xG difference.</dd></dl></div>`;
  let body = "", draw = () => {};
  if (tab === "teams") {
    const rows = d.rows;
    body = `<div class="grid g2">${panel("Process: expected goals for and against per game", '<div id="an1" class="chart"></div><p class="muted">Up and right is good: more chances created, fewer allowed. Bubble size is points.</p>')}
      ${panel("Luck: PDO and points against expectation", '<div id="an2" class="chart"></div>')}</div>` +
      panel("Team table", `<div class="scroll">${table(rows, [{key: "abbr", label: "Team", fmt: (r) => `<b>${esc(r.abbr)}</b>`}, {key: "gp", label: "GP", num: 1}, {key: "pts", label: "PTS", num: 1},
        {key: "exp_pts", label: "xPTS", num: 1}, {key: "luck", label: "PTS-xPTS", num: 1, fmt: (r) => sign(r.luck)}, {key: "gf", label: "GF", num: 1}, {key: "ga", label: "GA", num: 1},
        {key: "xgf", label: "xGF", num: 1}, {key: "xga", label: "xGA", num: 1}, {key: "xgf_pct", label: "xGF%", num: 1}, {key: "cf_pct", label: "CF%", num: 1},
        {key: "sh_pct", label: "SH%", num: 1}, {key: "sv_pct", label: "SV%", num: 1, fmt: (r) => r.sv_pct.toFixed(3)}, {key: "pdo", label: "PDO", num: 1}, {key: "g_minus_xg", label: "G-xG", num: 1, fmt: (r) => sign(r.g_minus_xg)}],
        {rowClass: (r) => r.team_id === d.me ? "mine" : ""})}</div>`);
    draw = () => {
      plot("an1", [{x: rows.map((r) => r.xgf_gp), y: rows.map((r) => r.xga_gp), text: rows.map((r) => r.abbr), mode: "markers+text", textposition: "top center",
        marker: {size: rows.map((r) => 8 + r.pts / 4), color: rows.map((r) => r.team_id === d.me ? C.mine : C.blue), opacity: .8}, hovertemplate: "%{text}<br>xGF/gp %{x}<br>xGA/gp %{y}<extra></extra>"}],
        {xaxis: {title: "xGF per game"}, yaxis: {title: "xGA per game (fewer is up)", autorange: "reversed"}, showlegend: false});
      const byPdo = rows.slice().sort((x, y) => y.pdo - x.pdo);
      plot("an2", [{type: "bar", x: byPdo.map((r) => r.abbr), y: byPdo.map((r) => r.pdo - 1000), name: "PDO - 1000", marker: {color: byPdo.map((r) => r.team_id === d.me ? C.mine : r.pdo >= 1000 ? C.amber : C.cyan)}},
        {type: "scatter", mode: "markers", x: byPdo.map((r) => r.abbr), y: byPdo.map((r) => r.luck), name: "points above expected", yaxis: "y2", marker: {color: C.grey, size: 8, symbol: "diamond"}}],
        {yaxis: {title: "PDO - 1000"}, yaxis2: {title: "PTS - xPTS", overlaying: "y", side: "right", showgrid: false}, xaxis: {tickangle: -60}});
    };
  } else if (tab === "team") {
    const g = d.games, r = d.row || {};
    const share = (f, a) => f.map((v, i) => (v + a[i]) ? 100 * v / (v + a[i]) : 50);
    body = `<div class="kpis">${[["Record pts", r.pts], ["xGF%", r.xgf_pct], ["CF%", r.cf_pct], ["PDO", r.pdo], ["G-xG", sign(r.g_minus_xg)], ["PTS vs expected", sign(r.luck)]].map(([l, v]) => `<div class="kpi"><span>${l}</span><b>${v ?? "-"}</b></div>`).join("")}</div>
      <div class="grid g2">${panel(`${esc(d.abbr)}: 10-game rolling shares`, '<div id="an3" class="chart"></div>')}${panel("Goals against expected goals, cumulative", '<div id="an4" class="chart"></div>')}
      ${panel("Shot quality: chances for and against", '<div id="an5" class="chart"></div><p class="muted">The distribution of each shot\'s goal chance. More shots on the right is better chances.</p>')}
      ${panel("Who drives the offence", '<div id="an6" class="chart"></div>')}</div>` +
      panel("Skaters", `<div class="scroll">${table(d.skaters, [{key: "name", label: "Player", fmt: (x) => clink(x.player_id, x.name)}, {key: "pos", label: "Pos"}, {key: "gp", label: "GP", num: 1},
        {key: "g", label: "G", num: 1}, {key: "a", label: "A", num: 1}, {key: "p", label: "P", num: 1}, {key: "toi_gp", label: "TOI", num: 1}, {key: "p60", label: "P/60", num: 1},
        {key: "sog", label: "SOG", num: 1}, {key: "icf", label: "iCF", num: 1}, {key: "ixg", label: "ixG", num: 1}, {key: "gax", label: "G-ixG", num: 1, fmt: (x) => sign(x.gax)}, {key: "sh_pct", label: "SH%", num: 1}])}</div>`);
    draw = () => {
      const x = g.map((z, i) => i + 1), lbl = g.map((z) => `${z.date} vs ${z.opp}`);
      plot("an3", [{x, y: rolling(share(g.map((z) => z.xgf), g.map((z) => z.xga)), 10), name: "xGF%", line: {color: C.blue, width: 3}, text: lbl},
        {x, y: rolling(share(g.map((z) => z.gf), g.map((z) => z.ga)), 10), name: "GF%", line: {color: C.mine, width: 2}, text: lbl},
        {x, y: rolling(share(g.map((z) => z.cf), g.map((z) => z.ca)), 10), name: "CF%", line: {color: C.grey, dash: "dot"}, text: lbl}],
        {xaxis: {title: "game"}, yaxis: {title: "%", range: [25, 75]}, shapes: [{type: "line", x0: 1, x1: Math.max(1, g.length), y0: 50, y1: 50, line: {color: C.grey, dash: "dash", width: 1}}]});
      let a = 0, b = 0, c = 0, e = 0;
      plot("an4", [{x, y: g.map((z) => (a += z.gf)), name: "goals for", line: {color: C.mine}}, {x, y: g.map((z) => (b += z.xgf)), name: "xG for", line: {color: C.mine, dash: "dot"}},
        {x, y: g.map((z) => (c += z.ga)), name: "goals against", line: {color: C.blue}}, {x, y: g.map((z) => (e += z.xga)), name: "xG against", line: {color: C.blue, dash: "dot"}}], {xaxis: {title: "game"}});
      plot("an5", [{type: "histogram", x: d.xg_for, name: "for", opacity: .65, marker: {color: C.mine}, xbins: {start: 0, end: .5, size: .01}, histnorm: "percent"},
        {type: "histogram", x: d.xg_against, name: "against", opacity: .55, marker: {color: C.blue}, xbins: {start: 0, end: .5, size: .01}, histnorm: "percent"}], {barmode: "overlay", xaxis: {title: "goal chance of the shot", range: [0, .4]}, yaxis: {title: "% of shots"}});
      const sk = d.skaters.filter((z) => z.p > 0).slice(0, 14);
      plot("an6", [{type: "bar", y: sk.map((z) => z.name), x: sk.map((z) => z.g), name: "goals", orientation: "h", marker: {color: C.mine}},
        {type: "bar", y: sk.map((z) => z.name), x: sk.map((z) => z.a), name: "assists", orientation: "h", marker: {color: C.blue}}], {barmode: "stack", yaxis: {autorange: "reversed"}, margin: {l: 130, r: 16, t: 20, b: 40}});
    };
    const prev = AFTER;
    AFTER = () => { if (prev) prev(); const s = $("#an-team"); if (s) s.onchange = () => { location.hash = `analytics/team:${s.value}`; }; };
  } else if (tab === "players") {
    const sk = d.skaters, gl = d.goalies;
    body = `<div class="grid g2">${panel("Finishing: goals against individual expected goals", '<div id="an7" class="chart"></div><p class="muted">Above the line: scoring more than his chances suggest (skill or a hot streak).</p>')}
      ${panel("Goalies: goals saved above expected", '<div id="an8" class="chart"></div>')}</div>` +
      `<div class="grid g2">${panel("Skaters (5+ games)", `<div class="scroll">${table(sk, [{key: "name", label: "Player", fmt: (x) => clink(x.player_id, x.name)}, {key: "team", label: "Tm"}, {key: "pos", label: "Pos"},
        {key: "gp", label: "GP", num: 1}, {key: "p", label: "P", num: 1}, {key: "g", label: "G", num: 1}, {key: "ixg", label: "ixG", num: 1}, {key: "gax", label: "G-ixG", num: 1, fmt: (x) => sign(x.gax)},
        {key: "p60", label: "P/60", num: 1}, {key: "ixg60", label: "ixG/60", num: 1}, {key: "icf", label: "iCF", num: 1}, {key: "sh_pct", label: "SH%", num: 1}, {key: "toi_gp", label: "TOI", num: 1}], {rowClass: (x) => x.team === STATE.abbr ? "mine" : ""})}</div>`)}
      ${panel("Goalies", `<div class="scroll">${table(gl, [{key: "name", label: "Goalie", fmt: (x) => clink(x.player_id, x.name)}, {key: "team", label: "Tm"}, {key: "gp", label: "GP", num: 1},
        {key: "sa", label: "SA", num: 1}, {key: "sv_pct", label: "SV%", num: 1, fmt: (x) => x.sv_pct.toFixed(3)}, {key: "ga", label: "GA", num: 1}, {key: "xga", label: "xGA", num: 1},
        {key: "gsax", label: "GSAx", num: 1, fmt: (x) => sign(x.gsax)}, {key: "gsax60", label: "GSAx/60", num: 1}], {rowClass: (x) => x.team === STATE.abbr ? "mine" : ""})}</div>`)}</div>`;
    draw = () => {
      const top = sk.slice().sort((x, y) => y.ixg - x.ixg).slice(0, 150);
      const mx = Math.max(1, ...top.map((x) => Math.max(x.ixg, x.g)));
      plot("an7", [{x: top.map((x) => x.ixg), y: top.map((x) => x.g), text: top.map((x) => `${x.name} (${x.team})`), mode: "markers", marker: {color: top.map((x) => x.team === STATE.abbr ? C.mine : C.blue), size: 8, opacity: .75},
        hovertemplate: "%{text}<br>ixG %{x}<br>goals %{y}<extra></extra>"}, {x: [0, mx], y: [0, mx], mode: "lines", line: {color: C.grey, dash: "dash"}, hoverinfo: "skip"}],
        {xaxis: {title: "individual xG"}, yaxis: {title: "goals"}, showlegend: false});
      const g2 = gl.slice(0, 25);
      plot("an8", [{type: "bar", x: g2.map((x) => x.name), y: g2.map((x) => x.gsax), marker: {color: g2.map((x) => x.team === STATE.abbr ? C.mine : x.gsax >= 0 ? C.good : C.bad)}, text: g2.map((x) => x.team), hovertemplate: "%{x} (%{text})<br>GSAx %{y}<extra></extra>"}],
        {xaxis: {tickangle: -55}, yaxis: {title: "GSAx"}, margin: {l: 52, r: 16, t: 20, b: 110}});
    };
  } else if (tab === "contracts") {
    const sk = d.skaters;
    body = panel("Cap hit against production (skaters, 10+ games)", '<div id="an9" class="chart tall"></div><p class="muted">Points per 82 games against this season\'s cap hit. Below and right of the cloud: paid more than he produces. Your players in red.</p>') +
      `<div class="grid g2">${panel("Most points per $1M", table(sk.slice(0, 25), [{key: "name", label: "Player", fmt: (x) => clink(x.player_id, x.name)}, {key: "team", label: "Tm"},
        {key: "cap", label: "Cap hit", num: 1, fmt: (x) => mil(x.cap)}, {key: "prod", label: "P/82", num: 1}, {key: "per_m", label: "P/82 per $1M", num: 1}]))}
        ${panel("Goalies: GSAx against cap hit", '<div id="an10" class="chart"></div>')}</div>`;
    draw = () => {
      plot("an9", [{x: sk.map((x) => x.cap / 1e6), y: sk.map((x) => x.prod), text: sk.map((x) => `${x.name} (${x.team})`), mode: "markers",
        marker: {color: sk.map((x) => x.team === STATE.abbr ? C.mine : x.pos === "D" ? C.cyan : C.blue), size: sk.map((x) => x.team === STATE.abbr ? 11 : 7), opacity: .75},
        hovertemplate: "%{text}<br>$%{x:.2f}M<br>%{y} P/82<extra></extra>"}], {xaxis: {title: "cap hit ($M)"}, yaxis: {title: "points per 82 games"}, showlegend: false});
      plot("an10", [{x: d.goalies.map((x) => x.cap / 1e6), y: d.goalies.map((x) => x.gsax), text: d.goalies.map((x) => `${x.name} (${x.team})`), mode: "markers",
        marker: {color: d.goalies.map((x) => x.team === STATE.abbr ? C.mine : C.blue), size: 10}, hovertemplate: "%{text}<br>$%{x:.2f}M<br>GSAx %{y}<extra></extra>"}],
        {xaxis: {title: "cap hit ($M)"}, yaxis: {title: "GSAx"}, showlegend: false});
    };
  } else if (tab === "odds") {
    const confs = [...new Set(d.rows.map((r) => r.conference))];
    body = `<p class="muted">${d.sims.toLocaleString()} simulations of the ${d.games_left} games left.</p><div class="grid g2">${confs.map((c, i) => panel(`${c} Conference`, `<div id="ao${i}" class="chart tall"></div>`)).join("")}</div>` +
      panel("Projection", table(d.rows, [{key: "abbr", label: "Team", fmt: (r) => `<b>${esc(r.abbr)}</b> ${esc(r.name)}`}, {key: "conference", label: "Conf"}, {key: "division", label: "Div"},
        {key: "pts", label: "PTS", num: 1}, {key: "proj", label: "Projected", num: 1}, {key: "playoffs", label: "Playoffs %", num: 1}, {key: "division_title", label: "Division %", num: 1}, {key: "strength", label: "Strength", num: 1}],
        {rowClass: (r) => r.mine ? "mine" : ""}));
    draw = () => confs.forEach((c, i) => {
      const rs = d.rows.filter((r) => r.conference === c).sort((x, y) => x.playoffs - y.playoffs);
      plot(`ao${i}`, [{type: "bar", orientation: "h", y: rs.map((r) => r.abbr), x: rs.map((r) => r.playoffs), text: rs.map((r) => `${r.playoffs}%  (${r.proj} pts)`), textposition: "auto",
        marker: {color: rs.map((r) => r.mine ? C.mine : r.playoffs >= 50 ? C.blue : C.grey)}, hovertemplate: "%{y}: %{x}%<extra></extra>"}], {xaxis: {range: [0, 100], title: "chance of making the playoffs (%)"}, margin: {l: 52, r: 16, t: 10, b: 44}});
    });
  }
  const prev = AFTER;
  AFTER = () => { if (prev) prev(); draw(); const h = $("#an-help"); if (h) h.onclick = (e) => { e.preventDefault(); Modal.open(`<div class="win-title">Analytics glossary</div><div class="pad">${help}</div><div class="win-buttons"><button class="primary" onclick="Modal.close()">Close</button></div>`, "win"); }; };
  return tabs + body;
};
