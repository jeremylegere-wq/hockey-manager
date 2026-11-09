"use strict";
// v55: tactical roles on the Lines screen (hs/game/troles.py): each dressed skater's role, his fit for every role,
// "suggest" and "clear", and what each role does on the ice.

const TRV = {open: true, info: false};
const linesV55 = VIEWS.lines;
VIEWS.lines = async (...args) => {
  const html = await linesV55(...args);
  const prev = AFTER;
  let d;
  try { d = await api("troles"); } catch (e) { return html; }
  const R = Object.fromEntries(d.roles.map((r) => [r.role, r]));
  const fitCls = (f) => f == null ? "" : f >= 70 ? "r4" : f >= 60 ? "r3" : f >= 45 ? "" : "r1";
  const rows = d.players.filter((p) => p.dressed).map((p) => {
    const opts = Object.entries(p.fits).sort((a, b) => b[1] - a[1]).map(([k, f]) => `<option value="${k}"${k === p.role ? " selected" : ""}>${esc(R[k].label)} (${f})</option>`).join("");
    return `<tr><td>${clink(p.player_id, p.name)} <span class="muted">${esc(p.pos)}</span></td>
      <td><select class="tr-sel" data-pid="${p.player_id}"><option value="none">no role</option>${opts}</select></td>
      <td class="num ${fitCls(p.fit)}">${p.fit ?? ""}</td><td class="num">${p.exec != null ? "x" + p.exec.toFixed(2) : ""}</td>
      <td>${p.best ? `${esc(R[p.best].label)} <span class="${fitCls(p.best_fit)}">${p.best_fit}</span>` : ""}</td>
      <td class="muted small">${p.role ? esc(R[p.role].upside) : ""}</td></tr>`;
  }).join("");
  const info = `<table class="nosort tr-info"><tr><th>Role</th><th>For</th><th>When</th><th>Upside (scaled by execution)</th><th>Cost (fixed)</th><th>Fit from</th></tr>
    ${d.roles.map((r) => `<tr><td><b>${esc(r.label)}</b></td><td>${r.positions === "FD" ? "F, D" : r.positions}</td><td>${esc(r.states.join(", "))}</td>
      <td>${esc(r.upside)}${r.extra ? `; ${esc(r.extra)}` : ""}</td><td>${esc(r.cost)}</td><td class="muted small">${esc(r.attributes.join(", ").replace(/_/g, " "))}</td></tr>`).join("")}</table>`;
  const body = `<div class="toolbar"><button id="tr-sug">Suggest</button> <button id="tr-clr">Clear</button>
      <span class="spacer"></span><a class="btn" id="tr-info">${TRV.info ? "Hide what the roles do" : "What the roles do"}</a> <a class="btn" id="tr-tog">${TRV.open ? "Hide" : "Show"}</a></div>
    <p class="muted small">A role's upside grows with the player's fit and its cost does not: at fit 50 (the league's average player for the role) it breaks even, so give a role only to a player who suits it
      (execution = 0.2 + fit / 62.5). Suggest gives each role to the best-fitting dressed player who clears fit ${d.suggest_fit}. At most ${d.max_per_role} players in a role. AI clubs set theirs the same way.</p>
    ${TRV.info ? info : ""}
    ${TRV.open ? `<table class="nosort tr-tbl"><tr><th>Player</th><th>Role (fit)</th><th class="num">Fit</th><th class="num">Exec</th><th>Best fit</th><th>On the ice</th></tr>${rows}</table>` : ""}`;
  AFTER = () => {
    if (prev) prev();
    $("#tr-sug").onclick = async () => { await cmd("troles suggest"); render(); };
    $("#tr-clr").onclick = async () => { await cmd("troles clear", {quiet: true}); render(); };
    $("#tr-info").onclick = () => { TRV.info = !TRV.info; render(); };
    $("#tr-tog").onclick = () => { TRV.open = !TRV.open; render(); };
    document.querySelectorAll(".tr-sel").forEach((s) => (s.onchange = async () => {
      const r = await cmd(`troles ${s.dataset.pid} ${s.value}`, {quiet: true});
      render();
    }));
  };
  return html + panel("Tactical roles", body);
};

Object.assign(FR, {"Tactical roles": "Rôles tactiques", "Suggest": "Suggérer", "Clear": "Effacer", "What the roles do": "Ce que font les rôles",
  "Hide what the roles do": "Masquer les rôles", "no role": "aucun rôle", "Best fit": "Meilleur rôle", "On the ice": "Sur la glace", "Role (fit)": "Rôle (aptitude)",
  "Fit": "Aptitude", "Exec": "Exécution", "Upside (scaled by execution)": "Gain (selon l'exécution)", "Cost (fixed)": "Coût (fixe)", "Fit from": "Aptitude selon",
  "When": "Quand", "For": "Pour"});

/* ---- boot: moved to the last script (v56.js) ---- */
