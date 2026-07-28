// dydownload background service worker
// Periodically collects douyin + bilibili cookies and pushes them to the CLI.

const SERVER_PORTS = [18921, 18922, 18923, 18924, 18925];
const COOKIE_CHECK_MINUTES = 5;

const DOUYIN_DOMAINS = ['.douyin.com', '.iesdouyin.com'];
const BILI_DOMAINS = ['.bilibili.com', '.b23.tv'];

let lastDouyinHash = '';
let lastBiliHash = '';
let activeServerBase = '';

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

async function findServerBase() {
  const candidates = activeServerBase
    ? [activeServerBase, ...SERVER_PORTS.map(port => `http://127.0.0.1:${port}`)]
    : SERVER_PORTS.map(port => `http://127.0.0.1:${port}`);
  for (const base of [...new Set(candidates)]) {
    try {
      const response = await fetch(`${base}/health`, { method: 'GET', cache: 'no-cache' });
      if (!response.ok) continue;
      const data = await response.json();
      if (data.service === 'dydownload' && data.status === 'running') {
        activeServerBase = base;
        return base;
      }
    } catch {
      // Try the next configured port.
    }
  }
  activeServerBase = '';
  return '';
}

async function pushCookiesToServer(base, path, cookieString, cookieCount, netscapeCookies) {
  try {
    const response = await fetch(`${base}${path}`, {
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

  const serverBase = await findServerBase();
  if (!serverBase) {
    lastDouyinHash = '';
    lastBiliHash = '';
    return { success: false, message: 'dydownload 本地服务未启动' };
  }

  if (!douyinCookies.length && !biliCookies.length) {
    return { success: false, message: '未找到抖音或 B 站 Cookie', serverBase };
  }

  const failures = [];

  if (douyinCookies.length) {
    const cookieString = formatCookieString(douyinCookies);
    const netscape = formatNetscapeCookies(douyinCookies);
    const hash = await sha256(cookieString);
    if (hash !== lastDouyinHash) {
      const pushed = await pushCookiesToServer(
        serverBase, '/cookie', cookieString, douyinCookies.length, netscape,
      );
      if (pushed) {
        lastDouyinHash = hash;
        console.log(`[dydownload] Pushed ${douyinCookies.length} 抖音 cookies`);
      } else {
        failures.push('抖音 Cookie 推送失败');
      }
    }
  }

  if (biliCookies.length) {
    const cookieString = formatCookieString(biliCookies);
    const hash = await sha256(cookieString);
    if (hash !== lastBiliHash) {
      const pushed = await pushCookiesToServer(
        serverBase, '/cookie/bilibili', cookieString, biliCookies.length, '',
      );
      if (pushed) {
        lastBiliHash = hash;
        console.log(`[dydownload] Pushed ${biliCookies.length} B 站 cookies`);
      } else {
        failures.push('B 站 Cookie 推送失败');
      }
    }
  }

  return {
    success: failures.length === 0,
    message: failures.join('；'),
    serverBase,
  };
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
    checkAndPushCookies()
      .then(sendResponse)
      .catch(err => sendResponse({ success: false, message: err.message }));
    return true;
  }

  if (request.action === 'checkServer') {
    findServerBase().then(serverBase => {
      sendResponse({ serverUp: Boolean(serverBase), serverBase });
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
