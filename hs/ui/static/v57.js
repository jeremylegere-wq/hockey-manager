"use strict";
// v57: a new arena on the Finances screen (hs/game/arena.py): the quote (cost, the owner's share, the loan), the
// owner's approval, construction and the loan once it is under way.

const finV57 = VIEWS.finances;
VIEWS.finances = async (...args) => {
  const html = await finV57(...args);
  let d;
  try { d = await api("arena"); } catch (e) { return html; }
  const M = (v) => `$${(v / 1e6).toLocaleString(undefined, {maximumFractionDigits: 1})}M`;
  const p = d.project, ln = d.loan;
  let body;
  if (p) {
    body = `<table class="kvt"><tr><th>Project</th><td>${p.capacity.toLocaleString()} seats, quality ${Math.round(p.quality)}</td></tr>
      <tr><th>Cost</th><td>${M(p.cost)} (the owner ${M(p.owner_share)}, the loan ${M(p.loan)})</td></tr>
      <tr><th>Status</th><td>${p.status === "open" ? `open since ${dshort(p.opened)}` : `building: ${p.months_paid} of 24 months paid; opens ${ssn(p.opens_season)}`}</td></tr>
      ${ln ? `<tr><th>Loan</th><td>${M(ln.balance)} left at ${(ln.rate * 100).toFixed(0)}%, ${M(ln.payment)} a month</td></tr>` : ""}
      ${d.novelty ? `<tr><th>Novelty</th><td>demand +${(d.novelty * 100).toFixed(1)}%</td></tr>` : ""}</table>`;
  } else {
    const q = d.quote;
    body = `<div class="toolbar"><label>Seats <input id="ar-seats" type="number" min="${d.ranges.capacity[0]}" max="${d.ranges.capacity[1]}" step="250" value="${q.capacity}" style="width:90px"></label>
      <label>Quality <input id="ar-q" type="number" min="${d.ranges.quality[0]}" max="${d.ranges.quality[1]}" value="${Math.round(q.quality)}" style="width:60px"></label>
      <span class="spacer"></span><button id="ar-go"${d.offseason ? "" : " disabled title=\"In the offseason\""}>Ask the owner</button></div><div id="ar-quote"></div>
      <p class="muted small">Two seasons to build, paid month by month. The owner puts in 20% + 6% per point of his spending; the club borrows the rest at ${(d.rate * 100).toFixed(0)}% over ${d.years} years.
      Opening season: demand +8%, fading over five. The building is depreciated over 30 years.</p>`;
  }
  const prev = AFTER;
  AFTER = async () => {
    if (prev) await prev();
    const qd = $("#ar-quote");
    if (!qd) return;
    const show = async () => {
      const q = await api("arena", {seats: $("#ar-seats").value, quality: $("#ar-q").value});
      qd.innerHTML = `<table class="kvt"><tr><th>Cost</th><td>${M(q.cost)}</td></tr><tr><th>The owner</th><td>${M(q.owner_share)} (${q.owner_pct}%)</td></tr>
        <tr><th>The loan</th><td>${M(q.loan)}: ${M(q.yearly)} a year from the opening; interest ${M(q.interest_first_year)} in the first year</td></tr>
        <tr><th>Opens</th><td>${ssn(q.opens)}</td></tr></table>${q.ok ? '<p class="r4 small">The owner would approve it.</p>' : `<p class="r1 small">${esc(q.why)}</p>`}`;
      $("#ar-go").disabled = !q.ok || !d.offseason;
    };
    $("#ar-seats").onchange = show; $("#ar-q").onchange = show;
    $("#ar-go").onclick = async () => {
      const ok = await ask(`Build a ${(+$("#ar-seats").value).toLocaleString()}-seat arena of quality ${$("#ar-q").value}? This cannot be undone.`, {ok: "Build it"});
      if (ok) { await cmd(`arena new ${$("#ar-seats").value} ${$("#ar-q").value}`); render(); }
    };
    show();
  };
  return html + panel("A new arena", body);
};

Object.assign(FR, {"A new arena": "Un nouvel aréna", "Ask the owner": "Demander au propriétaire", "Seats": "Sièges", "Quality": "Qualité",
  "Project": "Projet", "Cost": "Coût", "Loan": "Prêt", "Novelty": "Nouveauté", "Opens": "Ouverture"});

/* ---- boot (keep last) ---- */
loadLogos().finally(() => bootApp());
