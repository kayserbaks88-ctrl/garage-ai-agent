/* Compatibility recovery: preserve the worker URL, let the browser own requests. */
'use strict';
self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
// No request handlers, storage, background tasks, forced reloads or queued actions.
