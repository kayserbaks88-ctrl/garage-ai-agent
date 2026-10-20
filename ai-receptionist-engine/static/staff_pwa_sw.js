/* Public offline document embedded at delivery; never store employee responses. */
'use strict';
const offlineDocument = __STAFF_OFFLINE_HTML__;
self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  const employeePage = /^\/staff\/[a-z0-9][a-z0-9_-]*\/employee(?:\/(?:login|jobs|clocking|hours|leave|pay|profile|rota|recover|reset))?\/?$/;
  const publicPage = /^\/staff\/employee\/app(?:\/(?:install|offline))?\/?$/;
  // Only existing read-only HTML page URLs. APIs, files, subscriptions,
  // registration, setup and all mutations remain ordinary network requests.
  const managerPage = /^\/staff\/(?:account(?:\/login)?|(?!account(?:\/|$)|platform(?:\/|$))[a-z0-9][a-z0-9_-]*(?:\/(?:employees|sites|shifts|approvals|attendance|leave|agency|jobs|rota|payroll))?)\/?$/;
  // POSTs, GPS calls, downloads, managers and onboarding go directly to the network.
  if (request.method !== 'GET' || request.mode !== 'navigate' ||
      url.origin !== self.location.origin ||
      !(employeePage.test(url.pathname) || publicPage.test(url.pathname) || managerPage.test(url.pathname))) return;
  event.respondWith(fetch(request, {cache: 'no-store'}).catch(() =>
    new Response(offlineDocument, {status: 503, headers: {
      'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'
    }})));
});
