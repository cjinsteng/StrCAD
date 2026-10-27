/* offline cache for the app shell (works when served over https, e.g. GitHub Pages) */
const CACHE = "strcad-survey-v4";
const FILES = ["./", "index.html", "app.js", "check.js", "detail.js", "sketch.js", "app.css", "manifest.webmanifest", "icon-192.png", "icon-512.png", "logo.png",
  "vendor/sql-wasm.js", "vendor/sql-wasm.wasm"];
self.addEventListener("install", (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(FILES)).then(() => self.skipWaiting())));
self.addEventListener("activate", (e) => e.waitUntil(caches.keys().then((ks) =>
  Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (u.pathname.includes("/api/") || e.request.method !== "GET") return;      // PC sync calls go to the network
  e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request).then((resp) => {
    if (resp.ok && u.origin === location.origin) { const cp = resp.clone(); caches.open(CACHE).then((c) => c.put(e.request, cp)); }
    return resp;
  })));
});
