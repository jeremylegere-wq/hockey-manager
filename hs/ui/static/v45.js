/* v45: League > Expansion: new clubs, protection lists and the expansion draft (docs/EXPANSION.md). */

const XP = {sel: null, scheme: null};
VIEWS.expansion = async () => {
  const d = await api("expansion");
  const e = d.pending;
  const money = (v) => v == null ? "-" : "$" + (v / 1e6).toFixed(2) + "M";
  let parts = [];
  // status
  parts.push(panel("Expansion", `<p>${d.clubs} clubs in the league (limit ${d.max}). League expansion:
    <select id="xp-mode"><option value="occasional"${d.mode === "occasional" ? " selected" : ""}>occasional (the league may add a club)</option>
    <option value="off"${d.mode === "off" ? " selected" : ""}>off</option></select></p>
    ${e ? `<p><b>On the way: the ${esc(e.city)} ${esc(e.nickname)} (${esc(e.abbr)})</b>, ${esc(e.conference)} Conference, ${esc(e.division)} Division,
      first season ${ssn(e.first_season)}. ${e.status === "announced" ? "The club comes into being when this season ends; protection lists follow and the expansion draft is held when the entry draft phase opens." : "Protection lists are in; the expansion draft is held when the entry draft phase opens."}
      ${e.user_gm ? "<br>You will be (or are) its general manager." : ""}</p>` : ""}
    <p class="muted small">The rules are the NHL's for Vegas (2017) and Seattle (2021): each club protects 7 forwards, 3 defencemen and a goalie, or any 8 skaters and a goalie;
    no-movement clauses must be protected; first- and second-year pros are exempt; each club loses one player. The new club drafts with the third-worst club's lottery odds.</p>`));
  // create
  if (!e && d.state === "regular_season" && d.clubs < d.max && d.me) {
    const confs = d.conferences.map((c) => `<option>${esc(c)}</option>`).join("");
    parts.push(panel("Create a club", `<div class="xp-form">
      <label>Market <select id="xp-cand"><option value="">your own…</option>${d.candidates.map((c, i) => `<option value="${i}">${esc(c.city)} ${esc(c.nickname)}</option>`).join("")}</select></label>
      <label>City <input id="xp-city" maxlength="30"></label><label>Nickname <input id="xp-nick" maxlength="30"></label>
      <label>Abbreviation <input id="xp-abbr" maxlength="4" size="5"></label><label>Conference <select id="xp-conf">${confs}</select></label>
      <label class="chk"><input type="checkbox" id="xp-gm"> Become its general manager (you leave your club when this season ends)</label>
      <button class="btn primary" id="xp-go">Announce the club</button></div>
      <p class="muted small">It joins next season, in its conference's smallest division. It must be announced before the trade deadline.</p>`));
  }
  // protection list
  if (d.protect) {
    const pr = d.protect;
    XP.sel = XP.sel || new Set(pr.players);
    XP.scheme = XP.scheme || pr.scheme || "7-3-1";
    const rows = pr.pool.filter((x) => x.eligible || x.exempt || x.gp > 0).map((x) => {
      const tags = [x.exempt ? "exempt" : "", x.nmc ? "NMC" : "", !x.exempt && !x.eligible ? "not eligible" : "", x.qualifies && !x.exempt && x.group !== "G" ? "meets exposure" : ""].filter(Boolean).join(", ");
      return `<tr class="${x.exempt || !x.eligible ? "muted" : ""}"><td>${x.exempt || !x.eligible ? "" : `<input type="checkbox" class="xp-p" value="${x.player_id}"${XP.sel.has(x.player_id) ? " checked" : ""}>`}</td>
        <td>${clink(x.player_id, x.name)}</td><td>${esc(x.pos)}</td><td class="num">${x.gp}</td><td class="num">${x.value.toFixed(1)}</td><td class="small">${tags}</td></tr>`;
    }).join("");
    const n = {F: 0, D: 0, G: 0};
    pr.pool.forEach((x) => { if (XP.sel.has(x.player_id) && x.eligible) n[x.group]++; });
    parts.push(panel("Our protection list", `<div class="toolbar"><label>Scheme <select id="xp-scheme">
        <option value="7-3-1"${XP.scheme === "7-3-1" ? " selected" : ""}>7 F, 3 D, 1 G</option><option value="8-1"${XP.scheme === "8-1" ? " selected" : ""}>8 skaters, 1 G</option></select></label>
        <span class="xp-count">Protected: ${n.F} F, ${n.D} D, ${n.G} G</span><span class="spacer"></span>
        <button class="btn" id="xp-auto">Assistant's list</button> <button class="btn primary" id="xp-save">Submit list</button></div>
      ${pr.problems.length ? `<ul class="xp-warn">${pr.problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>` : `<p class="muted small">${pr.by_user ? "Your list is in." : "Your assistant's list is in; change it before the draft if you like."}</p>`}
      <table class="dv-t"><tr><th></th><th>Player</th><th>Pos</th><th class="num">GP</th><th class="num">Value</th><th></th></tr>${rows}</table>`));
  }
  // draft room (you run the expansion club)
  if (d.draft) {
    const sf = d.plan_shortfalls || {};
    const sfText = Object.entries(sf).map(([k, v]) => k === "pay_low" ? `payroll ${money(v)} under the floor` : k === "pay_high" ? `payroll ${money(v)} over the cap` : k === "under" ? `${v} more under contract` : `${v} more ${k}`).join("; ");
    parts.push(panel("Expansion draft", `<p class="muted small">One player from each club. Pick for yourself or leave a club to your staff (their choices keep the roster legal: 14 F, 9 D, 3 G, 20 under contract, payroll 60-100% of the cap).</p>
      ${sfText ? `<p class="xp-warn">With these picks the roster is short: ${esc(sfText)}.</p>` : `<p class="muted small">These picks make a legal roster.</p>`}
      <table class="dv-t"><tr><th>Club</th><th>Pick</th><th></th></tr>${d.draft.map((c) => `<tr><td>${esc(c.abbr)}</td>
        <td><select class="xp-pick" data-abbr="${esc(c.abbr)}"><option value="">${c.mine ? "(staff choice)" : "staff: " + esc(c.pick ? c.pick.name : "-")}</option>
          ${c.exposed.map((x) => `<option value="${x.player_id}"${c.mine && c.pick && c.pick.player_id === x.player_id ? " selected" : ""}>${esc(x.name)} (${x.pos}, ${x.value.toFixed(1)}${x.under ? "" : ", RFA"})</option>`).join("")}</select></td>
        <td class="small">${c.mine ? "yours" : ""}</td></tr>`).join("")}</table>`));
  }
  if (d.last_draft) {
    parts.push(panel(`The ${esc(d.last_draft.club)} expansion draft`, `<table class="dv-t"><tr><th>#</th><th>Player</th><th>Pos</th><th>From</th><th></th></tr>
      ${d.last_draft.picks.map((p, i) => `<tr><td>${i + 1}</td><td>${clink(p.player_id, p.name)}</td><td>${esc(p.pos)}</td><td>${esc(p.frm)}</td><td class="small muted">${esc(p.side || "")}</td></tr>`).join("")}</table>`));
  }
  if (d.history.length) {
    parts.push(panel("Expansion clubs", table(d.history, [{key: "club", label: "Club", fmt: (r) => esc(`${r.city} ${r.nickname} (${r.abbr})`)},
      {key: "first_season", label: "First season", fmt: (r) => ssn(r.first_season)}, {key: "status", label: "Status"}])));
  }
  AFTER = () => {
    const m = $("#xp-mode"); if (m) m.onchange = () => cmd(`expansion mode ${m.value}`).then(render);
    const cand = $("#xp-cand");
    if (cand) cand.onchange = () => {
      const c = d.candidates[+cand.value]; if (!c) return;
      $("#xp-city").value = c.city; $("#xp-nick").value = c.nickname; $("#xp-abbr").value = c.abbr;
      if (d.conferences.includes(c.conference)) $("#xp-conf").value = c.conference;
    };
    const go = $("#xp-go");
    if (go) go.onclick = async () => {
      const r = await cmd(`expansion create ${$("#xp-city").value} | ${$("#xp-nick").value} | ${$("#xp-abbr").value} | ${$("#xp-conf").value}${$("#xp-gm").checked ? " | gm" : ""}`);
      if (r.ok) render();
    };
    document.querySelectorAll(".xp-p").forEach((b) => b.onchange = () => { b.checked ? XP.sel.add(+b.value) : XP.sel.delete(+b.value); render(); });
    const sc = $("#xp-scheme"); if (sc) sc.onchange = () => { XP.scheme = sc.value; render(); };
    const au = $("#xp-auto"); if (au) au.onclick = async () => { const r = await cmd("expansion protect auto"); if (r.ok) { XP.sel = null; XP.scheme = null; render(); } };
    const sv = $("#xp-save"); if (sv) sv.onclick = async () => { const r = await cmd(`expansion protect ${XP.scheme} ${[...XP.sel].join(", ")}`); if (r.ok) { XP.sel = null; XP.scheme = null; render(); } };
    document.querySelectorAll(".xp-pick").forEach((s) => s.onchange = async () => {
      await cmd(s.value ? `expansion pick ${s.dataset.abbr} ${s.value}` : `expansion unpick ${s.dataset.abbr}`, {quiet: true}); render();
    });
  };
  return `<div class="xp">${parts.join("")}</div>`;
};
(() => {
  const lg = MENUS.find((m) => m[0] === "League")[1];
  const at = lg.findIndex((x) => Array.isArray(x) && x[0] === "World Leagues");
  lg.splice(at >= 0 ? at + 1 : lg.length, 0, ["Expansion", "#expansion"]);
  SCREEN_NAMES.expansion = "Expansion";
})();

/* v45: the Hall of Fame by Career Legacy Score (docs/HALL_OF_FAME.md): the ballot, the members, the CLS tracker and a
   player's breakdown (#hof/<player id>). */
const HF = {tab: "ballot", all: false};
VIEWS.hof = async (arg) => {
  if (arg) {
    const s = await api("legacy", {player: arg});
    const items = s.items.length ? `<table class="dv-t">${s.items.map((i) => `<tr><td>${esc(i.label)}</td><td class="num">+${i.pts}</td></tr>`).join("")}</table>` : '<p class="muted">No trophies, championships or milestones.</p>';
    const best = s.best.length ? `<table class="dv-t"><tr><th>Season</th><th class="num">SV</th></tr>${s.best.map((b) => `<tr><td>${ssn(b.season)}</td><td class="num">${b.sv.toFixed(2)}</td></tr>`).join("")}</table>` : '<p class="muted">No NHL seasons on file.</p>';
    return panel(`${esc(s.name)}: Career Legacy Score`, `<p class="hf-big"><b>${s.cls.toFixed(1)}</b> ${s.tier ? `<span class="tag pos">${esc(s.tier)}</span>` : ""}</p>
      <p>Peak (best seven seasons) ${s.peak.toFixed(2)} × 10 + longevity (the other ${Math.max(0, s.seasons - 7)} seasons) ${s.longevity.toFixed(2)} × 3 = ${s.pvl.toFixed(1)}; hardware ${s.hardware.toFixed(1)}.</p>
      <div class="hf-split"><div><h4>Best seasons (Season Value)</h4>${best}</div><div><h4>Hardware</h4>${items}</div></div>
      <p class="muted small">A Season Value of 1.0 is an average starter at his position that season; an MVP season is about 2.2-2.8. <a href="#hof">Back to the Hall of Fame</a></p>`);
  }
  const d = await api("hof");
  const tierTag = (t) => t ? `<span class="tag${t === "Hall of Very Good" ? "" : " pos"}">${esc(t)}</span>` : "";
  const cls = (r) => `<a href="#hof/${r.player_id}"><b>${(+r.score || +r.cls || 0).toFixed(1)}</b></a>`;
  let body;
  if (HF.tab === "ballot") {
    body = d.ballot.length ? table(d.ballot, [
      {key: "vote", label: d.open && d.mode === "committee" ? "Back" : "", fmt: (r) => d.open && d.mode === "committee" ? `<input type="checkbox" class="hof-v" value="${r.player_id}"${r.my_vote ? " checked" : ""}>` : (r.inducted ? '<span class="tag pos">inducted</span>' : "")},
      {key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "pos", label: "Pos"}, {key: "last", label: "Last season", num: true},
      {key: "score", label: "CLS", num: true, fmt: cls}, {key: "tier", label: "Tier", fmt: (r) => tierTag(r.tier)},
      {key: "ballot_years", label: "Year on ballot", num: true, fmt: (r) => `${r.ballot_years || 1} of ${d.ballot_life}`}, {key: "line", label: "Career"}])
      + (d.open && d.mode === "committee" ? `<div class="toolbar"><span class="muted">The best ${d.max} by CLS go in. Back up to ${d.max}: a candidate you back passes any unbacked candidate within 15 points. The class is named when the re-signing phase opens.</span><span class="spacer"></span><button class="primary" id="hof-go">Submit my ballot</button></div>` : "")
      : empty(`No ballot yet: it opens when a season ends. A player is eligible ${d.wait} years after he retires, with a Career Legacy Score of ${d.threshold} or more, for up to ${d.ballot_life} years.`);
  } else if (HF.tab === "members") {
    body = d.members.length ? table(d.members, [{key: "year", label: "Class", num: true}, {key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)},
      {key: "pos", label: "Pos"}, {key: "score", label: "CLS", num: true, fmt: cls}, {key: "tier", label: "Tier", fmt: (r) => tierTag(r.tier)},
      {key: "ballot_years", label: "Ballot", num: true, fmt: (r) => r.ballot_years ? `year ${r.ballot_years}` : (r.votes != null ? `${r.votes}/${r.of} votes` : "")},
      {key: "line", label: "Career"}]) : empty("Nobody has been inducted in this save yet.");
  } else {
    const t = await api("legacy", HF.all ? {all: "1"} : {});
    body = `<div class="toolbar"><label class="chk"><input type="checkbox" id="hf-all"${HF.all ? " checked" : ""}> Include retired players</label></div>` +
      table(t.rows, [{key: "name", label: "Player", fmt: (r) => clink(r.player_id, r.name)}, {key: "group", label: "Pos"},
        {key: "cls", label: "CLS", num: true, fmt: (r) => `<a href="#hof/${r.player_id}"><b>${r.cls.toFixed(1)}</b></a>`}, {key: "tier", label: "Tier", fmt: (r) => tierTag(r.tier)},
        {key: "peak", label: "Peak SV", num: true, fmt: (r) => r.peak.toFixed(2)}, {key: "longevity", label: "Longevity SV", num: true, fmt: (r) => r.longevity.toFixed(2)},
        {key: "hardware", label: "Hardware", num: true, fmt: (r) => r.hardware.toFixed(0)}, {key: "seasons", label: "Seasons", num: true}]);
  }
  const tiers = d.tiers.map((t, i) => `${esc(t.name)} ${i === 0 ? `over ${t.bar}` : `${t.bar}-${d.tiers[i - 1].bar - 1}`}`).join(" · ");
  AFTER = () => {
    document.querySelectorAll("[data-hftab]").forEach((b) => b.onclick = () => { HF.tab = b.dataset.hftab; render(); });
    const a = $("#hf-all"); if (a) a.onchange = () => { HF.all = a.checked; render(); };
    const b = $("#hof-go");
    if (b) b.onclick = () => {
      const ids = [...document.querySelectorAll(".hof-v:checked")].map((x) => x.value);
      if (ids.length > d.max) { toast(`Up to ${d.max}.`); return; }
      if (!ids.length) { toast("Tick at least one player."); return; }
      cmd(`hof vote ${ids.join(", ")}`);
    };
    decorate($("#view"));
  };
  const tabs = [["ballot", `Ballot ${d.ballot_year || ""}`], ["members", "Members"], ["tracker", "Legacy tracker"]];
  return panel("Hall of Fame", `<div class="toolbar"><div class="tabs">${tabs.map(([k, l]) => `<a class="btn${HF.tab === k ? " active" : ""}" data-hftab="${k}">${l}</a>`).join(" ")}</div></div>
    <p class="muted small">Career Legacy Score: era- and position-adjusted Season Values (best seven ×10, the rest ×3) plus trophies, championships and milestones. ${tiers}.</p>${body}`);
};

