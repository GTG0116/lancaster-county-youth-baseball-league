/* Calendar — month grid of games, each labeled with age group + section. */
(function () {
  "use strict";
  var L = window.LCYBL, esc = L.esc;
  var DATA = null, view = null, selDay = null;
  var f = { div: "All", sec: "All" };
  var $ = function (id) { return document.getElementById(id); };
  var DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  var MON = ["January","February","March","April","May","June","July","August","September","October","November","December"];

  function uniq(key) { var s = {}; DATA.scheduleGames.forEach(function (g) { s[g[key]] = 1; }); return Object.keys(s).sort(); }
  function isFinal(g) { return L.isFinal(g); }

  function filtered() {
    return DATA.scheduleGames.filter(function (g) {
      if (f.div !== "All" && g.division !== f.div) return false;
      if (f.sec !== "All" && g.section !== f.sec) return false;
      return true;
    });
  }
  function gamesByDay() {
    var map = {};
    filtered().forEach(function (g) { (map[g.date] = map[g.date] || []).push(g); });
    Object.keys(map).forEach(function (k) { map[k].sort(function (a, b) { return (a.time || "").localeCompare(b.time || ""); }); });
    return map;
  }

  function pills(host, values, current, onPick, fmt) {
    host.innerHTML = values.map(function (v) {
      return '<button class="lc-pill" aria-pressed="' + (v === current ? "true" : "false") + '">' + (fmt ? fmt(v) : v) + '</button>';
    }).join("");
    Array.prototype.forEach.call(host.children, function (b, i) { b.onclick = function () { onPick(values[i]); }; });
  }

  function evLabel(g) {
    var who = esc(g.away) + " @ " + esc(g.home);
    if (isFinal(g)) return '<span class="lc-ev final" title="' + who + '"><span class="ag">' + esc(L.ageSec(g)) + '</span> ' + esc(g.away) + ' ' + g.awayScore + '–' + g.homeScore + ' ' + esc(g.home) + '</span>';
    return '<span class="lc-ev" title="' + who + '"><span class="ag">' + esc(L.ageSec(g)) + '</span> ' + who + '</span>';
  }

  function render() {
    var y = view.getFullYear(), m = view.getMonth();
    $("cal-title").textContent = MON[m] + " " + y;
    $("cal-dow").innerHTML = DOW.map(function (d) { return '<div class="lc-caldow">' + d + '</div>'; }).join("");

    var byDay = gamesByDay();
    var first = new Date(y, m, 1);
    var start = new Date(y, m, 1 - first.getDay());      // back up to Sunday
    var today = L.todayISO();
    var html = "";
    for (var i = 0; i < 42; i++) {
      var d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
      var iso = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
      var out = d.getMonth() !== m;
      var evs = byDay[iso] || [];
      var cls = "lc-cell" + (out ? " out" : "") + (iso === today ? " today" : "");
      html += '<div class="' + cls + '" data-day="' + iso + '"><span class="dnum">' + d.getDate() + '</span>';
      evs.slice(0, 3).forEach(function (g) { html += evLabel(g); });
      if (evs.length > 3) html += '<span class="lc-more">+' + (evs.length - 3) + ' more</span>';
      html += '</div>';
    }
    $("cal-grid").innerHTML = html;
    Array.prototype.forEach.call($("cal-grid").children, function (cell) {
      cell.onclick = function () { selDay = cell.getAttribute("data-day"); showDay(selDay); };
    });
    if (selDay) showDay(selDay);
  }

  function showDay(iso) {
    var evs = (gamesByDay()[iso] || []);
    var host = $("cal-detail");
    if (!evs.length) { host.innerHTML = ""; return; }
    var cards = evs.map(function (g) {
      var fin = isFinal(g);
      var line = fin
        ? esc(g.away) + ' ' + g.awayScore + ' — ' + g.homeScore + ' ' + esc(g.home)
        : esc(g.away) + ' @ ' + esc(g.home);
      var chip = fin ? '<span class="lc-chip lc-chip-final">Final</span>' : '<span class="lc-chip lc-chip-sched">' + esc(g.time || "TBD") + '</span>';
      return '<div class="lc-game"><div class="lc-game-date"><span class="mo">' + L.mon(g.date) + '</span><span class="dy">' + L.day(g.date) + '</span></div>' +
        '<div class="lc-game-body"><div class="lc-game-head"><span class="lc-chip">' + esc(L.ageSec(g)) + '</span>' + chip + '</div>' +
        '<div style="font-weight:700;color:var(--navy-900)">' + line + '</div></div></div>';
    }).join("");
    host.innerHTML = '<h2>' + esc(L.longDate(iso)) + '</h2><div class="lc-games cols-2">' + cards + '</div>';
  }

  function buildFilters() {
    pills($("f-div"), ["All"].concat(uniq("division")), f.div, function (v) { f.div = v; buildFilters(); render(); });
    pills($("f-sec"), ["All"].concat(uniq("section")), f.sec, function (v) { f.sec = v; buildFilters(); render(); }, L.secShort);
  }

  function startMonth() {
    // first month that has games (>= today preferred), else current
    var dates = DATA.scheduleGames.map(function (g) { return g.date; }).sort();
    var today = L.todayISO();
    var pick = dates.filter(function (d) { return d >= today; })[0] || dates[dates.length - 1] || today;
    var p = pick.split("-");
    return new Date(+p[0], +p[1] - 1, 1);
  }

  L.load().then(function (d) {
    DATA = d;
    $("lc-loading").style.display = "none";
    view = startMonth();
    buildFilters();
    render();
    $("prev").onclick = function () { view = new Date(view.getFullYear(), view.getMonth() - 1, 1); render(); };
    $("next").onclick = function () { view = new Date(view.getFullYear(), view.getMonth() + 1, 1); render(); };
  }).catch(function () { $("lc-loading").textContent = "Could not load the calendar. Please refresh."; });
})();
