(function () {
  "use strict";

  var stage = document.getElementById("stage");
  if (!stage || window.FestivalPopup) return;
  var qs = new URLSearchParams(location.search);
  if (qs.get("popup") === "0") {
    window.FestivalPopup = {
      isBusy: function () { return false; },
      pollNow: function () {},
      scheduleNavigation: function (url, delay) {
        setTimeout(function () { location.href = url; }, delay);
      }
    };
    return;
  }

  var POLL_MS = 10000;
  var MAX_QUEUED = 3;
  var L3_DWELL_MS = 5000;
  var L4_DWELL_MS = 17100;
  var isPreview = qs.get("preview") === "1";
  var cursorKey = "festival_seen_max" + (isPreview ? "_pv" : "");
  var queue = [];
  var queuedIds = new Set();
  var busy = false;
  var initialized = false;
  var polling = false;
  var pollTimer = null;
  var memoryCursor = 0;

  var TEAM_LOGOS = {
    "专治不服": "zhuanzhibufu", "多财多亿": "duocaiduoyi", "稻乐偲": "daolesi",
    "星星之火": "xingxingzhihuo", "行则将至": "xingzejiangzhi", "乘风": "chengfeng",
    "无名": "wuming"
  };

  stage.insertAdjacentHTML("beforeend",
    '<div class="festival-popup-lower" aria-live="polite"></div>' +
    '<div class="festival-popup-replay" aria-live="assertive">' +
      '<div class="festival-popup-replay-card">' +
        '<div class="festival-popup-replay-tag"></div>' +
        '<div class="festival-popup-replay-subject"></div>' +
        '<div class="festival-popup-replay-name"></div>' +
        '<div class="festival-popup-replay-amount"></div>' +
        '<div class="festival-popup-replay-detail"></div>' +
      '</div>' +
    '</div>');

  var lower = stage.querySelector(".festival-popup-lower");
  var replay = stage.querySelector(".festival-popup-replay");

  function text(value) {
    return String(value == null ? "" : value);
  }

  function money(value) {
    return "$" + Math.round(Number(value) || 0).toLocaleString("en-US");
  }

  function readCursor() {
    try {
      return Math.max(memoryCursor, parseInt(localStorage.getItem(cursorKey) || "0", 10) || 0);
    } catch (_error) {
      return memoryCursor;
    }
  }

  function hasStoredCursor() {
    try {
      return localStorage.getItem(cursorKey) !== null || initialized;
    } catch (_error) {
      return initialized;
    }
  }

  function acknowledge(eventId) {
    var id = Number(eventId) || 0;
    if (!id || id <= readCursor()) return;
    memoryCursor = id;
    try { localStorage.setItem(cursorKey, String(id)); } catch (_error) { /* 内存队列仍继续 */ }
  }

  function apiUrl(includeCursor) {
    var params = new URLSearchParams();
    if (qs.get("key")) params.set("key", qs.get("key"));
    if (isPreview) {
      params.set("date_from", qs.get("date_from") || "2026-06-01");
      params.set("date_to", qs.get("date_to") || "2026-07-29");
    } else {
      if (qs.get("date_from")) params.set("date_from", qs.get("date_from"));
      if (qs.get("date_to")) params.set("date_to", qs.get("date_to"));
      if (qs.get("source")) params.set("source", qs.get("source"));
    }
    if (includeCursor) params.set("after_id", String(readCursor()));
    return "/api/public/festival/headline?" + params.toString();
  }

  function makeFallback(event, className) {
    var fallback = document.createElement("span");
    fallback.className = className;
    fallback.textContent = text(event.subject_name).trim().slice(-1) || "✦";
    return fallback;
  }

  function subjectImagePath(event) {
    if (event.subject_type === "person") return "assets/avatars/" + encodeURIComponent(event.subject_id) + ".png";
    if (event.subject_type === "team" && TEAM_LOGOS[event.subject_name]) {
      return "assets/team-logos/" + TEAM_LOGOS[event.subject_name] + ".png";
    }
    return "";
  }

  function makeSubject(event, large) {
    var path = subjectImagePath(event);
    var imageClass = large ? "festival-popup-replay-icon" : "festival-popup-icon";
    var fallbackClass = large ? "festival-popup-replay-fallback" : "festival-popup-fallback";
    if (!path) return makeFallback(event, fallbackClass);
    var image = document.createElement("img");
    image.className = imageClass + (event.subject_type === "team" ? " is-team" : "");
    image.src = path;
    image.alt = "";
    image.onerror = function () { image.replaceWith(makeFallback(event, fallbackClass)); };
    return image;
  }

  function finish(event) {
    queuedIds.delete(String(event.id));
    acknowledge(event.id);
    busy = false;
    playNext();
  }

  function showLower(event) {
    lower.replaceChildren();
    var card = document.createElement("div");
    card.className = "festival-popup-lower-card";
    var tag = document.createElement("div");
    tag.className = "festival-popup-tag";
    tag.textContent = "⚡ " + text(event.label);
    var body = document.createElement("div");
    body.className = "festival-popup-body";
    var name = document.createElement("span");
    name.className = "festival-popup-name";
    name.textContent = text(event.subject_name);
    var detail = document.createElement("span");
    detail.className = "festival-popup-detail";
    detail.textContent = text(event.detail);
    card.appendChild(tag);
    body.appendChild(makeSubject(event, false));
    body.appendChild(name);
    body.appendChild(detail);
    if (event.amount) {
      var amount = document.createElement("span");
      amount.className = "festival-popup-amount";
      amount.textContent = money(event.amount);
      body.appendChild(amount);
    }
    card.appendChild(body);
    lower.appendChild(card);
    requestAnimationFrame(function () { card.classList.add("is-visible"); });
    setTimeout(function () { card.classList.remove("is-visible"); }, L3_DWELL_MS - 220);
    setTimeout(function () { lower.replaceChildren(); finish(event); }, L3_DWELL_MS);
  }

  function sprayFireworks() {
    replay.querySelectorAll(".festival-popup-firework").forEach(function (item) { item.remove(); });
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    for (var index = 0; index < 10; index += 1) {
      var firework = document.createElement("span");
      firework.className = "festival-popup-firework";
      firework.textContent = ["✦", "🎆", "✨"][index % 3];
      firework.style.left = (8 + Math.random() * 84) + "%";
      firework.style.bottom = (10 + Math.random() * 30) + "%";
      firework.style.animationDelay = (Math.random() * .9) + "s";
      replay.appendChild(firework);
    }
  }

  function showReplay(event) {
    replay.querySelector(".festival-popup-replay-tag").textContent = "✦ " + text(event.label);
    var subject = replay.querySelector(".festival-popup-replay-subject");
    subject.replaceChildren(makeSubject(event, true));
    replay.querySelector(".festival-popup-replay-name").textContent = text(event.subject_name);
    replay.querySelector(".festival-popup-replay-amount").textContent = event.amount ? money(event.amount) : "";
    replay.querySelector(".festival-popup-replay-detail").textContent = text(event.detail);
    replay.classList.add("is-visible");
    sprayFireworks();
    setTimeout(sprayFireworks, 5000);
    setTimeout(sprayFireworks, 10000);
    setTimeout(function () { replay.classList.remove("is-visible"); }, L4_DWELL_MS - 180);
    setTimeout(function () {
      replay.querySelectorAll(".festival-popup-firework").forEach(function (item) { item.remove(); });
      finish(event);
    }, L4_DWELL_MS);
  }

  function playNext() {
    if (busy || !queue.length) return;
    busy = true;
    var event = queue.shift();
    if (event.level === "L4") showReplay(event);
    else showLower(event);
  }

  function enqueue(events) {
    var cursor = readCursor();
    var slots = Math.max(0, MAX_QUEUED - queuedIds.size);
    if (!slots) return;
    events
      .filter(function (event) {
        var id = Number(event.id) || 0;
        return id > cursor && !queuedIds.has(String(id));
      })
      .sort(function (a, b) { return Number(a.id) - Number(b.id); })
      .slice(0, slots)
      .forEach(function (event) {
        queuedIds.add(String(event.id));
        queue.push(event);
      });
    playNext();
  }

  function previewExamples(events) {
    var examples = [];
    var l4 = events.find(function (event) { return event.level === "L4"; });
    var l3 = events.find(function (event) { return event.level === "L3"; });
    if (l4) examples.push(l4);
    if (l3) examples.push(l3);
    examples.forEach(function (event) {
      queuedIds.add(String(event.id));
      queue.push(event);
    });
    playNext();
  }

  function schedulePoll(delay) {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(poll, delay == null ? POLL_MS : delay);
  }

  function poll() {
    if (polling || document.hidden) { schedulePoll(); return; }
    polling = true;
    var baseline = !hasStoredCursor();
    fetch(apiUrl(!baseline))
      .then(function (response) { if (!response.ok) throw new Error(String(response.status)); return response.json(); })
      .then(function (body) {
        var data = body.data || body;
        var events = data.popup_events || data.events || [];
        if (baseline) {
          var maxId = events.reduce(function (max, event) { return Math.max(max, Number(event.id) || 0); }, 0);
          memoryCursor = maxId;
          try { localStorage.setItem(cursorKey, String(maxId)); } catch (_error) { /* 下轮仍可继续 */ }
          initialized = true;
          if (isPreview) previewExamples(events);
        } else {
          initialized = true;
          enqueue(events);
        }
      })
      .catch(function () { /* 保留游标，下轮自动恢复 */ })
      .finally(function () { polling = false; schedulePoll(); });
  }

  function scheduleNavigation(url, delay) {
    var remaining = delay;
    var previous = Date.now();
    setTimeout(function tick() {
      var now = Date.now();
      if (!busy && !queue.length && !document.hidden) remaining -= now - previous;
      previous = now;
      if (remaining <= 0) { location.href = url; return; }
      setTimeout(tick, Math.min(250, remaining));
    }, Math.min(250, remaining));
  }

  window.FestivalPopup = {
    isBusy: function () { return busy || queue.length > 0; },
    pollNow: function () { schedulePoll(0); },
    scheduleNavigation: scheduleNavigation
  };

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) schedulePoll(0);
  });
  poll();
})();
