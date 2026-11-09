/* v47: Manager > Challenges (challenge mode and challenges) and League > Commissioner (commissioner tools)
   (docs/CHALLENGES.md, docs/EDITOR.md). */

VIEWS.challenge = async () => {
  const d = await api("challenge");
  const cur = d.current;
  const yr = (y) => `${y}-${String((y + 1) % 100).padStart(2, "0")}`;
  let parts = [];
  parts.push(panel("Challenge mode", d.mode
    ? `<p><span class="tag pos">on</span> This is a challenge-mode career: no commissioner mode or editor, in-season sims of at most ${d.max_sim_days} days, and you can be fired.</p>`
    : d.edited ? `<p class="muted">This save has used commissioner mode, so it cannot become a challenge-mode career.</p>`
    : `<p>Challenge mode: no commissioner mode or editor, in-season sims of at most ${d.max_sim_days} days (long sims in the off-season only), and you can be fired.
       It stays on for the rest of the career.</p><button class="primary" id="chm-on">Turn on challenge mode</button>`));
  if (cur) {
    const prog = (cur.progress || []).map((p) => `<tr><td>${yr(p.season)}</td><td>${esc(p.team)}</td><td>${["missed the playoffs", "lost in round 1", "lost in round 2", "lost in the conference final", "lost in the final", "won the championship"][p.round] || ""}</td></tr>`).join("");
    parts.push(panel(`Challenge: ${esc(cur.name)}`, `<p><b>${esc(cur.goal)}</b></p>
      <p>Status: <span class="tag${cur.status === "won" ? " pos" : cur.status === "lost" ? " neg" : ""}">${esc(cur.status === "on" ? "in progress" : cur.status)}</span>
      · started ${yr(cur.start)} · deadline: the end of ${yr(cur.deadline)}${cur.result ? ` · ${esc(cur.result)}` : ""}</p>
      ${prog ? `<table class="dv-t"><tr><th>Season</th><th>Club</th><th>Result</th></tr>${prog}</table>` : '<p class="muted">No season finished yet.</p>'}
      ${cur.status === "on" ? '<p><button id="ch-ab">Abandon the challenge</button></p>' : ""}`));
  }
  if (d.can_start) {
    parts.push(panel("Take on a challenge", `<p class="muted small">A challenge starts at the beginning of a career, before your club's first game: you can pick one now.</p>
      <table class="dv-t"><tr><th>Challenge</th><th>Goal</th><th>Suits</th><th></th></tr>${d.challenges.map((c) => `<tr><td><b>${esc(c.name)}</b></td><td>${esc(c.goal)}</td>
        <td class="small">${c.suggest.length ? esc(c.suggest.join(", ")) : "any club"}</td><td><button class="ch-go" data-k="${c.key}">Take it on</button></td></tr>`).join("")}</table>`));
  } else if (!cur) {
    parts.push(panel("Challenges", `<p class="muted">${esc(d.why)} Start a new career to take one on.</p>`));
  }
  if (d.history.length) {
    parts.push(panel("Past challenges", table(d.history, [{key: "name", label: "Challenge"}, {key: "start", label: "From", fmt: (r) => yr(r.start)},
      {key: "status", label: "Result", fmt: (r) => `<span class="tag${r.status === "won" ? " pos" : " neg"}">${esc(r.status)}</span> ${esc(r.result || "")}`},
      {key: "mode", label: "Mode", fmt: (r) => r.mode ? "challenge mode" : ""}])));
  }
  AFTER = () => {
    const on = $("#chm-on");
    if (on) on.onclick = async () => { if (await ask("Turn on challenge mode for the rest of this career? It cannot be turned off.", {ok: "Turn it on"})) { await cmd("challenge mode on"); render(); } };
    document.querySelectorAll(".ch-go").forEach((b) => b.onclick = async () => { const r = await cmd(`challenge start ${b.dataset.k}`); if (r.ok) render(); });
    const ab = $("#ch-ab"); if (ab) ab.onclick = async () => { if (await ask("Abandon the challenge? It counts as failed.", {ok: "Abandon", danger: true})) { await cmd("challenge abandon"); render(); } };
  };
  return parts.join("");
};

const CM = {a: null, b: null, ga: new Set(), gb: new Set()};
VIEWS.commish = async () => {
  const d = await api("commish", Object.assign({}, CM.a ? {a: CM.a} : {}, CM.b ? {b: CM.b} : {}));
  if (d.challenge_mode) return panel("Commissioner", '<p class="muted">This is a challenge-mode career: commissioner mode is off for good.</p>');
  if (!d.enabled) return panel("Commissioner", `<p>Commissioner mode lets you trade between any clubs, take over any club, fire GMs and coaches, injure or heal players and change the league's rules.
    Turning it on marks the save as edited for good.</p><button class="primary" id="cm-on">Turn on commissioner mode</button>`);
  const r = d.rules;
  const clubOpts = (sel) => `<option value="">choose...</option>` + d.clubs.map((c) => `<option value="${c.team_id}"${+sel === c.team_id ? " selected" : ""}>${esc(c.abbr)} ${esc(c.name)}</option>`).join("");
  const side = (k, set) => {
    const s = d.sides[k];
    if (!s) return '<p class="muted">Choose a club.</p>';
    return `<div class="cm-list">${s.players.map((p) => `<label><input type="checkbox" class="cm-p" data-side="${k}" value="${p.player_id}"${set.has(String(p.player_id)) ? " checked" : ""}> ${esc(p.name)} <span class="muted">${p.pos}${p.status !== "active" ? " · " + p.status : ""}</span></label>`).join("")}
      ${s.picks.map((p) => `<label><input type="checkbox" class="cm-p" data-side="${k}" value="${p.code}"${set.has(p.code) ? " checked" : ""}> <span class="muted">pick</span> ${esc(p.label)}</label>`).join("")}</div>`;
  };
  const rulesForm = [["cap", "Salary cap", (r.cap / 1e6).toFixed(1) + "m"], ["floor", "Cap floor", (r.floor / 1e6).toFixed(1) + "m"], ["min_salary", "League minimum", (r.min_salary / 1e3).toFixed(0) + "k"],
    ["roster_min", "Roster minimum", r.roster_min], ["roster_max", "Roster maximum", r.roster_max], ["deadline", "Trade deadline (MM-DD)", r.deadline.slice(5)]]
    .map(([k, l, v]) => `<label>${l} <input class="cm-rule" data-k="${k}" value="${esc(String(v))}" size="9"></label>`).join("");
  const body = panel("Trade between any clubs", `<div class="cm-trade"><div><select id="cm-a">${clubOpts(CM.a)}</select>${side("a", CM.ga)}</div>
      <div><select id="cm-b">${clubOpts(CM.b)}</select>${side("b", CM.gb)}</div></div>
      <div class="toolbar"><label class="chk"><input type="checkbox" id="cm-force"> Force (skip the cap and roster checks)</label><span class="spacer"></span><button class="primary" id="cm-trade">Make the trade</button></div>`) +
    panel("Clubs and people", `<div class="cm-row"><label>Club <select id="cm-club">${clubOpts(null)}</select></label>
      <button id="cm-take">Take over this club</button> <button id="cm-gm">Fire its GM</button> <button id="cm-hc">Fire its head coach</button></div>
      <div class="cm-row"><label>Player (name or id) <input id="cm-pl" size="22"></label> <label>Days <input id="cm-days" size="4" value="14"></label>
      <button id="cm-inj">Injure</button> <button id="cm-heal">Heal</button></div>`) +
    panel("League rules", `<div class="cm-rules">${rulesForm}</div><p class="muted small">Amounts take 95.5m, 850k or a plain number. Changes apply from now on.</p>`) +
    (d.log.length ? panel("Commissioner log", table(d.log, [{key: "day", label: "Date", fmt: (x) => dshort(x.day)}, {key: "what", label: ""}, {key: "detail", label: "", fmt: (x) => esc(String(x.detail).replace(/^"|"$/g, ""))}])) : "");
  AFTER = () => {
    $("#cm-a").onchange = (e) => { CM.a = e.target.value || null; CM.ga = new Set(); render(); };
    $("#cm-b").onchange = (e) => { CM.b = e.target.value || null; CM.gb = new Set(); render(); };
    document.querySelectorAll(".cm-p").forEach((x) => x.onchange = () => { const s = x.dataset.side === "a" ? CM.ga : CM.gb; x.checked ? s.add(x.value) : s.delete(x.value); });
    $("#cm-trade").onclick = async () => {
      if (!CM.a || !CM.b || CM.a === CM.b) return toast("Choose two different clubs.", true);
      const ab = (id) => d.clubs.find((c) => c.team_id === +id).abbr;
      const res = await cmd(`commish trade ${ab(CM.a)} ${[...CM.ga].join(" ")} for ${ab(CM.b)} ${[...CM.gb].join(" ")}${$("#cm-force").checked ? " force" : ""}`);
      if (res.ok) { CM.ga = new Set(); CM.gb = new Set(); render(); }
    };
    const club = () => { const v = $("#cm-club").value; if (!v) { toast("Choose a club.", true); return null; } return d.clubs.find((c) => c.team_id === +v).abbr; };
    $("#cm-take").onclick = async () => { const a = club(); if (a && await ask(`Take over ${a}? You leave your club at once.`, {ok: "Take over"})) { await cmd(`commish takeover ${a}`); location.hash = "#dashboard"; } };
    $("#cm-gm").onclick = async () => { const a = club(); if (a) { await cmd(`commish fire ${a} gm`); render(); } };
    $("#cm-hc").onclick = async () => { const a = club(); if (a) { await cmd(`commish fire ${a} coach`); render(); } };
    $("#cm-inj").onclick = async () => { const p = $("#cm-pl").value.trim(); if (p) { await cmd(`commish injure ${p} ${$("#cm-days").value}`); render(); } };
    $("#cm-heal").onclick = async () => { const p = $("#cm-pl").value.trim(); if (p) { await cmd(`commish heal ${p}`); render(); } };
    document.querySelectorAll(".cm-rule").forEach((i) => i.onchange = async () => { await cmd(`commish rule ${i.dataset.k} ${i.value}`); render(); });
  };
  return body;
};
document.addEventListener("click", async (e) => {
  if (e.target && e.target.id === "cm-on") { if (await ask("Turn on commissioner mode? The save is marked as edited for good.", {ok: "Turn it on"})) { await cmd("editor on"); render(); } }
});
(() => {
  const mgr = MENUS.find((m) => m[0] === "Manager")[1];
  const at = mgr.findIndex((x) => Array.isArray(x) && x[0] === "Manager Profile");
  mgr.splice(at >= 0 ? at + 1 : mgr.length, 0, ["Challenges", "#challenge"]);
  const lg = MENUS.find((m) => m[0] === "League")[1];
  lg.push("-", ["Commissioner", "#commish"]);
  Object.assign(SCREEN_NAMES, {challenge: "Challenges", commish: "Commissioner"});
})();

