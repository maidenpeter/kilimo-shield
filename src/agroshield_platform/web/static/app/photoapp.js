/* AgroShield crop photo app (milestone 8). Plain JavaScript, no build step, works on low-end Android browsers.
 *
 * Offline first: a photo is saved to this phone (IndexedDB) the moment it is taken, with its farm, growth stage,
 * time and GPS. The queue is sent whenever there is signal (on load, when the phone comes back online, every
 * minute). Each photo has its own id, so a photo sent twice is stored once. The server checks and stores it
 * without EXIF or GPS in the file.
 */
(function () {
  "use strict";
  var DB = "agroshield-photos", STORE = "queue", SENT_KEY = "agroshield-sent", ME_KEY = "agroshield-me";
  var me = null, current = null, stream = null, fix = null, watch = null, syncing = false;
  var $ = function (id) { return document.getElementById(id); };

  // ------------------------------------------------------------------ IndexedDB queue
  function db() {
    return new Promise(function (ok, fail) {
      var r = indexedDB.open(DB, 1);
      r.onupgradeneeded = function () { r.result.createObjectStore(STORE, {keyPath: "client_id"}); };
      r.onsuccess = function () { ok(r.result); };
      r.onerror = function () { fail(r.error); };
    });
  }
  function tx(mode, fn) {
    return db().then(function (d) {
      return new Promise(function (ok, fail) {
        var t = d.transaction(STORE, mode), out = fn(t.objectStore(STORE));
        t.oncomplete = function () { ok(out && out.result !== undefined ? out.result : out); };
        t.onerror = function () { fail(t.error); };
      });
    });
  }
  var queueAll = function () { return tx("readonly", function (s) { return s.getAll(); }); };
  var queuePut = function (item) { return tx("readwrite", function (s) { return s.put(item); }); };
  var queueDel = function (id) { return tx("readwrite", function (s) { return s.delete(id); }); };
  window.agroshieldQueue = {all: queueAll, put: queuePut, del: queueDel};   // for tests and support

  function newId() {
    var a = new Uint8Array(16);
    (window.crypto || window.msCrypto).getRandomValues(a);
    return Array.prototype.map.call(a, function (b) { return ("0" + b.toString(16)).slice(-2); }).join("");
  }
  function words(k) { return (me && me.words && me.words[k]) || k; }
  function esc(t) { var d = document.createElement("div"); d.textContent = t == null ? "" : String(t); return d.innerHTML; }

  // ------------------------------------------------------------------ farms
  function loadMe() {
    return fetch("/app/api/me", {credentials: "same-origin"}).then(function (r) {
      if (r.status === 401) { location.href = "/app/login"; throw new Error("signed out"); }
      return r.json();
    }).then(function (j) {
      try { localStorage.setItem(ME_KEY, JSON.stringify(j)); } catch (e) {}
      return j;
    }).catch(function () {
      try { return JSON.parse(localStorage.getItem(ME_KEY)); } catch (e) { return null; }
    });
  }

  function renderFarms() {
    var box = $("farms");
    if (!me) { box.innerHTML = '<p class="muted">' + esc(words("offline")) + "</p>"; return; }
    $("hello").textContent = (me.user.lang === "sw" ? "Habari " : "Hello ") + me.user.name;
    box.innerHTML = me.plots.map(function (p, i) {
      var stages = p.stages.map(function (s) {
        var cls = s.done ? "ok" : (s.due ? "warn" : "");
        var state = s.done ? words("done") : (s.due ? words("due") : words("not_yet"));
        return '<li><span class="chip ' + cls + '">' + esc(state) + "</span> " + esc(s.label) + "</li>";
      }).join("");
      return '<article class="card fa-farm"><h2 class="mt-0">' + esc(p.label) + "</h2>" +
        '<p class="muted">' + esc(p.acres) + " acres" + (p.season ? " &middot; " + esc(p.season) : "") + "</p>" +
        '<ul class="fa-stages">' + stages + "</ul>" +
        '<button class="btn big" type="button" data-farm="' + i + '">' + esc(words("take")) + "</button></article>";
    }).join("") || '<p class="muted">No farm is linked to you yet. Ask your SACCO officer.</p>';
    Array.prototype.forEach.call(box.querySelectorAll("[data-farm]"), function (b) {
      b.addEventListener("click", function () { openCamera(me.plots[+b.getAttribute("data-farm")]); });
    });
  }

  // ------------------------------------------------------------------ camera, GPS and the ghost of the last photo
  function openCamera(plot) {
    current = plot;
    $("cam-farm").textContent = plot.label;
    var due = plot.stages.filter(function (s) { return s.due; })[0];
    if (due) { $("stage").value = due.key; }
    $("camera").hidden = false;
    $("camera").scrollIntoView();
    $("preview").hidden = true;
    startGps();
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      navigator.mediaDevices.getUserMedia({video: {facingMode: "environment"}, audio: false}).then(function (s) {
        stream = s;
        $("video").srcObject = s;
        $("video").hidden = false;
        $("video").play();
        $("snap").hidden = false;
        $("pick-label").hidden = true;
      }).catch(function () { /* no camera permission: the file picker opens the phone's camera instead */ });
    }
  }

  function closeCamera() {
    if (stream) { stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; }
    if (watch !== null && navigator.geolocation) { navigator.geolocation.clearWatch(watch); watch = null; }
    $("video").hidden = true; $("snap").hidden = true; $("pick-label").hidden = false;
    $("ghost").hidden = true; $("ghost-note").hidden = true;
    $("camera").hidden = true;
    current = null;
  }

  function startGps() {
    fix = null;
    if (!navigator.geolocation) { $("gps").textContent = "No GPS on this phone."; return; }
    watch = navigator.geolocation.watchPosition(function (pos) {
      var first = !fix;
      fix = {lat: pos.coords.latitude, lon: pos.coords.longitude, accuracy_m: Math.round(pos.coords.accuracy)};
      $("gps").textContent = "GPS: within " + fix.accuracy_m + " m";
      if (first) { loadGhost(); }
    }, function () { $("gps").textContent = "Location is off. Turn it on so the photo can be checked."; },
    {enableHighAccuracy: true, maximumAge: 30000, timeout: 30000});
  }

  function loadGhost() {
    if (!current || !navigator.onLine || !me) { return; }
    fetch("/app/api/ghost/" + encodeURIComponent(current.id), {
      method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": me.csrf},
      body: JSON.stringify(fix ? {lat: fix.lat, lon: fix.lon} : {})
    }).then(function (r) { return r.ok ? r.json() : {}; }).then(function (g) {
      if (g && g.url) { $("ghost").src = g.url; $("ghost").hidden = false; $("ghost-note").hidden = false; }
    }).catch(function () {});
  }

  function toJpeg(source, w, h) {
    var max = 1600, k = Math.min(1, max / Math.max(w, h));
    var c = document.createElement("canvas");
    c.width = Math.round(w * k); c.height = Math.round(h * k);
    c.getContext("2d").drawImage(source, 0, 0, c.width, c.height);
    return new Promise(function (ok) { c.toBlob(ok, "image/jpeg", 0.85); });
  }

  function snap() {
    var v = $("video");
    toJpeg(v, v.videoWidth, v.videoHeight).then(keep);
  }

  function picked(ev) {
    var f = ev.target.files && ev.target.files[0];
    if (!f) { return; }
    var img = new Image();
    img.onload = function () { toJpeg(img, img.naturalWidth, img.naturalHeight).then(keep); URL.revokeObjectURL(img.src); };
    img.onerror = function () { keep(f); };      // the server reads it instead
    img.src = URL.createObjectURL(f);
    ev.target.value = "";
  }

  function keep(blob) {
    if (!current) { return; }
    var item = {client_id: newId(), plot_id: current.id, farm: current.label, stage: $("stage").value,
                stage_label: $("stage").selectedOptions[0].textContent, taken_at: new Date().toISOString(),
                lat: fix && fix.lat, lon: fix && fix.lon, accuracy_m: fix && fix.accuracy_m, blob: blob, error: null};
    $("preview").src = URL.createObjectURL(blob);
    $("preview").hidden = false;
    queuePut(item).then(function () { closeCamera(); return showQueue(); }).then(sync);
  }

  // ------------------------------------------------------------------ the queue and sending
  function showQueue() {
    return queueAll().then(function (items) {
      $("q-count").textContent = items.length;
      $("queue").innerHTML = items.map(function (it) {
        return "<li><b>" + esc(it.farm) + "</b>, " + esc(it.stage_label) + " &middot; " +
          esc(new Date(it.taken_at).toLocaleString()) +
          (it.error ? '<div class="err">' + esc(it.error) + ' <button class="btn ghost small" type="button" data-drop="' +
            esc(it.client_id) + '">Remove</button></div>' : "") + "</li>";
      }).join("");
      Array.prototype.forEach.call($("queue").querySelectorAll("[data-drop]"), function (b) {
        b.addEventListener("click", function () { queueDel(b.getAttribute("data-drop")).then(showQueue); });
      });
      var sent = [];
      try { sent = JSON.parse(localStorage.getItem(SENT_KEY)) || []; } catch (e) {}
      $("sent").innerHTML = sent.slice(0, 10).map(function (r) {
        return "<li><b>" + esc(r.farm) + "</b>, " + esc(r.stage) + ": " + esc(r.text) + "</li>";
      }).join("");
    });
  }

  function remember(item, text) {
    var sent = [];
    try { sent = JSON.parse(localStorage.getItem(SENT_KEY)) || []; } catch (e) {}
    sent.unshift({farm: item.farm, stage: item.stage_label, text: text});
    try { localStorage.setItem(SENT_KEY, JSON.stringify(sent.slice(0, 30))); } catch (e) {}
  }

  function sendOne(item) {
    var fd = new FormData();
    fd.append("file", item.blob, "photo.jpg");
    fd.append("plot_id", item.plot_id);
    fd.append("meta", JSON.stringify({client_id: item.client_id, stage: item.stage, taken_at: item.taken_at,
                                      lat: item.lat, lon: item.lon, accuracy_m: item.accuracy_m}));
    return fetch("/app/api/photos", {method: "POST", body: fd, credentials: "same-origin",
                                     headers: {"X-CSRF-Token": me.csrf}})
      .then(function (r) {
        if (r.status === 401 || r.status === 403) { throw {signin: true}; }
        return r.json().then(function (j) { return {status: r.status, body: j}; });
      }).then(function (res) {
        if (res.status === 200 && res.body.ok) {
          var b = res.body;
          var text = b.status === "rejected" ? "not accepted: " + b.reason
            : "received " + b.ref + (b.on_schedule ? "" : " (outside this stage's dates)") +
              (b.flags && b.flags.length ? "; to check: " + b.flags.join(", ") : "");
          remember(item, text);
          return queueDel(item.client_id);
        }
        item.error = (res.body && res.body.error) || "Could not send.";
        return queuePut(item);                    // a problem the farmer can see; kept until removed
      });
  }

  function sync() {
    if (syncing || !navigator.onLine || !me || !me.csrf) { return Promise.resolve(); }
    syncing = true;
    return queueAll().then(function (items) {
      var chain = Promise.resolve();
      items.filter(function (i) { return !i.error; }).forEach(function (it) {
        chain = chain.then(function () { return sendOne(it); });
      });
      return chain;
    }).catch(function (e) {
      if (e && e.signin) { location.href = "/app/login"; }
    }).then(function () { syncing = false; return showQueue(); });
  }
  window.agroshieldSync = sync;

  // ------------------------------------------------------------------ start
  $("snap").addEventListener("click", snap);
  $("pick").addEventListener("change", picked);
  $("cancel").addEventListener("click", closeCamera);
  addEventListener("online", function () { loadMe().then(function (j) { if (j) { me = j; } sync(); }); });
  loadMe().then(function (j) { me = j; renderFarms(); return showQueue(); }).then(sync);
  setInterval(sync, 60000);
})();
