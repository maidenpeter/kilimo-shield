/* AgroShield photo app service worker: the app opens with no signal. Served at /app/sw.js (scope /app).
 * Pages and the farm list: network first, falling back to the last copy. Styles, scripts and icons: cache first.
 * Photos are never sent from here: the page's own queue (IndexedDB) sends them when there is signal.
 */
var CACHE = "agroshield-app-v1";
var SHELL = ["/app", "/app/weather", "/app/consent", "/app/manifest.webmanifest", "/static/tokens.css", "/static/app.css",
             "/static/app/photoapp.css", "/static/app/photoapp.js", "/static/app/icon-192.png",
             "/static/brand/agroshield-mark.svg"];

self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) {
    return Promise.all(SHELL.map(function (u) { return c.add(u).catch(function () {}); }));
  }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener("fetch", function (e) {
  var req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) { return; }
  if (url.pathname.indexOf("/static/") === 0) {
    e.respondWith(caches.match(req).then(function (hit) {
      return hit || fetch(req).then(function (res) {
        var copy = res.clone();
        caches.open(CACHE).then(function (c) { c.put(req, copy); });
        return res;
      });
    }));
    return;
  }
  if (url.pathname === "/app" || url.pathname.indexOf("/app/") === 0) {
    e.respondWith(fetch(req).then(function (res) {
      if (res.ok && !res.redirected) {
        var copy = res.clone();
        caches.open(CACHE).then(function (c) { c.put(req, copy); });
      }
      return res;
    }).catch(function () { return caches.match(req).then(function (hit) { return hit || caches.match("/app"); }); }));
  }
});
