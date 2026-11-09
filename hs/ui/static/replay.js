"use strict";
// 2D replay of a played game (data from hs/game/replay.py). Positions are reconstructed, not tracked: the engine
// records events, not where players stood. Rink: 200 x 85 ft, centre ice at (0, 0), nets at x = +-89.

const Replay = (() => {
  const W = 200, H = 85, PAD = 4;
  const SPEEDS = [30, 60, 120, 300];               // game seconds per real second
  const PAUSE = {goal: 2.2, shot: 0.55, miss: 0.45, block: 0.45, penalty: 1.2, so_goal: 1.8, so_miss: 1.2};
  const TRAVEL = 0.45;                              // real seconds the puck takes from stick to net

  function mount(el, data) {
    if (!el) return;
    const evs = data.events.slice();
    const reg = data.length;
    let round = 0;
    evs.forEach((e) => { if (e.t == null) { round += 1; e.t = reg + 6 * round; } });   // shootout after play
    const end = evs.length ? Math.max(reg, evs[evs.length - 1].t + 3) : reg;
    el.innerHTML = `
      <div class="rp-board"><span class="rp-team" style="--c:${data.away.color}">${data.away.abbr}</span>
        <b class="rp-score" data-k="away">0</b><span class="rp-clock" data-k="clock">1st 20:00</span><b class="rp-score" data-k="home">0</b>
        <span class="rp-team" style="--c:${data.home.color}">${data.home.abbr}</span>
        <span class="rp-sog muted" data-k="sog"></span><span class="rp-pp" data-k="pp"></span></div>
      <canvas class="rp-canvas"></canvas>
      <div class="rp-caption" data-k="cap">&nbsp;</div>
      <div class="rp-controls">
        <button data-a="play" class="primary">Play</button>
        <button data-a="prev">&#9664;&#9664; Goal</button><button data-a="next">Goal &#9654;&#9654;</button>
        <label>Speed <select data-a="speed">${SPEEDS.map((s) => `<option value="${s}"${s === 60 ? " selected" : ""}>${s}x</option>`).join("")}</select></label>
        <label><input type="checkbox" data-a="chart" checked> Shot chart</label>
        <input type="range" data-a="seek" min="0" max="${end}" step="1" value="0">
      </div>
      <p class="muted rp-note">Reconstructed from the game's events: shot spots come from each chance's quality, and the
        unnamed dots stand in for skaters the engine does not track. Shot chart: dot = save, cross = miss or block, ringed dot = goal.</p>`;
    const cv = el.querySelector("canvas"), ctx = cv.getContext("2d");
    const q = (k) => el.querySelector(`[data-k="${k}"]`), a = (k) => el.querySelector(`[data-a="${k}"]`);

    // state
    let t = 0, playing = false, speed = 60, last = null, hold = 0, holdEv = null, idx = 0;
    let puck = {x: 0, y: 0}, from = {x: 0, y: 0}, chart = true;
    const skaters = {home: formation(), away: formation()};

    function formation() { return Array.from({length: 5}, (_, i) => ({x: (i - 2) * 10, y: (i % 2 ? 1 : -1) * 12 * (i % 3)})); }
    function scale() {
      const w = el.clientWidth || 800;
      cv.width = w * devicePixelRatio; cv.height = (w * (H + 2 * PAD) / (W + 2 * PAD)) * devicePixelRatio;
      cv.style.width = w + "px"; cv.style.height = (w * (H + 2 * PAD) / (W + 2 * PAD)) + "px";
    }
    const k = () => cv.width / (W + 2 * PAD);
    const X = (x) => (x + W / 2 + PAD) * k(), Y = (y) => (H / 2 - y + PAD) * k();

    function rink() {
      const s = k();
      ctx.fillStyle = "#f4f8fc"; ctx.strokeStyle = "#1c2a3a"; ctx.lineWidth = 1.2 * s;
      roundRect(X(-W / 2), Y(H / 2), W * s, H * s, 28 * s); ctx.fill(); ctx.stroke();
      ctx.save(); roundRect(X(-W / 2), Y(H / 2), W * s, H * s, 28 * s); ctx.clip();
      line(0, "#c0392b", 1.0); line(25, "#2f6fd6", 1.0); line(-25, "#2f6fd6", 1.0); line(89, "#c0392b", 0.3); line(-89, "#c0392b", 0.3);
      circle(0, 0, 15, "#2f6fd6");
      for (const sx of [-69, 69]) for (const sy of [-22, 22]) { circle(sx, sy, 15, "#c0392b"); dot(sx, sy, 1, "#c0392b"); }
      for (const sx of [-20, 20]) for (const sy of [-22, 22]) dot(sx, sy, 1, "#c0392b");
      for (const d of [-1, 1]) {                     // creases and nets
        ctx.fillStyle = "rgba(47,111,214,.25)"; ctx.beginPath();
        ctx.arc(X(d * 89), Y(0), 6 * s, d > 0 ? Math.PI / 2 : -Math.PI / 2, d > 0 ? 1.5 * Math.PI : Math.PI / 2); ctx.fill();
        ctx.strokeStyle = "#1c2a3a"; ctx.lineWidth = 0.8 * s; ctx.strokeRect(X(d > 0 ? 89 : -93), Y(3), 4 * s, 6 * s);
      }
      ctx.restore();
    }
    function roundRect(x, y, w, h, r) {
      ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
      ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
    }
    function line(x, c, w) { ctx.strokeStyle = c; ctx.lineWidth = w * k(); ctx.beginPath(); ctx.moveTo(X(x), Y(H / 2)); ctx.lineTo(X(x), Y(-H / 2)); ctx.stroke(); }
    function circle(x, y, r, c) { ctx.strokeStyle = c; ctx.lineWidth = 0.4 * k(); ctx.beginPath(); ctx.arc(X(x), Y(y), r * k(), 0, 2 * Math.PI); ctx.stroke(); }
    function dot(x, y, r, c) { ctx.fillStyle = c; ctx.beginPath(); ctx.arc(X(x), Y(y), r * k(), 0, 2 * Math.PI); ctx.fill(); }
    function label(x, y, text, c) {
      ctx.font = `${Math.max(10, 3.2 * k())}px system-ui, sans-serif`; ctx.fillStyle = c; ctx.textAlign = "center";
      ctx.fillText(text, X(x), Y(y) - 2.6 * k());
    }

    // where the play is heading: the next event's shot spot
    function nextEv() { return evs[idx] || null; }
    function targets(dt) {
      const ne = nextEv();
      const att = ne && ne.type !== "penalty" ? ne.team : null;
      const px = puck.x, py = puck.y;
      for (const side of ["home", "away"]) {
        const dir = ne ? (ne.team === side ? Math.sign(ne.net) : -Math.sign(ne.net)) : (side === "home" ? 1 : -1);
        const attacking = side === att;
        skaters[side].forEach((p, i) => {
          let tx, ty;
          const lane = [-18, 18, -6, 6, 0][i];
          if (attacking) { tx = px + dir * [-4, -4, -26, -26, 6][i]; ty = py * 0.4 + lane * 1.2; }
          else { tx = px + dir * [-10, -10, 14, 14, -2][i] * -1; ty = py * 0.5 + lane; }
          tx = Math.max(-96, Math.min(96, tx)); ty = Math.max(-38, Math.min(38, ty));
          const f = Math.min(1, dt * 2.2);
          p.x += (tx - p.x) * f; p.y += (ty - p.y) * f;
        });
      }
    }

    function stateAt(time) {                        // score, shots, power play, last caption for a seek
      const st = {home: 0, away: 0, sh: 0, sa: 0, pp: null, cap: ""};
      for (const e of evs) {
        if (e.t > time) break;
        if (e.type === "goal") { st[e.team] += 1; e.team === "home" ? st.sh++ : st.sa++; }
        if (e.type === "shot") e.team === "home" ? st.sh++ : st.sa++;
        if (e.type === "penalty") st.pp = /offsetting/.test(e.detail || "") ? null : {against: e.team, until: e.t + 120};
        if (e.type === "goal" && st.pp && e.team !== st.pp.against && e.t <= st.pp.until) st.pp = null;
      }
      if (st.pp && st.pp.until < time) st.pp = null;
      return st;
    }

    function clockText(time) {
      if (time >= reg && evs.some((e) => e.period === "SO")) return "Shootout";
      const p = Math.floor(time / 1200) + 1;
      if (p <= 3) { const r = 1200 - (time % 1200); return `${["1st", "2nd", "3rd"][p - 1]} ${Math.floor(r / 60)}:${String(Math.floor(r % 60)).padStart(2, "0")}`; }
      const r = Math.max(0, 3600 + 300 - time);
      return `OT ${Math.floor(r / 60)}:${String(Math.floor(r % 60)).padStart(2, "0")}`;
    }

    function caption(e) {
      const who = esc(e.shooter || "");
      const side = e.team === "home" ? data.home.abbr : data.away.abbr;
      switch (e.type) {
        case "goal": return `<b>GOAL ${side}</b> ${who}${e.assists && e.assists.length ? ` (${e.assists.map(esc).join(", ")})` : " (unassisted)"}${e.empty_net ? " into the empty net" : ""}`;
        case "shot": return `${side} shot: ${who}, saved by ${esc(e.goalie || "the goalie")}`;
        case "miss": return `${side}: ${who} misses the net`;
        case "block": return `${side}: ${who}'s shot blocked by ${esc(e.blocker || "a defender")}`;
        case "penalty": return `Penalty ${side}: ${who}, ${esc(e.detail)}`;
        case "so_goal": return `Shootout: ${who} (${side}) scores`;
        case "so_miss": return `Shootout: ${who} (${side}) is stopped`;
      }
      return "";
    }

    function draw(prog) {
      ctx.clearRect(0, 0, cv.width, cv.height);
      rink();
      if (chart) for (const e of evs) {             // the shot chart so far
        if (e.t > t || e === holdEv || !["goal", "shot", "miss", "block"].includes(e.type)) continue;
        const c = e.team === "home" ? data.home.color : data.away.color;
        ctx.globalAlpha = e.type === "goal" ? 0.95 : 0.45;
        if (e.type === "goal") { dot(e.x, e.y, 2.2, c); ctx.strokeStyle = "#111"; ctx.lineWidth = 0.4 * k(); ctx.stroke(); }
        else if (e.type === "shot") dot(e.x, e.y, 1.2, c);
        else { ctx.strokeStyle = c; ctx.lineWidth = 0.5 * k(); const s = 1.1;
          ctx.beginPath(); ctx.moveTo(X(e.x - s), Y(e.y - s)); ctx.lineTo(X(e.x + s), Y(e.y + s));
          ctx.moveTo(X(e.x - s), Y(e.y + s)); ctx.lineTo(X(e.x + s), Y(e.y - s)); ctx.stroke(); }
        ctx.globalAlpha = 1;
      }
      for (const side of ["away", "home"]) {        // skaters
        const c = data[side].color;
        skaters[side].forEach((p) => { dot(p.x, p.y, 1.9, c); ctx.strokeStyle = "#fff"; ctx.lineWidth = 0.35 * k(); ctx.stroke(); });
      }
      for (const d of [-1, 1]) {                    // goalies follow the puck a little
        const side = d * (Math.floor(Math.min(t, reg - 1) / 1200) === 1 ? -1 : 1) > 0 ? "away" : "home";
        dot(d * 86, Math.max(-3, Math.min(3, puck.y * 0.08)), 2.1, data[side].color);
      }
      if (holdEv && holdEv.type !== "penalty") {   // the shooter
        const c = holdEv.team === "home" ? data.home.color : data.away.color;
        dot(holdEv.x, holdEv.y, 2.3, c); ctx.strokeStyle = "#111"; ctx.lineWidth = 0.5 * k(); ctx.stroke();
        label(holdEv.x, holdEv.y + 1.5, (holdEv.shooter || "").split(" ").slice(-1)[0], "#111");
        if (holdEv.type === "block" && prog > 0.4) label(holdEv.bx, holdEv.by + 1.5, (holdEv.blocker || "").split(" ").slice(-1)[0], "#555");
      }
      dot(puck.x, puck.y, 1.0, "#111");
      if (holdEv && holdEv.type === "goal" && prog > 0.2) {
        ctx.fillStyle = "rgba(255,215,0,.18)"; ctx.fillRect(0, 0, cv.width, cv.height);
        ctx.font = `bold ${8 * k()}px system-ui, sans-serif`; ctx.textAlign = "center";
        ctx.fillStyle = holdEv.team === "home" ? data.home.color : data.away.color;
        ctx.fillText("GOAL", cv.width / 2, cv.height * 0.3);
      }
    }

    function hud() {
      const st = stateAt(t);
      q("home").textContent = st.home; q("away").textContent = st.away;
      q("clock").textContent = clockText(t);
      q("sog").textContent = `SOG ${st.sa}-${st.sh}`;
      q("pp").textContent = st.pp ? `PP ${st.pp.against === "home" ? data.away.abbr : data.home.abbr} ${Math.ceil((st.pp.until - t) / 60 * 10) / 10 > 0 ? `${Math.floor((st.pp.until - t) / 60)}:${String(Math.floor((st.pp.until - t) % 60)).padStart(2, "0")}` : ""}` : "";
      a("seek").value = Math.floor(t);
    }

    function seek(time) {
      t = Math.max(0, Math.min(end, time));
      idx = evs.findIndex((e) => e.t > t); if (idx < 0) idx = evs.length;
      const prev = evs[idx - 1];
      puck = prev ? {x: prev.type === "goal" ? 0 : prev.x, y: prev.type === "goal" ? 0 : prev.y} : {x: 0, y: 0};
      from = {...puck}; hold = 0; holdEv = null;
      q("cap").innerHTML = prev ? caption(prev) : "&nbsp;";
      hud(); draw(0);
    }

    function frame(now) {
      if (!document.body.contains(cv)) return;     // left the page: stop
      const dt = last == null ? 0 : Math.min(0.1, (now - last) / 1000);
      last = now;
      if (playing) {
        if (holdEv) {                              // an event is being shown: the clock waits
          hold += dt;
          const fast = Math.min(1, 60 / speed);    // at high speed only goals and penalties linger
          const big = holdEv.type === "goal" || holdEv.type.startsWith("so") || holdEv.type === "penalty";
          const dur = (PAUSE[holdEv.type] || 0.5) * (big ? Math.max(0.6, fast) : fast);
          const prog = Math.min(1, hold / (TRAVEL * (big ? 1 : fast)));
          const to = holdEv.type === "block" ? {x: holdEv.bx, y: holdEv.by} : holdEv.type === "miss" ? {x: holdEv.mx, y: holdEv.my}
            : holdEv.type === "penalty" ? {x: holdEv.x, y: holdEv.y} : {x: holdEv.net, y: 0};
          puck = {x: holdEv.x + (to.x - holdEv.x) * prog, y: holdEv.y + (to.y - holdEv.y) * prog};
          if (holdEv.type === "penalty") puck = {...from};
          targets(dt * 0.3);
          draw(prog);
          if (hold >= dur) {
            if (holdEv.type === "goal" || holdEv.type.startsWith("so")) puck = {x: 0, y: 0};   // faceoff at centre
            from = {...puck}; holdEv = null; hold = 0;
          }
        } else {
          const ne = nextEv();
          const step = dt * speed;
          if (ne && t + step >= ne.t) {
            t = ne.t; idx += 1; holdEv = ne; hold = 0; from = {...puck};
            q("cap").innerHTML = caption(ne);
            hud();
          } else {
            t = Math.min(end, t + step);
            if (ne) {                              // carry the puck toward where the next chance comes from
              const span = Math.max(1, ne.t - (evs[idx - 1] ? evs[idx - 1].t : 0));
              const f = Math.min(1, 1 - (ne.t - t) / span);
              const via = {x: ne.type === "penalty" ? puck.x : ne.x * 0.5, y: ne.type === "penalty" ? puck.y : ne.y * -0.6};
              const g = f < 0.5 ? f * 2 : (f - 0.5) * 2;
              const p0 = f < 0.5 ? from : via, p1 = f < 0.5 ? via : (ne.type === "penalty" ? via : {x: ne.x, y: ne.y});
              const wob = Math.sin(t / 7) * 4;
              puck = {x: p0.x + (p1.x - p0.x) * g, y: p0.y + (p1.y - p0.y) * g + wob * (1 - Math.abs(2 * g - 1))};
              if (f >= 0.5 && g < 0.02) from = {...via};
            }
            targets(dt);
            hud(); draw(0);
            if (t >= end) { playing = false; a("play").textContent = "Replay"; }
          }
        }
      }
      requestAnimationFrame(frame);
    }

    a("play").addEventListener("click", () => {
      if (t >= end) seek(0);
      playing = !playing; a("play").textContent = playing ? "Pause" : "Play";
    });
    a("speed").addEventListener("change", (e) => (speed = +e.target.value));
    a("chart").addEventListener("change", (e) => { chart = e.target.checked; draw(0); });
    a("seek").addEventListener("input", (e) => seek(+e.target.value));
    a("next").addEventListener("click", () => { const g = evs.find((e) => e.t > t + 0.5 && (e.type === "goal" || e.type === "so_goal")); seek(g ? g.t - 12 : end); });
    a("prev").addEventListener("click", () => { const g = evs.filter((e) => e.t < t - 13 && (e.type === "goal" || e.type === "so_goal")).pop(); seek(g ? g.t - 12 : 0); });
    window.addEventListener("resize", () => { if (document.body.contains(cv)) { scale(); draw(0); } });
    scale(); seek(0); requestAnimationFrame(frame);
  }
  return {mount};
})();
