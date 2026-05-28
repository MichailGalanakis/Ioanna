/* sw.js — Service Worker για offline λειτουργία */
const CACHE = "jp-vocab-v2";
const ASSETS = [
  "./",
  "./index.html",
  "./css/styles.css",
  "./js/sample-data.js",
  "./js/packs.js",
  "./js/storage.js",
  "./js/srs.js",
  "./js/stats.js",
  "./js/achievements.js",
  "./js/speech.js",
  "./js/exercises.js",
  "./js/geisha.js",
  "./js/app.js",
  "./manifest.webmanifest",
  "./data/sample-deck.json",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./icons/icon-maskable-512.png",
  "./icons/apple-touch-icon.png",
  "./icons/favicon-64.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  e.respondWith(
    caches.match(e.request).then((cached) => {
      if (cached) return cached;
      return fetch(e.request)
        .then((res) => {
          // Αποθήκευσε νέα αιτήματα ίδιας προέλευσης για offline χρήση
          if (res && res.status === 200 && new URL(e.request.url).origin === location.origin) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(e.request, copy));
          }
          return res;
        })
        .catch(() => caches.match("./index.html"));
    })
  );
});
