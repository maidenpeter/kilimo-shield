/* AgroShield page behaviour: navbar, account and developer dropdowns, mobile sheet, theme toggle,
   image fallbacks, and the submit guard. No framework; works without it (links and forms still work). */
(function () {
  "use strict";
  var doc = document, root = doc.documentElement;

  /* ---------- theme ---------- */
  var THEME_KEY = "agroshield-theme";
  function currentTheme() {
    var t = root.getAttribute("data-theme");
    if (t) return t;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function setTheme(t) {          // only an explicit choice is stored; otherwise the system setting is followed
    root.setAttribute("data-theme", t);
    try { localStorage.setItem(THEME_KEY, t); } catch (e) { /* private mode: still switches for this page */ }
    syncToggles(t);
  }
  function syncToggles(t) {
    doc.querySelectorAll("[data-theme-toggle]").forEach(function (b) {
      b.setAttribute("aria-pressed", t === "dark" ? "true" : "false");
      var l = b.querySelector("[data-theme-label]");
      if (l) l.textContent = t === "dark" ? "Light mode" : "Dark mode";
    });
  }

  /* ---------- dropdowns (click to open, Esc and outside click to close) ---------- */
  function closeDropdowns(except) {
    doc.querySelectorAll("[data-dropdown] > [aria-expanded='true']").forEach(function (btn) {
      if (btn !== except) { btn.setAttribute("aria-expanded", "false"); doc.getElementById(btn.getAttribute("aria-controls")).hidden = true; }
    });
  }

  /* ---------- mobile sheet ---------- */
  var sheet, backdrop, menuBtn, lastFocus;
  function focusables(el) {
    return Array.prototype.filter.call(el.querySelectorAll("a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex='-1'])"),
      function (x) { return x.offsetParent !== null; });
  }
  function openSheet() {
    lastFocus = doc.activeElement;
    sheet.hidden = false; backdrop.hidden = false;
    doc.body.classList.add("sheet-open");
    menuBtn.setAttribute("aria-expanded", "true");
    var f = focusables(sheet); if (f.length) f[0].focus();
  }
  function closeSheet(restore) {
    if (!sheet || sheet.hidden) return;
    sheet.hidden = true; backdrop.hidden = true;
    doc.body.classList.remove("sheet-open");
    menuBtn.setAttribute("aria-expanded", "false");
    if (restore !== false) (menuBtn || lastFocus).focus();
  }

  /* ---------- navbar collapse fallback: collapse whenever the links would not fit on one row ---------- */
  function fitNav() {
    var header = doc.querySelector("header.site"); if (!header) return;
    var nav = header.querySelector("nav.primary"); if (!nav) return;
    header.classList.remove("collapsed");
    var style = getComputedStyle(nav);
    if (style.display === "none") return;          // already collapsed by the role's breakpoint
    var bar = header.querySelector(".bar");
    if (nav.scrollWidth > nav.clientWidth + 1 || bar.scrollWidth > bar.clientWidth + 1) header.classList.add("collapsed");
  }

  doc.addEventListener("DOMContentLoaded", function () {
    var header = doc.querySelector("header.site");
    sheet = doc.getElementById("sheet"); backdrop = doc.querySelector(".sheet-backdrop"); menuBtn = doc.querySelector(".menu-btn");

    // theme toggle buttons
    syncToggles(currentTheme());
    doc.querySelectorAll("[data-theme-toggle]").forEach(function (b) {
      b.addEventListener("click", function () { setTheme(currentTheme() === "dark" ? "light" : "dark"); });
    });

    // dropdowns
    doc.querySelectorAll("[data-dropdown] > button[aria-controls]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        var open = btn.getAttribute("aria-expanded") === "true";
        closeDropdowns(btn);
        btn.setAttribute("aria-expanded", open ? "false" : "true");
        var panel = doc.getElementById(btn.getAttribute("aria-controls"));
        panel.hidden = open;
        if (!open) { var f = focusables(panel); if (f.length) f[0].focus(); }
      });
    });
    doc.addEventListener("click", function (e) {
      if (!e.target.closest || !e.target.closest("[data-dropdown]")) closeDropdowns();
    });

    // sheet
    if (menuBtn && sheet) {
      menuBtn.addEventListener("click", function () { sheet.hidden ? openSheet() : closeSheet(); });
      backdrop.addEventListener("click", function () { closeSheet(); });
      sheet.querySelectorAll("[data-close-sheet]").forEach(function (b) { b.addEventListener("click", function () { closeSheet(); }); });
      sheet.querySelectorAll("a[href]").forEach(function (a) { a.addEventListener("click", function () { closeSheet(false); }); });
      sheet.addEventListener("keydown", function (e) {
        if (e.key !== "Tab") return;
        var f = focusables(sheet); if (!f.length) return;
        var first = f[0], last = f[f.length - 1];
        if (e.shiftKey && doc.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && doc.activeElement === last) { e.preventDefault(); first.focus(); }
      });
    }
    doc.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      if (sheet && !sheet.hidden) { closeSheet(); return; }
      var open = doc.querySelector("[data-dropdown] > [aria-expanded='true']");
      if (open) { closeDropdowns(); open.focus(); }
    });
    window.addEventListener("resize", function () {
      if (sheet && !sheet.hidden && getComputedStyle(menuBtn).display === "none") closeSheet(false);
      fitNav();
    });

    // scrolled shadow
    if (header) {
      var onScroll = function () { header.classList.toggle("scrolled", window.scrollY > 4); };
      window.addEventListener("scroll", onScroll, { passive: true }); onScroll();
    }
    fitNav();
    if (doc.fonts && doc.fonts.ready) doc.fonts.ready.then(fitNav);

    // images: graceful fallback when a file fails to load
    doc.querySelectorAll(".media img").forEach(function (img) {
      var fail = function () { var m = img.closest(".media"); if (m) m.classList.add("failed"); };
      if (img.complete && img.naturalWidth === 0 && img.currentSrc) fail();
      img.addEventListener("error", fail);
    });

    // keyboard access to scrollable table boxes is via tabindex in the markup; label them for screen readers
    var seen = {};
    doc.querySelectorAll(".table-wrap:not([aria-label])").forEach(function (w, i) {
      var cap = w.querySelector("caption"), h = w.previousElementSibling;
      var name = (cap ? cap.textContent : (h && /^H[1-4]$/.test(h.tagName) ? h.textContent : "Table")).trim();
      seen[name] = (seen[name] || 0) + 1;                       // landmark names must be unique on the page
      w.setAttribute("aria-label", seen[name] > 1 ? name + " (" + seen[name] + ")" : name);
    });
  });

  /* ---------- submit guard: the tapped button says "Working..." and a second tap is ignored ---------- */
  doc.addEventListener("submit", function (e) {
    var f = e.target, b = e.submitter;
    if (f.dataset.busy) { e.preventDefault(); return; }
    f.dataset.busy = "1";
    if (b && b.tagName === "BUTTON") setTimeout(function () {      // after the form data (incl. this button) is taken
      b.dataset.label = b.textContent; b.textContent = "Working…"; b.setAttribute("aria-busy", "true"); b.classList.add("busy");
    }, 0);
    setTimeout(resetForms, 15000);
  });
  function resetForms() {
    doc.querySelectorAll("form[data-busy]").forEach(function (f) { delete f.dataset.busy; });
    doc.querySelectorAll("button.busy").forEach(function (b) {
      b.textContent = b.dataset.label; b.removeAttribute("aria-busy"); b.classList.remove("busy"); });
  }
  window.addEventListener("pageshow", resetForms);   // coming Back to a page must not leave it locked
})();
