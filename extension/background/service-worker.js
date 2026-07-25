// dydownload background service worker
// Periodically collects douyin + bilibili cookies and pushes them to the CLI.

const LOCAL_SERVER_URL = 'http://127.0.0.1:18921/cookie';
const LOCAL_SERVER_BILI_URL = 'http://127.0.0.1:18921/cookie/bilibili';
const SERVER_HEALTH_URL = 'http://127.0.0.1:18921/health';
const COOKIE_CHECK_MINUTES = 5;

const DOUYIN_DOMAINS = ['.douyin.com', '.iesdouyin.com'];
const BILI_DOMAINS = ['.bilibili.com', '.b23.tv'];

let lastDouyinHash = '';
let lastBiliHash = '';

// ---- Cookie Helpers ----

async function getCookiesForDomains(domains) {
  let allCookies = [];
  for (const domain of domains) {
    try {
      const cookies = await chrome.cookies.getAll({ domain });
      allCookies = allCookies.concat(cookies);
    } catch (err) {
      console.debug('[dydownload] No cookies for domain:', domain);
    }
  }
  return allCookies;
}

function formatCookieString(cookies) {
  return cookies
    .filter(c => c.name && c.name.trim() !== '')
    .map(c => `${c.name}=${c.value}`)
    .join('; ');
}

function formatNetscapeCookies(cookies) {
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

async function pushCookiesToServer(url, cookieString, cookieCount, netscapeCookies) {
  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cookie: cookieString,
        netscape: netscapeCookies,
        timestamp: new Date().toISOString(),
        count: cookieCount,
      }),
    });
    return response.ok;
  } catch (err) {
    console.debug('[dydownload] Local server unreachable:', err.message);
    return false;
  }
}

// ---- Main Logic ----

async function checkAndPushCookies() {
  const [douyinCookies, biliCookies] = await Promise.all([
    getCookiesForDomains(DOUYIN_DOMAINS),
    getCookiesForDomains(BILI_DOMAINS),
  ]);

  const serverUp = await checkServerHealth();
  if (!serverUp) {
    lastDouyinHash = '';
    lastBiliHash = '';
    return;
  }

  if (douyinCookies.length) {
    const cookieString = formatCookieString(douyinCookies);
    const netscape = formatNetscapeCookies(douyinCookies);
    const hash = await sha256(cookieString);
    if (hash !== lastDouyinHash) {
      lastDouyinHash = hash;
      await pushCookiesToServer(LOCAL_SERVER_URL, cookieString, douyinCookies.length, netscape);
      console.log(`[dydownload] Pushed ${douyinCookies.length} 抖音 cookies`);
    }
  }

  if (biliCookies.length) {
    const cookieString = formatCookieString(biliCookies);
    const hash = await sha256(cookieString);
    if (hash !== lastBiliHash) {
      lastBiliHash = hash;
      await pushCookiesToServer(LOCAL_SERVER_BILI_URL, cookieString, biliCookies.length, '');
      console.log(`[dydownload] Pushed ${biliCookies.length} B 站 cookies`);
    }
  }
}

// ---- Message Handling (from popup) ----

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'getCookies') {
    Promise.all([
      getCookiesForDomains(DOUYIN_DOMAINS),
      getCookiesForDomains(BILI_DOMAINS),
    ]).then(([douyin, bili]) => {
      sendResponse({
        success: true,
        douyin: {
          cookies: douyin,
          cookieString: formatCookieString(douyin),
          count: douyin.length,
        },
        bilibili: {
          cookies: bili,
          cookieString: formatCookieString(bili),
          count: bili.length,
        },
      });
    });
    return true;
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

checkAndPushCookies();
console.log('[dydownload] Background service worker started');
