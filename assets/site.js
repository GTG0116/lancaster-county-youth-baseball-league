/* ==========================================================================
   LCYBL shared client runtime for the live, data-driven pages.

   Responsibilities:
     - work out the deploy base path (works at a sub-path or a custom domain),
     - inject the site header + footer so the live pages match the built pages,
     - load /data/generated/lcybl-official-data.json (always the latest),
     - map every team to its town's high-school colors (Teams mode theming),
     - small date / record helpers shared across pages.
   ========================================================================== */
(function () {
  "use strict";

  var L = (window.LCYBL = window.LCYBL || {});

  /* ---- base path -------------------------------------------------------- */
  // Each live page sets window.LCYBL_PAGE (e.g. "teams"). We strip that
  // trailing segment so the same code works under /lancaster-county-.../ on
  // GitHub Pages and at the root of a custom domain.
  var page = window.LCYBL_PAGE || "";
  var B = location.pathname.replace(new RegExp("/" + page + "/?$"), "");
  if (B === location.pathname) B = location.pathname.replace(/\/[^/]*$/, "");
  B = B.replace(/\/$/, "");
  L.base = B;
  L.url = function (p) { return B + p; };

  /* ---- escaping --------------------------------------------------------- */
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  L.esc = esc;

  /* ---- dates ------------------------------------------------------------ */
  var MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  var DOW = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
  // ISO "2026-04-13" -> local Date (no timezone drift)
  function toDate(iso) {
    if (!iso) return null;
    var p = String(iso).split("-");
    if (p.length !== 3) return new Date(iso);
    return new Date(+p[0], +p[1] - 1, +p[2]);
  }
  L.toDate = toDate;
  L.mon = function (iso) { var d = toDate(iso); return d ? MON[d.getMonth()] : ""; };
  L.day = function (iso) { var d = toDate(iso); return d ? d.getDate() : ""; };
  L.dow = function (iso) { var d = toDate(iso); return d ? DOW[d.getDay()] : ""; };
  L.longDate = function (iso) {
    var d = toDate(iso); if (!d) return "";
    return DOW[d.getDay()] + ", " + MON[d.getMonth()] + " " + d.getDate();
  };
  L.todayISO = function () {
    var d = new Date();
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  };

  /* ---- division / section helpers -------------------------------------- */
  // section is stored as "Section 3" (games) or 3 (standings); show "Sec 3".
  L.secShort = function (s) {
    var n = L.secNum(s);
    return n != null ? "Sec " + n : String(s || "");
  };
  // extract the section number from "Section 3", "Sec 3" or 3
  L.secNum = function (s) {
    if (s == null) return null;
    var m = String(s).match(/\d+/);
    return m ? parseInt(m[0], 10) : null;
  };
  L.ageSec = function (g) { return g.division + " · " + L.secShort(g.section); };

  /* ======================================================================
     Team -> town high-school colors.
     Matched by team-name prefix. { primary, secondary } where primary is the
     dominant school color. Unmapped teams fall back to league navy.
     ====================================================================== */
  var TEAM_THEMES = [
    // order matters: more specific patterns first
    { re: /^(mt |manheim twp|mt\b|mt$)/i,                      town: "Manheim Township", school: "Blue Streaks",        primary: "#14387a", secondary: "#ffffff" },
    { re: /^manheim/i,                                          town: "Manheim Central",  school: "Barons",             primary: "#6b1f2a", secondary: "#f2a900" },
    { re: /^(e-?town|elizabethtown)/i,                          town: "Elizabethtown",    school: "Bears",              primary: "#7c2230", secondary: "#939598" },
    { re: /^warwick/i,                                          town: "Warwick / Lititz", school: "Warriors",           primary: "#00529b", secondary: "#f4c20d" },
    { re: /^hempfield/i,                                        town: "Hempfield",        school: "Black Knights",      primary: "#1a1a1a", secondary: "#c8a951" },
    { re: /^mountville/i,                                       town: "Mountville",       school: "Hempfield SD",       primary: "#8b1a1a", secondary: "#d4af37" },
    { re: /^(ls |l-?s\b|lampeter)/i,                            town: "Lampeter-Strasburg", school: "Pioneers",         primary: "#b1242d", secondary: "#111111" },
    { re: /(\bpm\b|penn manor)/i,                               town: "Penn Manor",       school: "Comets",             primary: "#003da5", secondary: "#ffffff" },
    { re: /^(cv |conestoga valley)/i,                           town: "Conestoga Valley", school: "Buckskins",          primary: "#00693e", secondary: "#ffd200" },
    { re: /^(pv |pequea valley)/i,                              town: "Pequea Valley",    school: "Braves",             primary: "#b01e28", secondary: "#14224b" },
    { re: /^cocalico/i,                                         town: "Cocalico",         school: "Eagles",             primary: "#c8102e", secondary: "#111111" },
    { re: /^donegal/i,                                          town: "Donegal",          school: "Indians",            primary: "#00573f", secondary: "#ffc72c" },
    { re: /^garden spot/i,                                      town: "Garden Spot / ELANCO", school: "Spartans",       primary: "#003594", secondary: "#ffc72c" },
    { re: /^ephrata/i,                                          town: "Ephrata",          school: "Mountaineers",       primary: "#6e2233", secondary: "#b5b7b9" },
    { re: /^ce?dar crest/i,                                     town: "Cedar Crest",      school: "Falcons",            primary: "#006341", secondary: "#ffffff" },
    { re: /^solanco/i,                                          town: "Solanco",          school: "Golden Mules",       primary: "#a86b00", secondary: "#111111" },
    { re: /^octorara/i,                                         town: "Octorara",         school: "Braves",             primary: "#d2491c", secondary: "#111111" },
    { re: /^columbia/i,                                         town: "Columbia",         school: "Crimson Tide",       primary: "#9e1b32", secondary: "#c0c0c0" },
    { re: /^lanc.*mennonite|lancaster mennonite/i,              town: "Lancaster Mennonite", school: "Blazers",         primary: "#1f3a93", secondary: "#ffd200" },
    { re: /^st\.? ?leo/i,                                       town: "St. Leo the Great", school: "Crusaders",         primary: "#1d4e89", secondary: "#ffcc00" },
    { re: /^lititz/i,                                           town: "Lititz",           school: "",                   primary: "#14387a", secondary: "#c8102e" },
    { re: /^(lanc jr|lanc rec|conoy|ctyaa)|tornado/i,           town: "Lancaster Rec",    school: "Tornadoes",          primary: "#c8102e", secondary: "#14224b" },
  ];
  var FALLBACK = { town: "Lancaster County", school: "", primary: "#061a33", secondary: "#c8102e" };

  function readableText(hex) {
    var h = hex.replace("#", "");
    if (h.length === 3) h = h.split("").map(function (c) { return c + c; }).join("");
    var r = parseInt(h.substr(0, 2), 16), g = parseInt(h.substr(2, 2), 16), b = parseInt(h.substr(4, 2), 16);
    var lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    return lum > 0.6 ? "#0f172a" : "#ffffff";
  }
  L.theme = function (team) {
    var t = FALLBACK, name = String(team || "");
    for (var i = 0; i < TEAM_THEMES.length; i++) {
      if (TEAM_THEMES[i].re.test(name)) { t = TEAM_THEMES[i]; break; }
    }
    return {
      town: t.town, school: t.school,
      primary: t.primary, secondary: t.secondary,
      onPrimary: readableText(t.primary),
      onSecondary: readableText(t.secondary),
    };
  };
  L.initials = function (name) {
    var m = String(name || "").replace(/^[A-Z]{1,2}-?\s+/, function (s) { return s; });
    var parts = String(name || "").trim().split(/\s+/).slice(0, 2);
    return parts.map(function (p) { return p[0]; }).join("").toUpperCase() || "?";
  };

  /* ---- data load -------------------------------------------------------- */
  L.load = function () {
    var u = B + "/data/generated/lcybl-official-data.json?v=" + Date.now();
    return fetch(u, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  };

  /* ---- a game counts as a played result only with a real score ---------- */
  // 0–0 "finals" are unplayed placeholders in the source data; never a result.
  L.isFinal = function (g) {
    return g.status === "final" && g.homeScore != null && g.awayScore != null &&
      !(g.homeScore === 0 && g.awayScore === 0);
  };

  /* ---- record from games (fallback when no standings row) --------------- */
  L.recordFor = function (team, games) {
    var w = 0, l = 0, t = 0;
    games.forEach(function (g) {
      if (!L.isFinal(g)) return;
      var isHome = g.home === team, isAway = g.away === team;
      if (!isHome && !isAway) return;
      var us = isHome ? g.homeScore : g.awayScore;
      var them = isHome ? g.awayScore : g.homeScore;
      if (us > them) w++; else if (us < them) l++; else t++;
    });
    return { wins: w, losses: l, ties: t };
  };

  /* ======================================================================
     Chrome: header + footer (mirrors the built marketing pages).
     ====================================================================== */
  var LOGO =
    '<svg viewBox="0 0 48 48" class="h-11 w-11" aria-hidden="true"><circle cx="24" cy="24" r="22" fill="#fff" stroke="#0a2342" stroke-width="2.5"></circle><path d="M14 8 C19 14 19 34 14 40 M34 8 C29 14 29 34 34 40" fill="none" stroke="#c8102e" stroke-width="2" stroke-linecap="round"></path><g stroke="#c8102e" stroke-width="1.4" stroke-linecap="round"><path d="M13.6 11.5 L17.2 8.9 M15.4 17.7 L19 15.1 M16 25.3 L19.6 22.7 M15.4 32.9 L19 30.3 M13.6 39.1 L17.2 36.5"></path><path d="M34.4 11.5 L30.8 8.9 M32.6 17.7 L29 15.1 M32 25.3 L28.4 22.7 M32.6 32.9 L29 30.3 M34.4 39.1 L30.8 36.5"></path></g></svg>';
  var BRAND =
    '<span class="flex items-center gap-3 "><span class="relative inline-flex h-11 w-11 shrink-0 items-center justify-center">' + LOGO +
    '</span><span class="flex flex-col leading-none"><span class="font-display text-lg font-700 uppercase tracking-tight text-white">Lancaster County</span><span class="font-display text-sm font-500 uppercase tracking-[0.2em] text-brick-300">Youth Baseball</span></span></span>';

  var MENU = [
    { label: "Compete", items: [
      ["schedule/", "Schedule &amp; Scores", "Game times, results, and matchups"],
      ["standings/", "Standings", "Division records and rankings"],
      ["teams/", "Teams", "Pick a team &mdash; record, next &amp; past games"],
      ["matchups/", "Matchups", "Head-to-head between any two teams"],
      ["tournaments/", "Tournaments", "LNP, All-Star &amp; club tournaments"],
    ]},
    { label: "League", items: [
      ["divisions/", "Divisions", "10U, 12U and 14U age groups"],
      ["clubs/", "Member Clubs", "The 25+ clubs that make up LCYBL"],
      ["fields/", "Field Locations", "Where the games are played"],
    ]},
    { label: "About", items: [
      ["about/", "Our History", "74 years of Lancaster baseball"],
      ["calendar/", "Calendar", "Schedule by month"],
    ]},
  ];

  function chevron() {
    return '<svg fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24" class="h-4 w-4 transition group-hover:rotate-180"><path d="m6 9 6 6 6-6"></path></svg>';
  }
  function desktopNav() {
    var html = '<nav class="hidden items-center gap-1 lg:flex">';
    MENU.forEach(function (grp) {
      html += '<div class="group relative"><button class="flex items-center gap-1 rounded-full px-4 py-2 text-sm font-semibold uppercase tracking-wide text-white/85 transition hover:bg-white/10 hover:text-white">' + grp.label + chevron() + '</button>';
      html += '<div class="invisible absolute left-1/2 top-full w-72 -translate-x-1/2 pt-3 opacity-0 transition-all duration-200 group-hover:visible group-hover:opacity-100"><div class="overflow-hidden rounded-2xl border border-navy-100 bg-white p-2 shadow-lift">';
      grp.items.forEach(function (it) {
        html += '<a class="block rounded-xl px-4 py-3 transition hover:bg-sand-200" href="' + B + '/' + it[0] + '"><span class="block text-sm font-bold text-navy-900">' + it[1] + '</span><span class="mt-0.5 block text-xs text-navy-500">' + it[2] + '</span></a>';
      });
      html += '</div></div></div>';
    });
    html += '<a class="ml-3 btn-primary !px-5 !py-2.5" href="' + B + '/schedule/">Scores</a></nav>';
    return html;
  }
  function mobileNav() {
    var html = '<div class="overflow-hidden border-t border-white/10 bg-navy-900 lg:hidden max-h-0 transition-[max-height] duration-300" data-lc-mobile><nav class="container-page flex flex-col gap-5 py-6">';
    MENU.forEach(function (grp) {
      html += '<div><p class="mb-2 text-xs font-bold uppercase tracking-[0.25em] text-brick-300">' + grp.label + '</p><div class="flex flex-col">';
      grp.items.forEach(function (it) {
        html += '<a class="rounded-lg px-3 py-2.5 text-base font-semibold text-white/90 hover:bg-white/10" href="' + B + '/' + it[0] + '">' + it[1] + '</a>';
      });
      html += '</div></div>';
    });
    html += '<a class="btn-primary mt-2 w-full" href="' + B + '/schedule/">Schedule &amp; Scores</a></nav></div>';
    return html;
  }
  function header() {
    return '<header class="sticky top-0 z-50 transition-all duration-300 bg-navy-900"><div class="container-page flex h-[68px] items-center justify-between"><a class="group" aria-label="LCYBL home" href="' + B + '/">' + BRAND + '</a>' +
      desktopNav() +
      '<button class="rounded-full p-2 text-white lg:hidden" aria-label="Open menu" data-lc-toggle><svg fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24" class="h-7 w-7"><path d="M4 6h16M4 12h16M4 18h16"></path></svg></button></div>' +
      mobileNav() + '</header>';
  }

  function footer() {
    var cols = MENU.map(function (grp) {
      var lis = grp.items.map(function (it) {
        return '<li><a class="text-sm text-white/65 transition hover:text-white" href="' + B + '/' + it[0] + '">' + it[1] + '</a></li>';
      }).join("");
      return '<div><h4 class="text-sm font-bold uppercase tracking-[0.2em] text-brick-300">' + grp.label + '</h4><ul class="mt-4 space-y-2.5">' + lis + '</ul></div>';
    }).join("");
    return '<footer class="bg-navy-950 text-white/80"><div class="stitch"></div><div class="container-page grid gap-12 py-14 md:grid-cols-2 lg:grid-cols-4"><div class="lg:col-span-1">' + BRAND +
      '<p class="mt-5 max-w-xs text-sm leading-relaxed text-white/60">Travel baseball for the youth of Lancaster County since 1952. Run by volunteers, for the kids of Lancaster County.</p></div>' +
      cols +
      '</div><div class="border-t border-white/10"><div class="container-page space-y-4 py-7 text-sm text-white/55"><p class="leading-relaxed"><span class="font-semibold text-white/80">Unofficial fan project.</span> A modernized recreation of the Lancaster County Youth Baseball League website, built by a league player. Not affiliated with, endorsed by, or operated by the LCYBL. Official info: <a href="https://lancoyouthbaseball.org/" target="_blank" rel="noopener noreferrer" class="font-semibold text-brick-300 underline-offset-2 hover:underline">lancoyouthbaseball.org</a>.</p><p class="text-white/45">Recreation © 2026 · Team names, schedules and standings belong to the LCYBL and its member clubs.</p></div></div></footer>';
  }

  L.mountChrome = function () {
    var h = document.querySelector("[data-lc-header]");
    if (h) h.innerHTML = header();
    var f = document.querySelector("[data-lc-footer]");
    if (f) f.innerHTML = footer();
    // mobile toggle
    var btn = document.querySelector("[data-lc-toggle]");
    var menu = document.querySelector("[data-lc-mobile]");
    if (btn && menu) {
      btn.addEventListener("click", function () {
        var open = menu.style.maxHeight && menu.style.maxHeight !== "0px";
        menu.style.maxHeight = open ? "0px" : menu.scrollHeight + "px";
      });
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", L.mountChrome);
  } else {
    L.mountChrome();
  }
})();
