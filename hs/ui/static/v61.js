"use strict";
// v61: the display currency (a Currency menu, the choice at the new-game screen and in Settings; docs/CURRENCY.md),
// tr() for words built in code, and the boot line.

// a word or phrase in the interface language (for text put together in code; the page walker does the rest)
const tr = (s) => { const T = Lang.tables(); return (T && T[0][s]) || s; };

const Currency = {
  order: ["USD", "CAD", "EUR", "GBP", "SEK", "NOK", "DKK", "CHF", "CZK", "PLN", "RUB", "AUD", "JPY"],
  label(c) { return `${c} · ${tr(FX.names[c])}`; },
  rate(c) {                                                 // "1 EUR = 92.33 RUB · 1 USD = 82.98 RUB"
    const f = (x) => x >= 100 ? x.toFixed(1) : x >= 10 ? x.toFixed(2) : x.toFixed(4);
    return c === "EUR" ? `1 EUR = ${f(FX.per_eur.USD)} USD` : c === "USD" ? `1 USD = ${f(1 / FX.per_eur.USD)} EUR`
      : `1 EUR = ${f(FX.per_eur[c])} ${c} · 1 USD = ${f(FX.per_eur[c] / FX.per_eur.USD)} ${c}`;
  },
  async set(c) {
    if (!FX.per_eur[c]) return;
    SETTINGS.currency = c;
    await saveSettings();
    try { sessionStorage.setItem("hmCurNote", c); } catch (e) { /* no storage */ }
    location.reload();                                      // every screen redraws in the new currency
  },
  note() {                                                  // after the reload: which currency, at what rate
    let c = null;
    try { c = sessionStorage.getItem("hmCurNote"); sessionStorage.removeItem("hmCurNote"); } catch (e) { /* no storage */ }
    if (c && FX.per_eur[c]) setTimeout(() => toast(`${tr("Amounts now in")} ${tr(FX.names[c])} (${curSym()}). ${tr("Reference rate")}: ${this.rate(c)} (${FX.date}).`), 1500);
  },
  table() {
    const rows = this.order.map((c) => `<tr class="${c === currencyCode() ? "mine" : ""}"><td><b>${c}</b></td><td>${esc(tr(FX.names[c]))}</td>
      <td class="num">${FX.per_eur[c]}</td><td class="num">${(FX.per_eur[c] / FX.per_eur.USD).toFixed(4)}</td></tr>`).join("");
    Modal.open(`<div class="win-title">${tr("Reference rates")}</div><div class="pad"><table class="dv-t"><tr><th></th><th></th><th class="num">${tr("Per euro")}</th><th class="num">${tr("Per US dollar")}</th></tr>${rows}</table>
      <p class="muted small">${tr("European Central Bank reference rates of")} ${FX.date}; ${tr("the rouble: the Bank of Russia's official rate of 13 November 2026 (the ECB no longer publishes one).")}
      ${tr("The game keeps NHL money in US dollars and European money in euros; only what you see is converted.")}</p></div>
      <div class="win-buttons"><button onclick="Modal.close()">${tr("Close")}</button></div>`, "win");
  },
  options(sel) { return this.order.map((c) => `<option value="${c}"${c === sel ? " selected" : ""}>${esc(this.label(c))}</option>`).join(""); },
};
(function currencyMenu() {
  const help = MENUS.findIndex((m) => m[0] === "Help");
  MENUS.splice(help < 0 ? MENUS.length : help, 0, ["Currency", Currency.order.map((c) => [Currency.label(c), () => Currency.set(c), () => currencyCode() === c])
    .concat(["-", [`${tr("Reference rates")}...`, () => Currency.table()]])]);
})();
// the top-level menu shows the currency in use
const menuBuildV61 = Menu.build.bind(Menu);
const currencyLabel = () => {
  const i = MENUS.findIndex((m) => m[0] === "Currency");
  const b = document.querySelector(`.mb-item[data-mi="${i}"] .mb-top`);
  if (b) { b.textContent = `${curSym()} ${currencyCode()}`; b.title = tr("Currency"); }
};
Menu.build = function () { menuBuildV61(); currencyLabel(); };
// (the menu is built before the settings arrive: label it again once they have)
const applySettingsV61 = applySettings;
applySettings = function (...a) { const r = applySettingsV61(...a); currencyLabel(); return r; };

// Settings: the currency next to the units
const settingsOpenV61 = Settings.open.bind(Settings);
Settings.open = async function (...a) {
  const r = await settingsOpenV61(...a);
  const units = document.querySelector('[data-set="units"]');
  if (units && !document.querySelector('[data-set="currency"]')) {
    units.closest("label").insertAdjacentHTML("afterend", `<label class="frow">${tr("Currency")} <select data-set="currency">${Currency.options(currencyCode())}</select></label>`);
    const s = document.querySelector('[data-set="currency"]');
    s.onchange = () => Currency.set(s.value);
  }
  return r;
};

// the new-game screen: the currency on the first step
const titleShowV61 = Title.show.bind(Title);
Title.show = async function (page = "home") {
  const r = await titleShowV61(page);
  if (page === "new" && document.querySelector("#su-name") && !document.querySelector("#su-cur")) {
    const age = document.querySelector("#su-age").closest("label");
    age.insertAdjacentHTML("afterend", `<label>${tr("Currency")} <select id="su-cur">${Currency.options(currencyCode())}</select></label>`);
    $("#su-cur").onchange = async (e) => { SETTINGS.currency = e.target.value; await saveSettings(); };
  }
  return r;
};

// the same new words in French
Object.assign(FR, {"Currency": "Devise", "US dollar": "Dollar américain", "Canadian dollar": "Dollar canadien", "Euro": "Euro",
  "Pound sterling": "Livre sterling", "Swedish krona": "Couronne suédoise", "Norwegian krone": "Couronne norvégienne", "Danish krone": "Couronne danoise",
  "Swiss franc": "Franc suisse", "Czech koruna": "Couronne tchèque", "Polish zloty": "Zloty polonais", "Russian rouble": "Rouble russe",
  "Australian dollar": "Dollar australien", "Japanese yen": "Yen japonais", "Transfers": "Transferts", "The board": "Le conseil",
  "European openings": "Postes en Europe", "Out on loan": "Prêtés", "Wants to stay": "Demande pour rester", "Wage": "Salaire", "Fee": "Indemnité",
  "Extend": "Prolonger", "Release": "Libérer", "Offers for your players": "Offres pour vos joueurs", "League table": "Classement",
  "No dealings yet.": "Aucune transaction pour l'instant.", "Русский": "Русский", "reputation": "réputation"});
FR["Open GitHub issue"] = "Ouvrir un ticket GitHub";
FR["Your club's games are played by the full game engine, as an NHL club's: your lines, special-teams units, goalies and tactics count exactly as they do in the NHL, and every game has a recap and a 2D replay. The rest of your league is played by the quicker results model."] =
  "Les matchs de votre club sont joués par le moteur de jeu complet, comme ceux d'un club de la LNH : vos trios, vos unités spéciales, vos gardiens et votre tactique comptent exactement comme dans la LNH, et chaque match a son résumé et sa reprise 2D. Le reste de votre ligue est joué par le modèle de résultats, plus rapide.";
FR["Your tactics work as they do for an NHL club; your players' fit is measured against the clubs of your own league."] =
  "Votre tactique fonctionne comme pour un club de la LNH; l'adéquation de vos joueurs est mesurée par rapport aux clubs de votre propre ligue.";
if (typeof RU !== "undefined") Object.assign(RU, {"reputation": "репутация", "Open GitHub issue": "Открыть задачу на GitHub",
  "Your club's games are played by the full game engine, as an NHL club's: your lines, special-teams units, goalies and tactics count exactly as they do in the NHL, and every game has a recap and a 2D replay. The rest of your league is played by the quicker results model.":
    "Матчи вашего клуба проводятся полным игровым движком, как у клуба НХЛ: ваши звенья, спецбригады, вратари и тактика действуют точно так же, как в НХЛ, и у каждого матча есть отчёт и 2D-повтор. Остальные матчи вашей лиги рассчитываются более быстрой моделью результатов.",
  "Your tactics work as they do for an NHL club; your players' fit is measured against the clubs of your own league.":
    "Ваша тактика работает так же, как у клуба НХЛ; соответствие игроков измеряется относительно клубов вашей собственной лиги."});

/* ---- the league the league screens show (v61): your own league first, the others on a picker ----
   Standings, Playoffs and Statistics open on the league of the club you run (the KHL for a KHL coach, the NHL for an
   NHL GM); the picker above them switches to any league played game by game, for this session. */
const LF = {
  data: null, lastHub: null,
  key() { return "hmLeague:" + ((STATE && (STATE.save || STATE.team)) || ""); },
  async load() { if (!this.data || this.dataFor !== this.key()) { this.data = await api("focusleagues"); this.dataFor = this.key(); } return this.data; },
  get() {
    let v = null;
    try { v = sessionStorage.getItem(this.key()); } catch (e) { /* no storage */ }
    const ok = v && this.data && this.data.leagues.some((l) => String(l.league_id) === v);
    return ok ? +v : (this.data ? this.data.mine : null);
  },
  set(lid) { try { sessionStorage.setItem(this.key(), String(lid)); } catch (e) { /* no storage */ } },
  isNhl(lid) { return this.data && lid === this.data.nhl; },
  bar(lid) {
    const L = this.data.leagues;
    return `<div class="toolbar lf-bar"><label>${tr("League")} <select id="lf-pick">${L.map((l) => `<option value="${l.league_id}"${l.league_id === lid ? " selected" : ""}>${esc(l.abbr)}${l.league_id === this.data.mine ? " ★" : ""}</option>`).join("")}</select></label>
      <span class="muted small">${lid === this.data.mine ? "" : `<a href="#" id="lf-mine">${tr("Back to your league")}</a>`}</span></div>`;
  },
  hook() {
    const s = $("#lf-pick"); if (s) s.onchange = () => { this.set(+s.value); Hub.season = ""; render(); };
    const m = $("#lf-mine"); if (m) m.onclick = (e) => { e.preventDefault(); this.set(this.data.mine); Hub.season = ""; render(); };
  },
  after() { const prev = AFTER; AFTER = () => { if (prev) prev(); LF.hook(); }; },
};
const lfLeague = async (lid, tab, title) => {
  const d = await api("worldleagues", {league: lid});
  const cur = d.leagues.find((l) => l.league_id === d.league_id) || {};
  return panel(`${esc(cur.name || "")}: ${tr(title)}`, WL.body(d, tab) + `<p class="muted small"><a href="#worldleagues/${lid}">${tr("Rules, leaders and champions")}</a></p>`);
};
["standings", "playoffs"].forEach((v) => {
  const orig = VIEWS[v];
  VIEWS[v] = async (...a) => {
    await LF.load();
    const lid = LF.get();
    const html = LF.isNhl(lid) ? await orig(...a) : await lfLeague(lid, v === "standings" ? "table" : "playoffs", v === "standings" ? "Standings" : "Playoffs");
    if (!LF.isNhl(lid)) AFTER = null;
    LF.after();
    return LF.bar(lid) + html;
  };
});
const statsV61 = VIEWS.stats;
VIEWS.stats = async (tab = "leaders") => {
  await LF.load();
  if (tab !== "history") {
    if (LF.lastHub !== null && Hub.league !== LF.lastHub) LF.set(+Hub.league);        // chosen on the hub's own picker
    const lid = String(LF.get());
    if (Hub.league !== lid) { Hub.league = lid; Hub.season = ""; Hub.team = ""; }
  }
  const html = await statsV61(tab);
  LF.lastHub = Hub.league;
  return html;
};
(function teamPageMenu() {                                   // Team > Team Page: your European club's page
  const tm = MENUS.find((m) => m[0] === "Team");
  const it = tm && tm[1].find((x) => Array.isArray(x) && x[0] === "Team Page");
  if (it) it[1] = () => { location.hash = `#team/${STATE.team_id || (STATE.eu_club && STATE.eu_club.club_id) || ""}`; };
})();
// screens about the NHL only: marked while you run a European club
const NHL_ONLY = new Set(["Playoff Odds", "Advanced Analytics", "Free Agent Centre", "Re-signing (Rights)", "Free Agency War Room", "Draft Room",
  "League Trades", "League History", "Records and Awards", "Transactions", "Awards Night", "Schedule by Day", "Injury Report", "Past Drafts",
  "Exhibitions", "All-Star Weekend", "Expansion", "Season Pages", "Offseason", "GM Leaders"]);
const menuShowV61 = Menu.show.bind(Menu);
Menu.show = function (i) {
  menuShowV61(i);
  if (!(STATE && STATE.eu_club)) return;
  const items = MENUS[i][1];
  document.querySelectorAll(`.mb-item[data-mi="${i}"] .mb-entry`).forEach((b) => {
    const it = items[+b.dataset.mj];
    if (Array.isArray(it) && NHL_ONLY.has(it[0])) b.insertAdjacentHTML("beforeend", '<i class="lf-nhl">NHL</i>');
  });
};
Object.assign(FR, {"League": "Ligue", "Back to your league": "Retour à votre ligue", "Rules, leaders and champions": "Règlements, meneurs et champions",
  "Standings": "Classement", "Playoffs": "Séries"});
if (typeof RU !== "undefined") Object.assign(RU, {"League": "Лига", "Back to your league": "Вернуться к своей лиге",
  "Rules, leaders and champions": "Регламент, лидеры и чемпионы", "Standings": "Турнирная таблица", "Playoffs": "Плей-офф"});

Object.assign(FR, {"Amounts now in": "Montants maintenant en", "Reference rate": "Taux de référence", "Reference rates": "Taux de référence",
  "Per euro": "Par euro", "Per US dollar": "Par dollar américain", "European Central Bank reference rates of": "Taux de référence de la Banque centrale européenne du",
  "the rouble: the Bank of Russia's official rate of 13 November 2026 (the ECB no longer publishes one).": "le rouble : le taux officiel de la Banque de Russie du 13 novembre 2026 (la BCE n'en publie plus).",
  "The game keeps NHL money in US dollars and European money in euros; only what you see is converted.": "Le jeu garde l'argent de la LNH en dollars américains et celui de l'Europe en euros; seul l'affichage est converti."});
if (typeof RU !== "undefined") Object.assign(RU, {"Amounts now in": "Суммы теперь в валюте", "Reference rate": "Справочный курс", "Reference rates": "Справочные курсы",
  "Per euro": "За евро", "Per US dollar": "За доллар США", "European Central Bank reference rates of": "Справочные курсы Европейского центрального банка на",
  "the rouble: the Bank of Russia's official rate of 13 November 2026 (the ECB no longer publishes one).": "рубль: официальный курс Банка России на 13 ноября 2026 года (ЕЦБ его больше не публикует).",
  "The game keeps NHL money in US dollars and European money in euros; only what you see is converted.": "Игра хранит деньги НХЛ в долларах США, а европейские — в евро; пересчитывается только отображение."});
Currency.note();

/* ---- boot (keep last) ---- */
if (Lang.get() !== "en") Lang.apply(document.body);
loadLogos().finally(() => bootApp());
