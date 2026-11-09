"use strict";
// v33, phase B: tactics and lines. The Tactics screen (twelve settings with fit, execution and value; the five
// systems as presets; preferences; the next opponent and what counters him) and the Lines screen with roles, what
// each line lacks, chemistry, overtime units and player tendencies.

const pctS = (v) => `${v > 0 ? "+" : ""}${v.toFixed(1)}`;
const valCls = (v) => v > 0.05 ? "r4" : v < -0.05 ? "r1" : "";

/* ================================================================ the Tactics screen */
const TAC = {opp: null};
VIEWS.tactics = async () => {
  const d = await api("tactics", TAC.opp ? {opp: TAC.opp} : {});
  const groups = {};
  d.settings.forEach((s) => (groups[s.group] = groups[s.group] || []).push(s));
  const setting = (s) => `<tr><th>${esc(s.label)}</th><td>${s.options.map((o) => {
      const on = o.option === s.current;
      return `<button class="tac-opt${on ? " on" : ""}" ${on ? "disabled" : `data-cmd="tactics set ${s.key} ${o.option}"`} title="${o.attrs.length ? "Uses " + o.attrs.join(", ").replace(/_/g, " ") : "The engine as calibrated"}">
        <b>${esc(o.label)}</b><span>${o.attrs.length ? `fit ${pctS(o.fit)} · exec ${o.execution.toFixed(2)} · ` : ""}<i class="${valCls(o.value)}">${pctS(o.value)}</i></span></button>`;
    }).join("")}</td></tr>`;
  const grp = (g) => panel(g, `<table class="tac">${groups[g].map(setting).join("")}</table>`);
  const presets = table(d.presets, [{key: "system", label: "Preset", fmt: (r) => `${r.system === d.system ? "<b>" + esc(r.system) + "</b>" : esc(r.system)}${r.system === d.owner_identity ? ' <span class="tag">owner</span>' : ""}`},
    {key: "execution", label: "Execution", num: true, fmt: (r) => r.execution.toFixed(2)},
    {key: "value", label: "Value", num: true, fmt: (r) => `<span class="${valCls(r.value)}">${pctS(r.value)}</span>`},
    {key: "x", label: "", fmt: (r) => `<button class="mini" data-cmd="tactics ${esc(r.system)}" data-confirm="Set the six even-strength settings to ${esc(r.system)}? Special teams stay as they are.">Use</button>`}]);
  const prefs = `<table class="kvt">${Object.entries(d.pref_options).map(([k, p]) => `<tr><th>${esc(p.label)}</th><td><select data-pref="${k}">${p.options.map((o) => `<option${o === d.prefs[k] ? " selected" : ""}>${esc(o)}</option>`).join("")}</select></td></tr>`).join("")}</table>
    <p class="muted small">Line matching works at home, where you have the last change. Ice time spreads even-strength shifts over your four lines.</p>`;
  const sc = d.scout;
  const opp = sc ? `<div class="toolbar"><label>Opponent <select id="tac-opp">${d.teams.map((t) => `<option value="${t.team_id}"${t.team_id === sc.team_id ? " selected" : ""}>${esc(t.abbr)}</option>`).join("")}</select></label>
      ${sc.date ? `<span class="muted">next game ${esc(sc.date)}</span>` : ""}</div>
    <table class="kvt">${Object.entries(sc.labels).map(([k, v]) => `<tr><th>${esc(d.settings.find((s) => s.key === k).label)}</th><td>${esc(v)}</td></tr>`).join("")}</table>
    <p>How you match up: your attempts ${pctS((sc.you.att - 1) * 100)}%, shot quality ${pctS((sc.you.qual - 1) * 100)}%; on the power play ${pctS((sc.you.pp_att - 1) * 100)}% / ${pctS((sc.you.pp_qual - 1) * 100)}%.
      Theirs against you: ${pctS((sc.them.att - 1) * 100)}% / ${pctS((sc.them.qual - 1) * 100)}%.</p>
    ${sc.tips.length ? `<h4>To counter them</h4><ul class="plain">${sc.tips.map((t) => `<li><b>${esc(t.label)}</b>: ${esc(t.option_label)} beats their ${esc(t.against)} (+${t.gain}%) <button class="mini" data-cmd="tactics set ${t.setting} ${t.option}">Switch</button></li>`).join("")}</ul>` : '<p class="muted">Nothing in your settings is being countered.</p>'}`
    : empty("No opponent to scout.");
  AFTER = () => {
    document.querySelectorAll("[data-pref]").forEach((s) => (s.onchange = () => cmd(`tactics pref ${s.dataset.pref} ${s.value}`)));
    const o = $("#tac-opp"); if (o) o.onchange = (e) => { TAC.opp = +e.target.value; render(); };
  };
  const m = d.multipliers;
  const sum = `<div class="toolbar"><b>Closest system: ${esc(d.system)}</b>${d.owner_identity ? `<span class="muted">the owner wants ${esc(d.owner_identity)}</span>` : ""}<span class="spacer"></span>
    <span>Value <b class="${valCls(d.value)}">${pctS(d.value)}</b></span><span class="muted small">even strength: attempts ${pctS((m.att - 1) * 100)}% · allowed ${pctS((m.allow_att - 1) * 100)}% · quality ${pctS((m.qual - 1) * 100)}% · against ${pctS((m.allow_qual - 1) * 100)}% · penalties ${pctS((m.pen - 1) * 100)}%</span>
    <a class="btn" href="#lines">Lines</a></div>`;
  return sum + `<div class="grid two">${grp("With the puck")}${grp("Without the puck")}${grp("Power play")}${grp("Penalty kill")}</div>
    <div class="grid three">${panel("Presets (the five systems)", presets)}${panel("Preferences", prefs)}${panel(sc ? `Scouting: ${sc.abbr}` : "Scouting", opp)}</div>
    <p class="muted small">Each option's value is a rough goal-difference index (per cent) against an average club; every option breaks even with an average roster for it and an average coach, so fit and coaching make it pay. Some choices beat others (counters), game by game. The league's totals never move with the mix of tactics.</p>`;
};

/* ================================================================ the Lines screen */
VIEWS.lines = async () => {
  const d = await api("lines");
  const lu = d.lineup;
  if (!lu) return panel("Lines", "Your team cannot dress a lineup right now.");
  const byId = Object.fromEntries(d.players.map((p) => [p.player_id, p]));
  const short = {"Sniper": "SNP", "Playmaker": "PLY", "Power forward": "PWF", "Two-way forward": "2WF", "Grinder": "GRN", "Enforcer": "ENF",
    "Offensive D": "OFD", "Defensive D": "DFD", "Two-way D": "2WD", "Physical D": "PHD", "Positional": "POS", "Athletic": "ATH"};
  const opts = (sel, goalie) => `<option value="">-</option>` + d.players.filter((p) => (p.pos === "G") === goalie).map((p) =>
    `<option value="${p.player_id}"${p.player_id === sel ? " selected" : ""}${p.status === "injured" ? ' class="neg"' : ""}>${esc(p.name)} (${p.pos} ${p.value}${p.role ? " " + short[p.role] : ""}${p.status === "injured" ? ", injured" : ""})</option>`).join("");
  const select = (unit, i, sel, goalie = false) => `<select class="ln" data-unit="${unit}" data-i="${i}">${opts(sel, goalie)}</select>`;
  const chem = Object.fromEntries((d.chemistry || []).map((c) => [c.unit, c]));
  const note = (u) => (d.line_notes[u] || []).length ? `<span class="tag warn">${d.line_notes[u].map(esc).join(", ")}</span>` : '<span class="muted small">balanced</span>';
  const ch = (u) => chem[u] ? `<span class="chem" title="Chemistry from games together (${chem[u].games} for the pair with fewest)"><i style="width:${chem[u].chemistry}%"></i></span> ${chem[u].chemistry}` : "";
  // v39 (#4): forwards show left wing, centre, right wing (the depth chart's order); the line is still stored C, LW, RW
  const row = (unit, labels, ids, goalie = false, extra = true, order = null) => `<tr><th>${unit.replace(/^OT3/, "3v3 ").replace(/^OT4/, "4v4 ")}</th>${(order || labels.map((_, i) => i)).map((i) => `<td><span class="muted">${labels[i]}</span><br>${select(unit, i, ids[i], goalie)}</td>`).join("")}
    ${extra ? `<td class="ln-x">${note(unit)}<br>${ch(unit)}</td>` : ""}</tr>`;
  const F = [0, 1, 2, 3].map((i) => row(`F${i + 1}`, ["C", "LW", "RW"], lu.F[i] || [], false, true, [1, 0, 2])).join("");
  const D = [0, 1, 2].map((i) => row(`D${i + 1}`, ["LD", "RD"], lu.D[i] || [])).join("");
  const G = row("G", ["Starter", "Backup"], lu.G || [], true, false);
  const PP = [0, 1].map((i) => row(`PP${i + 1}`, ["", "", "", "", ""], (lu.PP[i] || []), false, false)).join("");
  const PK = [0, 1].map((i) => row(`PK${i + 1}`, ["", "", "", ""], (lu.PK[i] || []), false, false)).join("");
  const OT = [0, 1].map((i) => row(`OT3${i + 1}`, ["F", "F", "D"], ((lu.OT3 || [])[i] || []), false, false)).join("")
    + [0, 1].map((i) => row(`OT4${i + 1}`, ["F", "F", "D", "D"], ((lu.OT4 || [])[i] || []), false, false)).join("");
  const dressed = [...new Set([...lu.F.flat(), ...lu.D.flat()])].filter((x) => x && byId[x]);
  const tend = lu.tend || {};
  const tendRows = dressed.map((pid) => {
    const p = byId[pid], t = tend[String(pid)] || {};
    const sel = (kind, vals) => `<select data-tend="${pid}" data-kind="${kind}">${vals.map((v) => `<option${(t[kind] || "normal") === v ? " selected" : ""}>${esc(v)}</option>`).join("")}</select>`;
    return `<tr><td>${clink(pid, p.name)} <span class="muted">${esc(p.pos)}</span></td><td>${esc(p.role || "")} <span class="muted small">${p.fit ?? ""}</span></td><td><span class="tag">${esc(p.tag || "")}</span></td>
      <td>${sel("shoot", d.tendencies.shoot)}</td><td>${sel("style", d.tendencies.style)}</td></tr>`;
  }).join("");
  AFTER = () => {
    const check = () => {
      const counts = {};
      document.querySelectorAll('.ln[data-unit^="F"], .ln[data-unit^="D"]').forEach((s) => { if (s.value) counts[s.value] = (counts[s.value] || 0) + 1; });
      document.querySelectorAll(".ln").forEach((s) => s.classList.toggle("dup", /^[FD]/.test(s.dataset.unit) && counts[s.value] > 1));
      const ds = new Set(Object.keys(counts));
      document.querySelectorAll('.ln[data-unit^="P"], .ln[data-unit^="OT"]').forEach((s) => s.classList.toggle("dup", s.value && !ds.has(s.value)));
      $("#ln-warn").textContent = document.querySelector(".ln.dup") ? "Someone is in two places, or a special-teams or overtime player is not in the lines." : "";
    };
    document.querySelectorAll(".ln").forEach((s) => s.addEventListener("change", check));
    check();
    $("#ln-save").addEventListener("click", () => {
      const units = {};
      document.querySelectorAll(".ln").forEach((s) => { (units[s.dataset.unit] = units[s.dataset.unit] || [])[+s.dataset.i] = s.value; });
      const parts = Object.entries(units).map(([u, ids]) => /^(P|OT)/.test(u) && !ids.some((x) => x) ? `${u} none`
        : /^(P|OT)/.test(u) && ids.some((x) => !x) ? "" : `${u} ${ids.filter((x) => x).join(", ")}`).filter((p) => p && !/ $/.test(p));
      cmd(`lines set ${parts.join("; ")}`);
    });
    document.querySelectorAll("[data-tend]").forEach((s) => (s.onchange = async () => {
      const pid = s.dataset.tend, other = document.querySelector(`[data-tend="${pid}"][data-kind="${s.dataset.kind === "shoot" ? "style" : "shoot"}"]`).value;
      await post("/api/command", {line: `tend ${pid} normal`});
      if (s.value !== "normal") await post("/api/command", {line: `tend ${pid} ${s.value}`});
      if (other !== "normal") await post("/api/command", {line: `tend ${pid} ${other}`});
      toast("Tendency saved.");
    }));
  };
  const replaced = lu.replaced.length ? `<p><span class="tag warn">replaced for now</span> ${lu.replaced.map((p) => esc(byId[p] ? byId[p].name : "#" + p)).join(", ")} (unavailable; the depth chart fills in)</p>` : "";
  return `<div class="tabs"><b>${lu.custom ? "Your lines" : "Automatic lines"}</b> <span class="muted">${lu.custom ? "the engine uses these every game" : "from last season's ice time; edit and save to take over"}</span>
      <span class="spacer"></span><a class="btn" href="#tactics">Tactics</a> <button class="primary" id="ln-save">Save lines</button> <button data-cmd="lines auto" data-confirm="Go back to automatic lines?">Automatic</button></div>
    <p id="ln-warn" class="neg"></p>${replaced}
    <div class="grid g2">${panel("Forwards", `<table class="lines">${F}</table>`, "what each line lacks · chemistry")}
      <div class="grid">${panel("Defence", `<table class="lines">${D}</table>`)}${panel("Goal", `<table class="lines">${G}</table>`, "the starter plays about 82% of games")}</div>
      ${panel("Power play", `<table class="lines">${PP}</table><p class="muted">Leave a unit empty to have the power play drawn from the top lines. PP1 gets 65% of power-play time.</p>`)}
      ${panel("Penalty kill", `<table class="lines">${PK}</table><p class="muted">Special-teams players must also be in the lines.</p>`)}
      ${panel("Overtime units", `<table class="lines">${OT}</table><p class="muted">The first 3-on-3 (or 4-on-4) unit plays about 60% of overtime. Leave them empty to send out your top lines.</p>`)}
      ${panel("Player types and tendencies", `<table class="tend"><thead><tr><th>Player</th><th>Role</th><th></th><th>Shooting</th><th>Style</th></tr></thead><tbody>${tendRows}</tbody></table>
        <p class="muted small">Player types are read from the ratings (display only; the tactical roles below are what changes games). Shoot first takes more of his unit's shots and makes fewer assists; attacking trades a little defence for offence.</p>`)}</div>`;
};

/* ================================================================ menus */
(() => {
  const team = MENUS.find((m) => m[0] === "Team")[1];
  const i = team.findIndex((it) => it !== "-" && it[0] === "Lineup and Tactics");
  team.splice(i, 1, ["Lines", "#lines"], ["Tactics", "#tactics"]);
  Object.assign(SCREEN_NAMES, {tactics: "Tactics", lines: "Lines"});
  Object.assign(TAB_OF, {tactics: "lines"});
})();

/* ---- boot: moved to the last script (v34.js) ---- */
