/* Teams mode — sports-app style team pages themed to town HS colors. */
(function () {
  "use strict";
  var L = window.LCYBL, esc = L.esc;
  var DATA = null;
  var sel = { div: null, sec: null, team: null };

  var $ = function (id) { return document.getElementById(id); };

  function divisions() {
    var set = {};
    DATA.scheduleGames.forEach(function (g) { set[g.division] = 1; });
    return Object.keys(set).sort(function (a, b) { return parseInt(a) - parseInt(b); });
  }
  function sectionsFor(div) {
    var set = {};
    DATA.scheduleGames.forEach(function (g) { if (g.division === div) set[g.section] = 1; });
    return Object.keys(set).sort();
  }
  function teamsFor(div, sec) {
    var set = {};
    DATA.scheduleGames.forEach(function (g) {
      if (g.division === div && g.section === sec) { set[g.home] = 1; set[g.away] = 1; }
    });
    return Object.keys(set).sort();
  }
  function gamesFor(team, div, sec) {
    return DATA.scheduleGames.filter(function (g) {
      return g.division === div && g.section === sec && (g.home === team || g.away === team);
    }).sort(function (a, b) { return (a.date + a.time).localeCompare(b.date + b.time); });
  }
  // Some standings rows carry a trailing bracket label (e.g. "Hempfield White
  // National"). Work out the shared trailing token for a group so we can both
  // match and display clean team names.
  function bracketToken(grp) {
    var counts = {}, n = (grp.rows || []).length;
    (grp.rows || []).forEach(function (r) {
      var parts = String(r.team || "").trim().split(/\s+/);
      var last = parts[parts.length - 1];
      counts[last] = (counts[last] || 0) + 1;
    });
    var tok = null;
    Object.keys(counts).forEach(function (k) { if (counts[k] > n / 2) tok = k; });
    return tok;
  }
  function cleanTeam(name, tok) {
    if (tok) { var re = new RegExp("\\s+" + tok + "$"); return String(name).replace(re, ""); }
    return name;
  }
  function standingRowFor(team, div, sec) {
    var out = null;
    (DATA.standings || []).forEach(function (s) {
      if (s.division !== div) return;
      if (L.secNum(s.section) !== L.secNum(sec)) return;
      (s.groups || []).forEach(function (grp) {
        var tok = bracketToken(grp);
        (grp.rows || []).forEach(function (r, i) {
          if (r.team === team || cleanTeam(r.team, tok) === team) {
            out = { row: r, rank: i + 1, group: grp, label: s.label, token: tok };
          }
        });
      });
    });
    return out;
  }

  /* ---- pickers ---------------------------------------------------------- */
  function pill(label, pressed) {
    return '<button class="lc-pill" aria-pressed="' + (pressed ? "true" : "false") + '">' + label + '</button>';
  }
  function renderPickers() {
    var divs = divisions();
    if (!sel.div) sel.div = divs[0];
    $("lc-divs").innerHTML = divs.map(function (d) { return pill(d, d === sel.div); }).join("");
    Array.prototype.forEach.call($("lc-divs").children, function (b, i) {
      b.onclick = function () { sel.div = divs[i]; sel.sec = null; sel.team = null; renderPickers(); renderTeam(); };
    });

    var secs = sectionsFor(sel.div);
    if (!sel.sec || secs.indexOf(sel.sec) < 0) sel.sec = secs[0];
    $("lc-secs").innerHTML = secs.map(function (s) { return pill(L.secShort(s), s === sel.sec); }).join("");
    Array.prototype.forEach.call($("lc-secs").children, function (b, i) {
      b.onclick = function () { sel.sec = secs[i]; sel.team = null; renderPickers(); renderTeam(); };
    });

    var teams = teamsFor(sel.div, sel.sec);
    $("lc-teams").innerHTML = teams.map(function (t) {
      var th = L.theme(t);
      return '<button class="lc-pill" aria-pressed="' + (t === sel.team ? "true" : "false") + '">' +
        '<span class="lc-dot" style="background:' + th.primary + '"></span>' + esc(t) + '</button>';
    }).join("");
    Array.prototype.forEach.call($("lc-teams").children, function (b, i) {
      b.onclick = function () { sel.team = teams[i]; renderPickers(); renderTeam(); pushState(); scrollToTeam(); };
    });
  }

  function pushState() {
    try {
      var q = "?div=" + encodeURIComponent(sel.div) + "&sec=" + encodeURIComponent(sel.sec) + "&team=" + encodeURIComponent(sel.team || "");
      history.replaceState(null, "", q);
    } catch (e) {}
  }
  function scrollToTeam() {
    var el = $("lc-team"); if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  /* ---- game card -------------------------------------------------------- */
  function gameCard(g, team) {
    var final = L.isFinal(g);
    var isHome = g.home === team;
    var us = isHome ? g.homeScore : g.awayScore;
    var them = isHome ? g.awayScore : g.homeScore;
    var win = final && us > them, homeWin = final && g.homeScore > g.awayScore, awayWin = final && g.awayScore > g.homeScore;
    var chip = final
      ? '<span class="lc-chip lc-chip-final">Final</span>'
      : '<span class="lc-chip lc-chip-sched">' + esc(g.time || "TBD") + '</span>';
    function side(name, score, isWin) {
      var th = L.theme(name);
      return '<div class="lc-row' + (isWin ? " win" : "") + '">' +
        '<span class="lc-team"><span class="lc-dot" style="background:' + th.primary + '"></span><span class="nm">' + esc(name) + '</span></span>' +
        (final ? '<span class="lc-score">' + score + '</span>' : '') + '</div>';
    }
    return '<div class="lc-game"><div class="lc-game-date"><span class="mo">' + L.mon(g.date) + '</span><span class="dy">' + L.day(g.date) + '</span><span class="wd">' + L.dow(g.date) + '</span></div>' +
      '<div class="lc-game-body"><div class="lc-game-head"><span class="lc-chip">' + esc(L.ageSec(g)) + '</span>' + chip + '</div>' +
      side(g.home, g.homeScore, homeWin) + side(g.away, g.awayScore, awayWin) + '</div></div>';
  }

  /* ---- team view -------------------------------------------------------- */
  function renderTeam() {
    var host = $("lc-team");
    if (!sel.team) { host.innerHTML = ""; return; }
    var team = sel.team, th = L.theme(team);
    var games = gamesFor(team, sel.div, sel.sec);
    var today = L.todayISO();
    var finals = games.filter(function (g) { return L.isFinal(g); });
    var upcoming = games.filter(function (g) { return !L.isFinal(g) && g.date >= today; });
    var st = standingRowFor(team, sel.div, sel.sec);
    var rec = st ? { wins: st.row.wins, losses: st.row.losses, ties: st.row.ties } : L.recordFor(team, games);
    var pct = st ? st.row.pct : (rec.wins + rec.losses ? Math.round((rec.wins / (rec.wins + rec.losses)) * 1000) / 10 : 0);

    var themeVars = "--team-primary:" + th.primary + ";--team-secondary:" + th.secondary +
      ";--team-on-primary:" + th.onPrimary + ";--team-soft:" + softTint(th.primary) + ";";

    var next = upcoming[0];
    var prev = finals.slice().reverse(); // most recent first

    var sub = th.town + (th.school ? " · " + th.school : "");

    var html = '<div style="' + themeVars + '">';
    // hero
    html += '<section class="lc-team-hero"><div class="lc-wrap"><div class="lc-headrow">' +
      '<div class="lc-team-badge">' + esc(initialsOf(team)) + '</div>' +
      '<div><h1>' + esc(team) + '</h1><div class="sub">' + esc(sub) + ' · ' + esc(L.ageSec({ division: sel.div, section: sel.sec })) + '</div></div></div>' +
      '<div class="lc-statline">' +
        stat(rec.wins + "-" + rec.losses + (rec.ties ? "-" + rec.ties : ""), "Record") +
        stat(pct + "%", "Win Pct") +
        (st ? stat("#" + st.rank, "In Section") : "") +
        (st && st.row.points != null ? stat(st.row.points, "Points") : "") +
      '</div></div></section>';

    html += '<section class="lc-section"><div class="lc-wrap">';

    // next game
    html += '<div class="lc-next" style="margin-bottom:22px"><div class="lc-next-top">Next Game</div><div class="lc-next-body">';
    if (next) {
      var opp = next.home === team ? next.away : next.home;
      var ha = next.home === team ? "vs" : "at";
      html += '<div><div style="font-size:20px;font-weight:900;color:var(--navy-900)">' + esc(ha) + ' ' + esc(opp) + '</div>' +
        '<div class="lc-muted" style="margin-top:4px">' + esc(L.longDate(next.date)) + ' · ' + esc(next.time || "TBD") + '</div></div>' +
        '<a class="lc-btn" href="' + L.url("/schedule/") + '">Full schedule →</a>';
    } else {
      html += '<div class="lc-muted">No upcoming games — season complete or not yet scheduled.</div>';
    }
    html += '</div></div>';

    // grid: results + standings
    html += '<div style="display:grid;gap:22px" class="lc-cols">';
    // results
    html += '<div><h2>Recent Results</h2>';
    if (prev.length) {
      html += '<div class="lc-games">' + prev.slice(0, 12).map(function (g) { return gameCard(g, team); }).join("") + '</div>';
    } else {
      html += '<div class="lc-empty">No completed games yet.</div>';
    }
    html += '</div>';

    // upcoming list
    html += '<div><h2>Upcoming</h2>';
    if (upcoming.length) {
      html += '<div class="lc-games">' + upcoming.slice(0, 12).map(function (g) { return gameCard(g, team); }).join("") + '</div>';
    } else {
      html += '<div class="lc-empty">No upcoming games.</div>';
    }
    html += '</div></div>';

    // standings table for the section
    if (st) html += sectionTable(team, st);

    html += '</div></section></div>';
    host.innerHTML = html;
  }

  function sectionTable(team, st) {
    var rows = st.group.rows || [];
    var h = '<div style="margin-top:26px"><h2>' + esc(st.label || "Standings") + '</h2>' +
      '<div class="lc-card" style="overflow:hidden"><table class="lc-table"><thead><tr>' +
      '<th class="num">#</th><th>Team</th><th class="num">W</th><th class="num">L</th><th class="num">T</th><th class="num">Pct</th></tr></thead><tbody>';
    var tok = st.token;
    rows.forEach(function (r, i) {
      var disp = cleanTeam(r.team, tok);
      h += '<tr class="' + (disp === team ? "me" : "") + '"><td class="num">' + (i + 1) + '</td><td>' + esc(disp) + (r.champion ? ' 🏆' : '') + '</td>' +
        '<td class="num">' + r.wins + '</td><td class="num">' + r.losses + '</td><td class="num">' + (r.ties || 0) + '</td><td class="num">' + (r.pct != null ? r.pct : "—") + '</td></tr>';
    });
    h += '</tbody></table></div></div>';
    return h;
  }

  function stat(v, k) { return '<div class="lc-stat"><div class="v">' + esc(v) + '</div><div class="k">' + esc(k) + '</div></div>'; }
  function initialsOf(name) {
    var parts = String(name).trim().split(/\s+/);
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  function softTint(hex) {
    var h = hex.replace("#", "");
    if (h.length === 3) h = h.split("").map(function (c) { return c + c; }).join("");
    var r = parseInt(h.substr(0, 2), 16), g = parseInt(h.substr(2, 2), 16), b = parseInt(h.substr(4, 2), 16);
    return "rgba(" + r + "," + g + "," + b + ",0.08)";
  }

  /* ---- init ------------------------------------------------------------- */
  function readQuery() {
    var p = new URLSearchParams(location.search);
    if (p.get("div")) sel.div = p.get("div");
    if (p.get("sec")) sel.sec = p.get("sec");
    if (p.get("team")) sel.team = p.get("team");
  }

  L.load().then(function (d) {
    DATA = d;
    $("lc-loading").style.display = "none";
    readQuery();
    renderPickers();
    if (sel.team) { renderTeam(); }
  }).catch(function (e) {
    $("lc-loading").textContent = "Could not load league data. Please refresh.";
  });

  // add a couple of responsive grid columns for wide screens
  var s = document.createElement("style");
  s.textContent = "@media(min-width:900px){.lc-cols{grid-template-columns:1fr 1fr}}";
  document.head.appendChild(s);
})();
