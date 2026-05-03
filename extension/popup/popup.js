// dydownload popup script

const KEY_COOKIES = ['ttwid', 'sessionid', 'passport_csrf_token', 's_v_web_id', 'odin_tt'];

const $serverDot = document.getElementById('serverDot');
const $serverStatus = document.getElementById('serverStatus');
const $cookieCount = document.getElementById('cookieCount');
const $lastPush = document.getElementById('lastPush');
const $btnPush = document.getElementById('btnPush');
const $btnCopy = document.getElementById('btnCopy');
const $toast = document.getElementById('toast');

const $videoUrl = document.getElementById('videoUrl');
const $btnDownload = document.getElementById('btnDownload');
const $downloadStatus = document.getElementById('downloadStatus');

const DOWNLOAD_URL = 'http://127.0.0.1:18921/download';
const DOWNLOAD_STATUS_URL = 'http://127.0.0.1:18921/download/status/';

// ---- Init ----

document.addEventListener('DOMContentLoaded', async () => {
  await refreshStatus();
  checkServer();
  detectCurrentTabUrl();
});

// ---- Server Check ----

async function checkServer() {
  try {
    const response = await chrome.runtime.sendMessage({ action: 'checkServer' });
    if (response && response.serverUp) {
      $serverDot.className = 'status-dot online';
      $serverStatus.textContent = 'CLI 已连接';
    } else {
      $serverDot.className = 'status-dot offline';
      $serverStatus.textContent = 'CLI 未启动';
    }
  } catch {
    $serverDot.className = 'status-dot offline';
    $serverStatus.textContent = 'CLI 未启动';
  }
}

// ---- Cookie Status ----

async function refreshStatus() {
  try {
    const response = await chrome.runtime.sendMessage({ action: 'getCookies' });
    if (!response || !response.success) {
      $cookieCount.textContent = '0';
      updateChecklist([]);
      return;
    }

    const cookies = response.cookies || [];
    $cookieCount.textContent = cookies.length;

    // Update checklist
    const foundNames = new Set(cookies.map(c => c.name));
    updateChecklist(foundNames);

    // Read last push time from storage
    const storage = await chrome.storage.local.get('lastPushTime');
    if (storage.lastPushTime) {
      const ago = Math.round((Date.now() - storage.lastPushTime) / 1000);
      $lastPush.textContent = ago < 60 ? `${ago} 秒前` : `${Math.round(ago / 60)} 分钟前`;
    }
  } catch (err) {
    $cookieCount.textContent = '--';
  }
}

function updateChecklist(foundNames) {
  document.querySelectorAll('.cookie-item').forEach(item => {
    const key = item.dataset.key;
    const icon = item.querySelector('.check-icon');
    if (foundNames.has(key)) {
      icon.textContent = '✓';
      icon.className = 'check-icon ok';
    } else {
      icon.textContent = '✗';
      icon.className = 'check-icon miss';
    }
  });
}

// ---- Button Handlers ----

$btnPush.addEventListener('click', async () => {
  $btnPush.textContent = '推送中...';
  $btnPush.disabled = true;

  try {
    await chrome.runtime.sendMessage({ action: 'pushNow' });
    await chrome.storage.local.set({ lastPushTime: Date.now() });
    await refreshStatus();
    await checkServer();
    showToast('Cookie 已推送', 'success');
  } catch (err) {
    showToast('推送失败: ' + err.message, 'error');
  } finally {
    $btnPush.textContent = '推送到 CLI';
    $btnPush.disabled = false;
  }
});

$btnCopy.addEventListener('click', async () => {
  try {
    const response = await chrome.runtime.sendMessage({ action: 'getCookies' });
    if (response && response.cookieString) {
      await navigator.clipboard.writeText(response.cookieString);
      showToast('Cookie 已复制到剪贴板', 'success');
    } else {
      showToast('没有可复制的 Cookie', 'error');
    }
  } catch (err) {
    showToast('复制失败', 'error');
  }
});

// ---- Auto-detect current tab URL ----

async function detectCurrentTabUrl() {
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    const currentTab = tabs[0];
    if (currentTab && currentTab.url) {
      const url = currentTab.url;
      if (url.includes('douyin.com/video/') || url.includes('iesdouyin.com/share/video/') || url.includes('v.douyin.com')) {
        $videoUrl.value = url;
      }
    }
  } catch {
    // Popup in non-tab context — silently skip
  }
}

// ---- Download ----

$btnDownload.addEventListener('click', async () => {
  const url = $videoUrl.value.trim();
  if (!url) {
    $downloadStatus.className = 'download-status error';
    $downloadStatus.textContent = '请粘贴视频链接';
    $downloadStatus.classList.remove('hidden');
    return;
  }

  $btnDownload.textContent = '下载中...';
  $btnDownload.disabled = true;
  $downloadStatus.className = 'download-status loading';
  $downloadStatus.textContent = '正在下载，请稍候...';
  $downloadStatus.classList.remove('hidden');

  try {
    const resp = await fetch(DOWNLOAD_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });
    const data = await resp.json();

    if (data.status === 'started') {
      // Poll for completion
      const taskId = data.task_id;
      let done = false;
      for (let i = 0; i < 30; i++) {
        await sleep(2000);
        const statusResp = await fetch(DOWNLOAD_STATUS_URL + taskId);
        const statusData = await statusResp.json();

        if (statusData.status === 'done') {
          const sizeMB = (statusData.size / 1024 / 1024).toFixed(1);
          $downloadStatus.className = 'download-status success';
          $downloadStatus.textContent = `✓ 下载完成: ${statusData.title} (${sizeMB} MB)`;
          done = true;
          break;
        } else if (statusData.status === 'error') {
          $downloadStatus.className = 'download-status error';
          $downloadStatus.textContent = `✗ ${statusData.message}`;
          done = true;
          break;
        }
      }
      if (!done) {
        $downloadStatus.className = 'download-status loading';
        $downloadStatus.textContent = '后台下载中，稍后查看 downloads/ 目录';
      }
    } else {
      $downloadStatus.className = 'download-status error';
      $downloadStatus.textContent = `✗ ${data.message || '请求失败'}`;
    }
  } catch (err) {
    $downloadStatus.className = 'download-status error';
    $downloadStatus.textContent = '✗ 无法连接到本地服务，请先启动 CLI';
  } finally {
    $btnDownload.textContent = '下载无水印视频';
    $btnDownload.disabled = false;
  }
});

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ---- Toast ----

function showToast(message, type) {
  $toast.textContent = message;
  $toast.className = `toast ${type}`;
  setTimeout(() => {
    $toast.className = 'toast hidden';
  }, 2000);
}
