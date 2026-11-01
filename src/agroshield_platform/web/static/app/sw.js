/* AgroShield photo app service worker: the app opens with no signal. Served at /app/sw.js (scope /app).
 *
 * Styles, scripts and icons: served from the cache at once and refreshed in the background (only good answers
 * are kept). App pages: network first, falling back to the last good copy. Never cached: the farm list and
 * photos (/app/api/*, /app/photos/*), sign-in pages and redirects, so nothing personal is left for the next
 * person on a shared phone. Photos are never sent from here: the page's own queue sends them.
 */
var CACHE = "agroshield-app-v2";
var STATIC = ["/app/manifest.webmanifest", "/static/tokens.css", "/static/app.css", "/static/app/photoapp.css",
              "/static/app/photoapp.js", "/static/app/icon-192.png", "/static/brand/agroshield-mark.svg"];
var PAGES = ["/app", "/app/weather", "/app/consent"];

self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) {
    return Promise.all(STATIC.map(function (u) {
      return fetch(u).then(function (res) { if (res.ok) { return c.put(u, res); } }).catch(function () {});
    }));
  }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

function good(res) { return res && res.ok && res.type === "basic" && !res.redirected; }

self.addEventListener("fetch", function (e) {
  var req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) { return; }
  var path = url.pathname;
  if (path.indexOf("/static/") === 0 || path === "/app/manifest.webmanifest") {
    e.respondWith(caches.open(CACHE).then(function (c) {
      return c.match(req).then(function (hit) {
        var fresh = fetch(req).then(function (res) { if (good(res)) { c.put(req, res.clone()); } return res; });
        return hit || fresh;
      });
    }));
    return;
  }
  if (PAGES.indexOf(path) >= 0) {
    e.respondWith(fetch(req).then(function (res) {
      if (good(res)) {
        var copy = res.clone();
        caches.open(CACHE).then(function (c) { c.put(req, copy); });
      }
      return res;
    }).catch(function () {
      return caches.match(req).then(function (hit) { return hit || caches.match("/app"); });
    }));
  }
  // everything else (the API, photos, sign-in) goes straight to the network and is never stored
});
