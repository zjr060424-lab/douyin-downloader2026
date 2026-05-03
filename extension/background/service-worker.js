// dydownload background service worker
// Periodically checks for douyin cookies and pushes them to the local CLI server.

const LOCAL_SERVER_URL = 'http://127.0.0.1:18921/cookie';
const SERVER_HEALTH_URL = 'http://127.0.0.1:18921/health';
const COOKIE_CHECK_MINUTES = 5;
const TARGET_DOMAINS = ['.douyin.com', '.iesdouyin.com'];

let lastCookieHash = '';

// ---- Cookie Helpers ----

async function getAllCookies() {
  let allCookies = [];
  for (const domain of TARGET_DOMAINS) {
    try {
      const cookies = await chrome.cookies.getAll({ domain });
      allCookies = allCookies.concat(cookies);
    } catch (err) {
      // Domain may not have any cookies set yet
      console.debug('[dydownload] No cookies for domain:', domain);
    }
  }
  return allCookies;
}

function formatCookieString(cookies) {
  // Skip cookies with empty names (these are domain-level entries, not real cookies)
  return cookies
    .filter(c => c.name && c.name.trim() !== '')
    .map(c => `${c.name}=${c.value}`)
    .join('; ');
}

function formatNetscapeCookies(cookies) {
  // Netscape HTTP Cookie File format for yt-dlp compatibility
  // Lines: domain  flag  path  secure  expiration  name  value
  const lines = ['# Netscape HTTP Cookie File'];
  for (const c of cookies) {
    if (!c.name || c.name.trim() === '') continue;
    const domain = c.domain || '.douyin.com';
    const flag = domain.startsWith('.') ? 'TRUE' : 'FALSE';
    const path = c.path || '/';
    const secure = c.secure ? 'TRUE' : 'FALSE';
    const expiry = c.expirationDate ? Math.floor(c.expirationDate) : '0';
    lines.push(`${domain}\t${flag}\t${path}\t${secure}\t${expiry}\t${c.name}\t${c.value}`);
  }
  return lines.join('\n');
}

async function sha256(message) {
  const msgBuffer = new TextEncoder().encode(message);
  const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

// ---- Server Communication ----

async function checkServerHealth() {
  try {
    const response = await fetch(SERVER_HEALTH_URL, { method: 'GET', cache: 'no-cache' });
    return response.ok;
  } catch {
    return false;
  }
}

async function pushCookiesToServer(cookieString, cookieCount, netscapeCookies) {
  try {
    const response = await fetch(LOCAL_SERVER_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cookie: cookieString,
        netscape: netscapeCookies,
        timestamp: new Date().toISOString(),
        count: cookieCount
      })
    });
    return response.ok;
  } catch (err) {
    // Server not running — silent failure, will retry on next cycle
    console.debug('[dydownload] Local server unreachable:', err.message);
    return false;
  }
}

// ---- Main Logic ----

async function checkAndPushCookies() {
  const cookies = await getAllCookies();
  if (cookies.length === 0) {
    console.debug('[dydownload] No cookies found');
    return;
  }

  const cookieString = formatCookieString(cookies);
  const netscapeCookies = formatNetscapeCookies(cookies);
  const hash = await sha256(cookieString);

  if (hash !== lastCookieHash) {
    lastCookieHash = hash;
    const serverUp = await checkServerHealth();
    if (serverUp) {
      const success = await pushCookiesToServer(cookieString, cookies.length, netscapeCookies);
      if (success) {
        console.log(`[dydownload] Pushed ${cookies.length} cookies to CLI`);
      }
    } else {
      // Reset hash so we push on next check when server comes back
      lastCookieHash = '';
    }
  }
}

// ---- Message Handling (from popup) ----

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'getCookies') {
    getAllCookies().then(cookies => {
      sendResponse({
        success: true,
        cookies: cookies,
        cookieString: formatCookieString(cookies),
        count: cookies.length
      });
    });
    return true; // Keep channel open for async response
  }

  if (request.action === 'pushNow') {
    checkAndPushCookies().then(() => {
      sendResponse({ success: true });
    });
    return true;
  }

  if (request.action === 'checkServer') {
    checkServerHealth().then(up => {
      sendResponse({ serverUp: up });
    });
    return true;
  }
});

// ---- Alarm Setup ----

chrome.alarms.create('cookieCheck', { periodInMinutes: COOKIE_CHECK_MINUTES });

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'cookieCheck') {
    checkAndPushCookies();
  }
});

// Initial check on service worker startup
checkAndPushCookies();
console.log('[dydownload] Background service worker started');
