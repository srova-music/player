const CACHE_NAME = "srova-shell-v3";

const APP_SHELL = [
  "/ui_web/favicon.ico",
  "/ui_web/manifest.webmanifest",
  "/ui_web/icons/icon-180.png",
  "/ui_web/icons/icon-192.png",
  "/ui_web/icons/icon-512.png"
];

const CONTROL_PREFIXES = [
  "/api/",
  "/cache/",
  "/meta/",
  "/radio",
  "/scrobble/",
  "/session",
  "/spectrum",
  "/status",
  "/tidal/"
];

function isControlRoute(pathname) {
  return CONTROL_PREFIXES.some(function(prefix) {
    return pathname === prefix || pathname.indexOf(prefix) === 0;
  });
}

function isNetworkOnlyRoute(pathname) {
  return pathname === "/" ||
    pathname === "/ui_web/index.html" ||
    pathname === "/ui_web/srova.css" ||
    pathname === "/ui_web/ui.js";
}

self.addEventListener("install", function(event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.addAll(APP_SHELL);
    }).then(function() {
      return self.skipWaiting();
    })
  );
});

self.addEventListener("activate", function(event) {
  event.waitUntil(
    caches.keys().then(function(names) {
      return Promise.all(names.map(function(name) {
        if (name.indexOf("srova-shell-") === 0 && name !== CACHE_NAME) {
          return caches.delete(name);
        }
        return Promise.resolve();
      }));
    }).then(function() {
      return self.clients.claim();
    })
  );
});

self.addEventListener("fetch", function(event) {
  const request = event.request;

  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);

  if (url.origin !== self.location.origin || isControlRoute(url.pathname)) {
    return;
  }

  if (isNetworkOnlyRoute(url.pathname)) {
    event.respondWith(fetch(request));
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(fetch(request));
    return;
  }

  if (APP_SHELL.indexOf(url.pathname) === -1) {
    return;
  }

  event.respondWith(
    caches.match(request).then(function(cached) {
      return cached || fetch(request);
    })
  );
});
