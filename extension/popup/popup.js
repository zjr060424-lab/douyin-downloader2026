// dydownload popup script — supports 抖音 and B 站.

const DOUYIN_KEYS = ['ttwid', 'sessionid', 'passport_csrf_token', 's_v_web_id', 'odin_tt'];
const BILI_KEYS = ['SESSDATA', 'bili_jct', 'buvid3'];

const $serverDot = document.getElementById('serverDot');
const $serverStatus = document.getElementById('serverStatus');
const $douyinCount = document.getElementById('douyinCount');
const $biliCount = document.getElementById('biliCount');
const $lastPush = document.getElementById('lastPush');
const $btnPush = document.getElementById('btnPush');
const $btnCopy = document.getElementById('btnCopy');
const $toast = document.getElementById('toast');

const $videoUrl = document.getElementById('videoUrl');
const $btnDownload = document.getElementById('btnDownload');
const $downloadStatus = document.getElementById('downloadStatus');
const $platform = document.getElementById('platform');
const $quality = document.getElementById('quality');
const $preferDash = document.getElementById('preferDash');
const $parts = document.getElementById('parts');
const $mux = document.getElementById('mux');

const DOWNLOAD_URL = 'http://127.0.0.1:18921/download';
const DOWNLOAD_STATUS_URL = 'http://127.0.0.1:18921/download/status/';

document.addEventListener('DOMContentLoaded', async () => {
  await refreshStatus();
  checkServer();
  detectCurrentTabUrl();
});

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

async function refreshStatus() {
  try {
    const response = await chrome.runtime.sendMessage({ action: 'getCookies' });
    if (!response || !response.success) {
      $douyinCount.textContent = '0';
      $biliCount.textContent = '0';
      updateChecklist('douyin', new Set());
      updateChecklist('bili', new Set());
      return;
    }
    const douyin = response.douyin || { cookies: [], count: 0 };
    const bili = response.bilibili || { cookies: [], count: 0 };
    $douyinCount.textContent = douyin.count;
    $biliCount.textContent = bili.count;
    updateChecklist('douyin', new Set(douyin.cookies.map(c => c.name)));
    updateChecklist('bili', new Set(bili.cookies.map(c => c.name)));

    const storage = await chrome.storage.local.get('lastPushTime');
    if (storage.lastPushTime) {
      const ago = Math.round((Date.now() - storage.lastPushTime) / 1000);
      $lastPush.textContent = ago < 60 ? `${ago} 秒前` : `${Math.round(ago / 60)} 分钟前`;
    }
  } catch (err) {
    $douyinCount.textContent = '--';
    $biliCount.textContent = '--';
  }
}

function updateChecklist(platform, foundNames) {
  const items = document.querySelectorAll(`.cookie-item[data-platform="${platform}"]`);
  items.forEach(item => {
    const icon = item.querySelector('.check-icon');
    if (foundNames.has(item.dataset.key)) {
      icon.textContent = '✓';
      icon.className = 'check-icon ok';
    } else {
      icon.textContent = '✗';
      icon.className = 'check-icon miss';
    }
  });
}

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
    if (!response) {
      showToast('没有可复制的 Cookie', 'error');
      return;
    }
    const merged = [response.douyin.cookieString, response.bilibili.cookieString]
      .filter(s => s)
      .join('; ');
    if (!merged) {
      showToast('没有可复制的 Cookie', 'error');
      return;
    }
    await navigator.clipboard.writeText(merged);
    showToast('Cookie 已复制到剪贴板', 'success');
  } catch {
    showToast('复制失败', 'error');
  }
});

async function detectCurrentTabUrl() {
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    const currentTab = tabs[0];
    if (!currentTab || !currentTab.url) return;
    const url = currentTab.url;
    if (
      url.includes('douyin.com/video/') ||
      url.includes('douyin.com/note/') ||
      url.includes('iesdouyin.com/share/') ||
      url.includes('v.douyin.com')
    ) {
      $videoUrl.value = url;
      $platform.value = 'douyin';
    } else if (
      url.includes('bilibili.com/video/') ||
      url.includes('bilibili.com/bangumi/play/') ||
      url.includes('b23.tv/')
    ) {
      $videoUrl.value = url;
      $platform.value = 'bilibili';
    }
  } catch {
    // ignore
  }
}

$btnDownload.addEventListener('click', async () => {
  const url = $videoUrl.value.trim();
  if (!url) {
    $downloadStatus.className = 'download-status error';
    $downloadStatus.textContent = '请粘贴视频链接';
    $downloadStatus.classList.remove('hidden');
    return;
  }
  const platform = $platform.value;
  const payload = {
    url,
    platform,
    quality: parseInt($quality.value, 10) || 80,
    prefer_dash: $preferDash.checked,
    parts: $parts.value,
    mux: $mux.checked,
  };
  $btnDownload.textContent = '下载中...';
  $btnDownload.disabled = true;
  $downloadStatus.className = 'download-status loading';
  $downloadStatus.textContent = '正在下载，请稍候...';
  $downloadStatus.classList.remove('hidden');

  try {
    const resp = await fetch(DOWNLOAD_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();

    if (data.status === 'started') {
      const taskId = data.task_id;
      let done = false;
      for (let i = 0; i < 60; i++) {
        await sleep(2000);
        const statusResp = await fetch(DOWNLOAD_STATUS_URL + taskId);
        const statusData = await statusResp.json();

        if (statusData.status === 'done') {
          const files = statusData.files || (statusData.file ? [statusData.file] : []);
          const sizeMB = (statusData.size / 1024 / 1024).toFixed(1);
          const label = statusData.kind === 'bilibili' ? 'B 站' :
                         statusData.kind === 'image' ? '图集' : '视频';
          $downloadStatus.className = 'download-status success';
          $downloadStatus.textContent =
            `✓ ${label}完成: ${statusData.title || ''} (${sizeMB} MB, ${files.length} 文件)`;
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
  } catch {
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

function showToast(message, type) {
  $toast.textContent = message;
  $toast.className = `toast ${type}`;
  setTimeout(() => {
    $toast.className = 'toast hidden';
  }, 2000);
}
