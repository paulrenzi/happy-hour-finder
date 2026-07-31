/* Cache the shell and the zone bundles so "what's live right now" works with no
   signal -- it is pure client-side math over data already on the device. */
const CACHE = "hhf-v2";
const SHELL = [
  "./", "index.html", "app.js", "styles.css", "manifest.json",
  "data/index.json", "img/hero-taproom.jpg", "img/icon-192.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  );
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  // Network first so a rebuilt bundle lands, cache as the offline floor.
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return res;
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match("index.html")))
  );
});
