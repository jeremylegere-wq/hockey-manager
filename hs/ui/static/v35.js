"use strict";
// v35, phase D: people. On the player screen: what your scouts read of his hidden side, his special abilities, his
// game ratings, his morale log (your players), and the buttons to play him hurt, rest him or end his contract by
// agreement. On Team Info (your club): cliques, clashes and incidents in the room.

const ratingCls = (v) => v == null ? "" : v >= 7.5 ? "r4" : v >= 6.3 ? "r3" : v >= 5.2 ? "r2" : "r1";
const playerV35 = VIEWS.player;
VIEWS.player = async (id) => {
  const html = await playerV35(id);
  const prev = AFTER;
  AFTER = async () => {
    if (prev) await prev();
    const d = await api("people", {id}).catch(() => null);
    if (!d) return;
    const hero = $(".pp-id");
    if (hero) {
      const tags = d.abilities.map((a) => `<span class="pp-tag ability">${esc(a)}</span>`).join("") + d.scout.map((x) => `<span class="pp-tag scout" title="Your scouts' read">${esc(x)}</span>`).join("");
      if (tags) hero.insertAdjacentHTML("beforeend", `<div class="pp-tags v35">${tags}</div>`);
      const acts = [];
      if (d.hurt && d.hurt.can_play) acts.push(`<button class="mini" data-cmd="playhurt ${id}" data-confirm="Play him through the injury? He is below his best until he would have been back (${d.hurt.days_left} days), and each game he might make it worse.">Play hurt</button>`);
      if (d.playing_hurt) acts.push(`<span class="tag warn">playing hurt</span> <button class="mini" data-cmd="rest ${id}">Rest him</button>`);
      if (d.terminate) acts.push(d.terminate.willing ? `<button class="mini" data-cmd="terminate ${id}" data-confirm="He would agree to end his contract (${esc(d.terminate.why)}) for a settlement of about ${mil(d.terminate.settlement)} in cash. No buyout and no cap charge; he becomes a free agent. Go ahead?">Mutual termination...</button>`
        : `<span class="muted small" title="${esc(d.terminate.why)}">would not agree to a termination</span>`);
      if (acts.length) hero.insertAdjacentHTML("beforeend", `<div class="pp-marks">${acts.join(" ")}</div>`);
    }
    const view = $("#view");
    const tab = location.hash.split("/")[2] || "overview";
    if (tab === "overview" && d.ratings.length) {
      view.insertAdjacentHTML("beforeend", panel(`Game ratings${d.rating_avg ? ` · season average ${d.rating_avg}` : ""}`, table(d.ratings, [
        {key: "date", label: "Date", fmt: (r) => `<a href="#game/${r.game_id}">${dshort(r.date)}</a>`},
        {key: "offence", label: "Offence", num: true, fmt: (r) => r.offence == null ? "-" : `<b class="${ratingCls(r.offence)}">${r.offence}</b>`},
        {key: "defence", label: "Defence", num: true, fmt: (r) => r.defence == null ? "-" : `<b class="${ratingCls(r.defence)}">${r.defence}</b>`},
        {key: "overall", label: "Overall", num: true, fmt: (r) => `<b class="${ratingCls(r.overall)}">${r.overall}</b>`}])
        + '<p class="muted small">1-10 for each game: goals, assists and shots for offence; blocks, the goals allowed while he played and penalties for defence; save % for goalies.</p>'));
    }
    if (tab === "person" && d.morale_log.length) {
      view.insertAdjacentHTML("beforeend", panel("What moved his morale", table(d.morale_log, [{key: "day", label: "Date", fmt: (r) => dshort(r.day)},
        {key: "component", label: "Part", fmt: (r) => esc({role: "Role", team: "Team", contract: "Contract", trust_mgmt: "Trust in you", trust_coach: "Trust in the coach"}[r.component] || r.component)},
        {key: "delta", label: "Change", num: true, fmt: (r) => `<b class="${r.delta > 0 ? "r4" : "r1"}">${r.delta > 0 ? "+" : ""}${r.delta}</b>`}, {key: "reason", label: "Why"}])));
    }
    decorate(view);
  };
  return html;
};

const teaminfoV35 = VIEWS.teaminfo;
VIEWS.teaminfo = async (id) => {
  const html = await teaminfoV35(id);
  if (!STATE || +(id || STATE.team_id) !== STATE.team_id) return html;
  const h = await api("harmony").catch(() => null);
  if (!h) return html;
  const cl = h.cliques.length ? h.cliques.map((c) => `<li><b>${esc(c.name)}</b> (${c.players.length}) <span class="${c.morale < 45 ? "r1" : "muted"}">morale ${c.morale}${c.morale < 45 ? ", pulling the room down" : ""}</span><br>
      <span class="small muted">${c.names.map(esc).join(", ")}</span></li>`).join("") : "<li class=\"muted\">No cliques.</li>";
  const cs = h.clashes.length ? h.clashes.map((x) => `<li>${clink(x.a, x.names[0])} and ${clink(x.b, x.names[1])}</li>`).join("") : '<li class="muted">Nobody is at odds.</li>';
  const inc = h.incidents.length ? h.incidents.map((x) => `<li><span class="muted">${dshort(x.day)}</span> ${esc(x.text)}</li>`).join("") : '<li class="muted">No incidents.</li>';
  return html + `<div class="grid three">${panel("Cliques", `<ul class="plain">${cl}</ul>`)}${panel("Personalities that clash", `<ul class="plain">${cs}</ul><p class="muted small">Big egos with a short fuse, little sportsmanship, or an unhappy malcontent. A strong captain keeps a lid on it.</p>`)}
    ${panel("Incidents", `<ul class="plain">${inc}</ul>`)}</div>`;
};

/* ---- boot: moved to the last script (v36.js) ---- */
