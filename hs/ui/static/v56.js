"use strict";
// v56: the owner's goals on the Board screen (hs/game/owner_goals.py): this season's goals with priority, deadline and
// progress, past ones with their result, and the catalogue they come from.

const boardV56 = VIEWS.board;
VIEWS.board = async (...args) => {
  const html = await boardV56(...args);
  let d;
  try { d = await api("ownergoals"); } catch (e) { return html; }
  const prio = (p) => `<span class="tag ${p === "high" ? "warn" : ""}">${esc(p)}</span>`;
  const st = (g) => g.status === "open" ? `<span class="muted">${esc(g.progress || "")}</span>`
    : `<b class="${g.status === "met" ? "r4" : "r1"}">${g.status === "met" ? "met" : "missed"}</b> <span class="muted small">${esc(g.result || "")}</span>`;
  const rows = d.goals.length ? table(d.goals, [{key: "season", label: "Season", fmt: (g) => ssn(g.season)}, {key: "description", label: "Goal"},
    {key: "priority", label: "Priority", fmt: (g) => prio(g.priority)}, {key: "deadline", label: "By", fmt: (g) => dshort(g.deadline)},
    {key: "status", label: "Progress", fmt: st},
    {key: "delta", label: "Confidence", num: true, fmt: (g) => g.delta == null ? `<span class="muted small">+${d.reward[g.priority]} / -${d.penalty[g.priority]}</span>`
      : `<span class="${g.delta > 0 ? "r4" : "r1"}">${g.delta > 0 ? "+" : ""}${g.delta}</span>`}])
    : empty("The owner sets his goals when the regular season starts.");
  const cat = `<details><summary class="muted small">The catalogue the owner chooses from</summary><table class="nosort">
    <tr><th>Goal</th><th>When he asks</th><th>Deadline</th></tr>${d.catalogue.map((c) => `<tr><td>${esc(c[1])}</td><td class="muted small">${esc(c[2])}</td><td>${esc(c[3])}</td></tr>`).join("")}</table></details>`;
  return panel("The owner's goals", rows + `<p class="muted small">Up to three a season, beyond the board's objectives. Met: confidence +${d.reward.low} / +${d.reward.medium} / +${d.reward.high} (low / medium / high priority); missed: -${d.penalty.low} / -${d.penalty.medium} / -${d.penalty.high}.</p>` + cat) + html;
};

Object.assign(FR, {"The owner's goals": "Les objectifs du propriétaire", "Goal": "Objectif", "Priority": "Priorité", "By": "D'ici", "Progress": "Progrès",
  "The catalogue the owner chooses from": "Le catalogue du propriétaire", "When he asks": "Quand il le demande", "Deadline": "Échéance"});

/* ---- boot: moved to the last script (v57.js) ---- */
