/* Schedule & Scores — live, full schedule from the published JSON. */
(function () {
  "use strict";
  var L = window.LCYBL, esc = L.esc;
  var DATA = null;
  var f = { div: "All", sec: "All", team: "", when: "upcoming" };
  var $ = function (id) { return document.getElementById(id); };

  function uniq(key) {
    var s = {}; DATA.scheduleGames.forEach(function (g) { s[g[key]] = 1; });
    return Object.keys(s).sort();
  }
  function pills(host, values, current, onPick, fmt) {
    host.innerHTML = values.map(function (v) {
      return '<button class="lc-pill" aria-pressed="' + (v === current ? "true" : "false") + '">' + (fmt ? fmt(v) : v) + '</button>';
    }).join("");
    Array.prototype.forEach.call(host.children, function (b, i) { b.onclick = function () { onPick(values[i]); }; });
  }

  function isFinal(g) { return L.isFinal(g); }

  function gameCard(g) {
    var fin = isFinal(g);
    var homeWin = fin && g.homeScore > g.awayScore, awayWin = fin && g.awayScore > g.homeScore;
    var chip = fin ? '<span class="lc-chip lc-chip-final">Final</span>'
                   : '<span class="lc-chip lc-chip-sched">' + esc(g.time || "TBD") + '</span>';
    function side(name, score, win) {
      var th = L.theme(name);
      return '<div class="lc-row' + (win ? " win" : "") + '"><span class="lc-team"><span class="lc-dot" style="background:' + th.primary + '"></span>' +
        '<a class="nm" style="text-decoration:none" href="' + L.url("/teams/") + '?div=' + encodeURIComponent(g.division) + '&sec=' + encodeURIComponent(g.section) + '&team=' + encodeURIComponent(name) + '">' + esc(name) + '</a></span>' +
        (fin ? '<span class="lc-score">' + score + '</span>' : '') + '</div>';
    }
    return '<div class="lc-game"><div class="lc-game-date"><span class="mo">' + L.mon(g.date) + '</span><span class="dy">' + L.day(g.date) + '</span><span class="wd">' + L.dow(g.date) + '</span></div>' +
      '<div class="lc-game-body"><div class="lc-game-head"><span class="lc-chip">' + esc(L.ageSec(g)) + '</span>' + chip + '</div>' +
      side(g.away, g.awayScore, awayWin) + side(g.home, g.homeScore, homeWin) + '</div></div>';
  }

  function render() {
    var today = L.todayISO();
    var games = DATA.scheduleGames.filter(function (g) {
      if (f.div !== "All" && g.division !== f.div) return false;
      if (f.sec !== "All" && g.section !== f.sec) return false;
      if (f.team) { var q = f.team.toLowerCase(); if (g.home.toLowerCase().indexOf(q) < 0 && g.away.toLowerCase().indexOf(q) < 0) return false; }
      if (f.when === "upcoming") return !isFinal(g) && g.date >= today;
      return isFinal(g);
    });
    if (f.when === "results") games.sort(function (a, b) { return (b.date + b.time).localeCompare(a.date + a.time); });
    else games.sort(function (a, b) { return (a.date + a.time).localeCompare(b.date + b.time); });

    var host = $("lc-list");
    if (!games.length) { host.innerHTML = '<div class="lc-empty">No games match these filters.</div>'; return; }

    // group by date
    var html = "", curDate = null, bucket = [];
    function flush() {
      if (!bucket.length) return;
      html += '<h2 style="margin-top:8px">' + esc(L.longDate(curDate)) + '</h2><div class="lc-games cols-2">' + bucket.map(gameCard).join("") + '</div>';
      bucket = [];
    }
    games.forEach(function (g) { if (g.date !== curDate) { flush(); curDate = g.date; } bucket.push(g); });
    flush();
    host.innerHTML = html;
  }

  function buildFilters() {
    pills($("f-div"), ["All"].concat(uniq("division")), f.div, function (v) { f.div = v; buildFilters(); render(); });
    pills($("f-sec"), ["All"].concat(uniq("section")), f.sec, function (v) { f.sec = v; buildFilters(); render(); }, L.secShort);
    pills($("f-when"), ["upcoming", "results"], f.when, function (v) { f.when = v; buildFilters(); render(); }, function (v) { return v === "upcoming" ? "Upcoming" : "Results"; });
  }

  L.load().then(function (d) {
    DATA = d;
    $("lc-loading").style.display = "none";
    if (d.generatedAt) $("lc-updated").textContent = "Updated " + new Date(d.generatedAt).toLocaleString();
    $("f-team").addEventListener("input", function () { f.team = this.value.trim(); render(); });
    buildFilters();
    render();
  }).catch(function () { $("lc-loading").textContent = "Could not load schedule. Please refresh."; });
})();
