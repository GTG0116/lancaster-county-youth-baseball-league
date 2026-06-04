/* Matchups — head-to-head between any two teams, from the live JSON. */
(function () {
  "use strict";
  var L = window.LCYBL, esc = L.esc;
  var DATA = null;
  var $ = function (id) { return document.getElementById(id); };

  function allTeams() {
    var s = {};
    DATA.scheduleGames.forEach(function (g) { s[g.home] = 1; s[g.away] = 1; });
    return Object.keys(s).sort();
  }
  function isFinal(g) { return L.isFinal(g); }

  function h2hGames(a, b) {
    return DATA.scheduleGames.filter(function (g) {
      return (g.home === a && g.away === b) || (g.home === b && g.away === a);
    }).sort(function (x, y) { return (x.date + x.time).localeCompare(y.date + y.time); });
  }

  function teamCard(name) {
    var th = L.theme(name);
    var rec = L.recordFor(name, DATA.scheduleGames);
    return '<div class="lc-card" style="overflow:hidden;flex:1;min-width:220px">' +
      '<div style="background:' + th.primary + ';color:' + th.onPrimary + ';padding:16px 18px;display:flex;align-items:center;gap:12px">' +
      '<span class="lc-team-badge" style="width:46px;height:46px;border-radius:12px;font-size:18px;background:' + th.secondary + ';color:' + th.primary + '">' + esc(initials(name)) + '</span>' +
      '<div><div style="font-weight:900;font-size:18px">' + esc(name) + '</div><div style="opacity:.85;font-size:12px;font-weight:600">' + esc(th.town) + (th.school ? ' · ' + esc(th.school) : '') + '</div></div></div>' +
      '<div class="lc-card-pad"><div style="font-size:26px;font-weight:900;color:var(--navy-900)">' + rec.wins + '-' + rec.losses + (rec.ties ? '-' + rec.ties : '') + '</div>' +
      '<div class="lc-muted" style="font-size:12px;text-transform:uppercase;letter-spacing:.08em">Overall record</div>' +
      '<a class="lc-link" style="display:inline-block;margin-top:10px" href="' + L.url('/teams/') + '?team=' + encodeURIComponent(name) + '">View team page →</a></div></div>';
  }

  function gameCard(g) {
    var fin = isFinal(g);
    var homeWin = fin && g.homeScore > g.awayScore, awayWin = fin && g.awayScore > g.homeScore;
    var chip = fin ? '<span class="lc-chip lc-chip-final">Final</span>' : '<span class="lc-chip lc-chip-sched">' + esc(g.time || 'TBD') + '</span>';
    function side(nm, sc, win) {
      var th = L.theme(nm);
      return '<div class="lc-row' + (win ? ' win' : '') + '"><span class="lc-team"><span class="lc-dot" style="background:' + th.primary + '"></span><span class="nm">' + esc(nm) + '</span></span>' + (fin ? '<span class="lc-score">' + sc + '</span>' : '') + '</div>';
    }
    return '<div class="lc-game"><div class="lc-game-date"><span class="mo">' + L.mon(g.date) + '</span><span class="dy">' + L.day(g.date) + '</span><span class="wd">' + L.dow(g.date) + '</span></div>' +
      '<div class="lc-game-body"><div class="lc-game-head"><span class="lc-chip">' + esc(L.ageSec(g)) + '</span>' + chip + '</div>' +
      side(g.home, g.homeScore, homeWin) + side(g.away, g.awayScore, awayWin) + '</div></div>';
  }

  function render() {
    var a = $("teamA").value.trim(), b = $("teamB").value.trim();
    var host = $("lc-result");
    if (!a || !b) { host.innerHTML = '<div class="lc-empty">Choose two teams above to see the matchup.</div>'; return; }
    if (a === b) { host.innerHTML = '<div class="lc-empty">Pick two different teams.</div>'; return; }

    var games = h2hGames(a, b);
    var aw = 0, bw = 0, tw = 0;
    games.forEach(function (g) {
      if (!isFinal(g)) return;
      var aScore = g.home === a ? g.homeScore : g.awayScore;
      var bScore = g.home === b ? g.homeScore : g.awayScore;
      if (aScore > bScore) aw++; else if (bScore > aScore) bw++; else tw++;
    });

    var html = '<div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:22px">' + teamCard(a) + teamCard(b) + '</div>';
    html += '<div class="lc-card lc-card-pad lc-center" style="margin-bottom:22px"><div style="font-size:13px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);font-weight:700;margin-bottom:6px">Head to head</div>' +
      '<div style="font-size:30px;font-weight:900;color:var(--navy-900)">' + esc(a) + ' ' + aw + ' — ' + bw + ' ' + esc(b) + (tw ? ' <span class="lc-muted">(' + tw + ' tie' + (tw > 1 ? 's' : '') + ')</span>' : '') + '</div></div>';

    html += '<h2>Games between them</h2>';
    html += games.length ? '<div class="lc-games cols-2">' + games.map(gameCard).join("") + '</div>' : '<div class="lc-empty">These teams haven\'t played each other this season.</div>';
    host.innerHTML = html;
  }

  function initials(name) {
    var p = String(name).trim().split(/\s+/);
    return (p.length === 1 ? p[0].slice(0, 2) : p[0][0] + p[1][0]).toUpperCase();
  }

  L.load().then(function (d) {
    DATA = d;
    $("lc-loading").style.display = "none";
    $("teamlist").innerHTML = allTeams().map(function (t) { return '<option value="' + esc(t) + '">'; }).join("");
    $("teamA").addEventListener("change", render);
    $("teamB").addEventListener("change", render);
    $("teamA").addEventListener("input", render);
    $("teamB").addEventListener("input", render);
    // deep link ?a=&b=
    var p = new URLSearchParams(location.search);
    if (p.get("a")) $("teamA").value = p.get("a");
    if (p.get("b")) $("teamB").value = p.get("b");
    render();
  }).catch(function () { $("lc-loading").textContent = "Could not load data. Please refresh."; });
})();
