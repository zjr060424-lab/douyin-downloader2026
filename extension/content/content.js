// Content script injected into douyin.com pages.
// Currently minimal — primarily provides a detection signal that the
// user is actively browsing Douyin (cookies are fresh).

(function () {
  'use strict';

  // Signal to the page that dydownload extension is active.
  // Future: could extract RENDER_DATA directly from the page and forward
  // to the background service worker as an alternative data source.
  console.debug('[dydownload] Content script loaded on:', window.location.href);
})();
