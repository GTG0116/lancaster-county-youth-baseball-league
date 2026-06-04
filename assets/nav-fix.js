/* Hard-navigation shim for the built (Next.js) pages.

   Several data-driven pages (schedule, calendar, matchups, teams) were rebuilt
   as standalone live pages that read the latest published JSON. Next.js's
   client router would otherwise intercept in-app link clicks and try to render
   a stale cached route instead of loading those real documents. This shim
   forces a normal full-page navigation for internal links so every page loads
   fresh. It only affects link clicks; buttons, dropdowns and hashes are left
   alone. */
(function () {
  "use strict";
  document.addEventListener("click", function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
    if (!a) return;
    if (a.target && a.target !== "_self") return;
    if (a.hasAttribute("download")) return;
    var href = a.getAttribute("href");
    if (!href || href[0] === "#" || /^(mailto:|tel:|javascript:)/i.test(href)) return;
    var url;
    try { url = new URL(href, location.href); } catch (err) { return; }
    if (url.origin !== location.origin) return;           // external → leave it
    if (url.pathname === location.pathname && url.hash) return; // same-page anchor
    e.preventDefault();
    e.stopImmediatePropagation();
    location.assign(url.href);
  }, true);
})();
