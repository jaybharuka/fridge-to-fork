// Minimal service worker — app-shell caching only, no offline-first
// ambitions. This app's entire value is live AI results (fridge scanning,
// meal planning, ordering), so anything dynamic must always hit the
// network; only genuinely static, content-hashed or rarely-changing
// assets are cached here.
//
// Bump CACHE_VERSION when the cached asset list below changes, to evict
// the old cache on the next activate.
const CACHE_VERSION = "f2f-shell-v1";

// Explicit app-shell assets, pre-cached on install. Small and static by
// hand — this isn't meant to enumerate every route, just the icons/
// manifest that make the installed-app experience feel instant.
const SHELL_ASSETS = [
  "/manifest.webmanifest",
  "/favicon.ico",
  "/icon.svg",
  "/apple-icon.png",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/icon-maskable-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Never intercept anything but same-origin GETs — this is the hard
  // boundary that keeps /api/*, the SSE scan/order streams, and any
  // cross-origin request (backend, Google Fonts, YouTube, dish images)
  // untouched and always live.
  if (request.method !== "GET" || url.origin !== self.location.origin) {
    return;
  }

  // Next.js's build output — hashed filenames, safe to cache-first
  // (a new deploy produces new URLs, never a stale collision).
  if (url.pathname.startsWith("/_next/static/")) {
    event.respondWith(
      caches.open(CACHE_VERSION).then(async (cache) => {
        const cached = await cache.match(request);
        if (cached) return cached;
        const response = await fetch(request);
        if (response.ok) cache.put(request, response.clone());
        return response;
      })
    );
    return;
  }

  // Explicit shell assets — cache-first with a network fallback that
  // refreshes the cache, so an icon/manifest update eventually lands
  // without needing a version bump for every tweak.
  if (SHELL_ASSETS.includes(url.pathname)) {
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request).then((response) => {
            if (response.ok) {
              caches.open(CACHE_VERSION).then((cache) => cache.put(request, response.clone()));
            }
            return response;
          })
      )
    );
    return;
  }

  // Everything else (pages, /api/*, anything dynamic) — not intercepted,
  // network handles it exactly as if no service worker existed.
});
