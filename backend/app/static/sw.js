var CACHE_NAME = 'tele-schocken-static-v1';
var TWO_MONTHS_MS = 60 * 24 * 60 * 60 * 1000;

var STATIC_EXTENSIONS = [
  '.mp3', '.wav', '.ogg', '.webm',
  '.js', '.css',
  '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico',
  '.woff', '.woff2', '.ttf', '.eot'
];

function isStaticAsset(url) {
  var pathname = new URL(url).pathname.toLowerCase();
  for (var i = 0; i < STATIC_EXTENSIONS.length; i++) {
    if (pathname.endsWith(STATIC_EXTENSIONS[i])) return true;
  }
  return false;
}

self.addEventListener('install', function(event) {
  self.skipWaiting();
});

self.addEventListener('activate', function(event) {
  event.waitUntil(
    caches.keys().then(function(names) {
      return Promise.all(
        names.filter(function(n) { return n !== CACHE_NAME; })
             .map(function(n) { return caches.delete(n); })
      );
    }).then(function() {
      return self.clients.claim();
    })
  );
});

self.addEventListener('fetch', function(event) {
  if (event.request.method !== 'GET') return;
  if (!isStaticAsset(event.request.url)) return;

  event.respondWith(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.match(event.request).then(function(cached) {
        if (cached) {
          updateTimestamp(event.request.url);
          return cached;
        }
        return fetch(event.request).then(function(response) {
          if (response && response.status === 200) {
            cache.put(event.request, response.clone());
            updateTimestamp(event.request.url);
          }
          return response;
        });
      });
    })
  );
});

function updateTimestamp(url) {
  try {
    var db = indexedDB.open('sw-cache-meta', 1);
    db.onupgradeneeded = function(e) {
      var store = e.target.result;
      if (!store.objectStoreNames.contains('timestamps')) {
        store.createObjectStore('timestamps', {keyPath: 'url'});
      }
    };
    db.onsuccess = function(e) {
      var tx = e.target.result.transaction('timestamps', 'readwrite');
      tx.objectStore('timestamps').put({url: url, ts: Date.now()});
    };
  } catch(ex) {}
}

function cleanExpired() {
  var cutoff = Date.now() - TWO_MONTHS_MS;
  try {
    var dbReq = indexedDB.open('sw-cache-meta', 1);
    dbReq.onupgradeneeded = function(e) {
      var store = e.target.result;
      if (!store.objectStoreNames.contains('timestamps')) {
        store.createObjectStore('timestamps', {keyPath: 'url'});
      }
    };
    dbReq.onsuccess = function(e) {
      var db = e.target.result;
      var tx = db.transaction('timestamps', 'readwrite');
      var store = tx.objectStore('timestamps');
      var getAll = store.getAll();
      getAll.onsuccess = function() {
        var entries = getAll.result || [];
        var expired = entries.filter(function(en) { return en.ts < cutoff; });
        if (expired.length === 0) return;
        caches.open(CACHE_NAME).then(function(cache) {
          expired.forEach(function(en) {
            cache.delete(en.url).catch(function() {});
            store.delete(en.url);
          });
        });
      };
    };
  } catch(ex) {}
}

setInterval(cleanExpired, 24 * 60 * 60 * 1000);
cleanExpired();
