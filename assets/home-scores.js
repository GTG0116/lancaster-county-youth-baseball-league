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
      '<div class="space-y-1.5">' + row(g.away, g.awayScore, awayWin) + row(g.home, g.homeScore, homeWin) + '</div></div></div></div>';
  }

  /* The hero "Latest Result" highlight is a build-time snapshot; refresh it
     with the most recent published final so it never shows a stale score. */
  function heroCard() {
    var spans = document.querySelectorAll("span");
    for (var i = 0; i < spans.length; i++) {
      if ((spans[i].textContent || "").trim() === "Latest Result") {
        var header = spans[i].parentElement;            // header flex row
        return header ? header.parentElement : null;     // inner result card
      }
    }
    return null;
  }
  function teamRow(name, score, rec, dim) {
    var ini = String(name || "").slice(0, 2).toUpperCase() || "?";
    return '<div class="flex items-center justify-between"><div class="flex items-center gap-3">' +
      '<span class="flex h-10 w-10 items-center justify-center rounded-full bg-white/10 font-display text-sm font-700">' + L.esc(ini) + '</span>' +
      '<div><p class="font-semibold leading-tight">' + L.esc(name) + '</p>' +
      '<p class="text-xs text-white/45">' + L.esc(rec) + '</p></div></div>' +
      '<span class="font-display text-3xl font-700 tabular-nums ' + (dim ? "text-white/40" : "text-white") + '">' + score + '</span></div>';
  }
  function recStr(team, games) {
    var r = L.recordFor(team, games);
    return r.wins + "–" + r.losses + (r.ties ? "–" + r.ties : "");
  }
  function updateHero(g, games) {
    var host = heroCard();
    if (!host) return;
    var awayWin = g.awayScore > g.homeScore;
    var top = awayWin
      ? teamRow(g.away, g.awayScore, recStr(g.away, games), false)
      : teamRow(g.home, g.homeScore, recStr(g.home, games), false);
    var bot = awayWin
      ? teamRow(g.home, g.homeScore, recStr(g.home, games), true)
      : teamRow(g.away, g.awayScore, recStr(g.away, games), true);
    host.innerHTML =
      '<div class="flex items-center justify-between text-xs font-bold uppercase tracking-widest text-white/50"><span>Latest Result</span><span class="flex items-center gap-1.5 text-white/60">Final</span></div>' +
      '<div class="mt-5 space-y-4">' + top + bot + '</div>' +
      '<div class="mt-5 flex items-center justify-between border-t border-white/10 pt-4 text-xs text-white/50">' +
      '<span>' + L.esc(g.division + " · " + g.section + " · Final") + '</span>' +
      '<span class="truncate pl-3 text-right">' + L.esc(g.field || "") + '</span></div>';
  }

  function run() {
    L.load().then(function (data) {
      var today = new Date().toISOString().slice(0, 10);
      var games = data.scheduleGames || [];
      var finals = games.filter(function (g) { return L.isFinal(g) && g.date <= today; })
        .sort(function (a, b) { return (b.date + (b.time || "")).localeCompare(a.date + (a.time || "")); });
      if (!finals.length) return;
      updateHero(finals[0], games);
      var grid = findGrid();
      if (grid) grid.innerHTML = finals.slice(0, 6).map(function (g, i) { return card(g, i * 60); }).join("");
    }).catch(function () { /* leave the build-time snapshot in place */ });
  }

  if (document.readyState === "complete") setTimeout(run, 200);
  else window.addEventListener("load", function () { setTimeout(run, 200); });
})();
