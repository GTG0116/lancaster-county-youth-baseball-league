/* Homepage "Latest Scores" — replace the build-time snapshot with live data so
   the home page always reflects the latest published results. Matches the
   existing card styling and drops field locations. */
(function () {
  "use strict";
  var L = window.LCYBL;
  if (!L) return;
  var MON = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"];

  function findGrid() {
    // Anchor on an existing score card and take the *nearest* grid around it.
    // (The section's outer grid also wraps "Latest News", so we must not target
    // that one or we'd wipe the news column and the headings.)
    var hs = document.querySelectorAll("h2");
    for (var i = 0; i < hs.length; i++) {
      if (!/latest scores/i.test(hs[i].textContent || "")) continue;
      var sec = hs[i].closest("section") || hs[i].parentElement;
      if (!sec) continue;
      var card = sec.querySelector(".card-hover");
      var grid = card && card.closest ? card.closest(".grid") : null;
      // only accept a grid that is scoped to scores (no news content)
      if (grid && !/latest news/i.test(grid.textContent || "")) return grid;
    }
    return null;
  }

  function card(g, delay) {
    var d = L.toDate(g.date);
    var mo = MON[d.getMonth()], day = d.getDate();
    var homeWin = g.homeScore > g.awayScore, awayWin = g.awayScore > g.homeScore;
    function row(name, score, win) {
      return '<div class="flex items-center justify-between gap-3">' +
        '<span class="truncate text-sm font-bold text-navy-900">' + L.esc(name) + '</span>' +
        '<span class="min-w-[1.75rem] rounded-md px-1.5 py-0.5 text-center text-sm font-bold tabular-nums ' +
        (win ? 'bg-navy-900 text-white' : 'bg-navy-100 text-navy-700') + '">' + score + '</span></div>';
    }
    return '<div style="transition-delay:' + (delay) + 'ms"><div class="card-hover flex items-stretch overflow-hidden">' +
      '<div class="flex w-16 shrink-0 flex-col items-center justify-center bg-navy-900 px-2 py-3 text-white">' +
      '<span class="text-[10px] font-bold uppercase tracking-wider text-brick-300">' + mo + '</span>' +
      '<span class="font-display text-2xl font-700 leading-none">' + day + '</span></div>' +
      '<div class="flex flex-1 flex-col gap-2 p-4"><div class="flex items-center justify-between">' +
      '<span class="chip bg-sand-200 text-navy-700">' + L.esc(L.ageSec(g)) + '</span>' +
      '<span class="chip bg-navy-100 text-navy-700">Final</span></div>' +
      '<div class="space-y-1.5">' + row(g.home, g.homeScore, homeWin) + row(g.away, g.awayScore, awayWin) + '</div></div></div></div>';
  }

  function run() {
    var grid = findGrid();
    if (!grid) return;
    L.load().then(function (data) {
      var finals = (data.scheduleGames || []).filter(L.isFinal)
        .sort(function (a, b) { return (b.date + (b.time || "")).localeCompare(a.date + (a.time || "")); });
      if (!finals.length) return;
      grid = findGrid();
      if (!grid) return;
      grid.innerHTML = finals.slice(0, 6).map(function (g, i) { return card(g, i * 60); }).join("");
    }).catch(function () { /* leave the build-time snapshot in place */ });
  }

  if (document.readyState === "complete") setTimeout(run, 200);
  else window.addEventListener("load", function () { setTimeout(run, 200); });
})();
