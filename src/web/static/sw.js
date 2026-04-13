/* 오디스 프라임 — Service Worker */

const CACHE = "ordis-v1";
const PRECACHE = ["/", "/static/style.css", "/static/app.js"];

self.addEventListener("install", e => {
    e.waitUntil(
        caches.open(CACHE).then(c => c.addAll(PRECACHE)).then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", e => {
    e.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
        ).then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", e => {
    if (e.request.method !== "GET") return;
    if (e.request.url.includes("/ws")) return;
    if (e.request.url.includes("/api/")) return;
    e.respondWith(
        caches.match(e.request).then(cached => cached || fetch(e.request))
    );
});

self.addEventListener("push", e => {
    const data = e.data ? e.data.json() : {};
    const title = data.title || "오디스 프라임";
    const options = {
        body: data.body || "",
        icon: "/static/icon-192.png",
        badge: "/static/icon-192.png",
        data: { url: data.url || "/" },
        vibrate: [200, 100, 200],
    };
    e.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", e => {
    e.notification.close();
    e.waitUntil(
        clients.matchAll({ type: "window" }).then(list => {
            for (const c of list) {
                if (c.url === "/" && "focus" in c) return c.focus();
            }
            if (clients.openWindow) return clients.openWindow(e.notification.data.url);
        })
    );
});
