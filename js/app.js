/**
 * 云析 Web 客户端 - 主应用逻辑
 * 视图切换、UI 交互、解析流程、设置管理
 */

/* ===== 全局状态 ===== */
const state = {
  currentView: 'parse',
  parsedResult: null,
  selectedQuality: null,
  settings: {
    quality: 'auto',
    concurrency: 2,
    proxy: 'https://corsproxy.io/?url=',
    proxyCustom: ''
  }
};

/* ===== 初始化 ===== */
document.addEventListener('DOMContentLoaded', () => {
  loadSettings();
  initViews();
  initParsePage();
  initDownloadsPage();
  initSettingsPage();
  initPWA();
});

/* ===== 设置管理 ===== */
function loadSettings() {
  try {
    const saved = localStorage.getItem('yunx-settings');
    if (saved) Object.assign(state.settings, JSON.parse(saved));
  } catch {}
  // 应用代理设置
  const proxy = state.settings.proxy === 'custom' ? state.settings.proxyCustom : state.settings.proxy;
  http.setProxy(proxy);
  downloadManager.setConcurrency(parseInt(state.settings.concurrency));
}

function saveSettings() {
  localStorage.setItem('yunx-settings', JSON.stringify(state.settings));
}

/* ===== 视图切换 ===== */
function initViews() {
  const tabs = document.querySelectorAll('.tab-item');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const view = tab.dataset.view;
      switchView(view);
    });
  });
  // 设置按钮
  document.getElementById('btn-settings').addEventListener('click', () => switchView('settings'));
}

function switchView(name) {
  state.currentView = name;
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById('view-' + name).classList.add('active');
  document.querySelectorAll('.tab-item').forEach(t => {
    t.classList.toggle('active', t.dataset.view === name);
  });
  // 下载页切换时刷新列表
  if (name === 'downloads') renderDownloadList();
}

/* ===== 解析页 ===== */
function initParsePage() {
  // 粘贴按钮
  document.getElementById('btn-paste').addEventListener('click', async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        document.getElementById('url-input').value = text.trim();
        showToast('已粘贴链接');
      }
    } catch (e) {
      showToast('无法读取剪贴板，请手动粘贴');
    }
  });

  // 解析按钮
  document.getElementById('btn-parse').addEventListener('click', handleParse);

  // 下载按钮
  document.getElementById('btn-download').addEventListener('click', handleDownload);

  // 回车解析
  document.getElementById('url-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); handleParse(); }
  });
}

async function handleParse() {
  const url = document.getElementById('url-input').value.trim();
  const errorBox = document.getElementById('parse-error');
  const resultBox = document.getElementById('parse-result');
  errorBox.classList.add('hidden');
  resultBox.classList.add('hidden');

  if (!url) {
    showError('请输入链接');
    return;
  }

  const btn = document.getElementById('btn-parse');
  btn.disabled = true;
  btn.innerHTML = '<span class="loading"></span> 解析中...';

  try {
    const result = await parserFactory.parse(url);
    state.parsedResult = result;
    renderParseResult(result);
  } catch (e) {
    showError(e.message || '解析失败');
  } finally {
    btn.disabled = false;
    btn.textContent = '解析';
  }
}

function renderParseResult(result) {
  document.getElementById('result-cover').src = result.cover || '';
  document.getElementById('result-title').textContent = result.title;
  const meta = [];
  if (result.extra.author) meta.push(result.extra.author);
  if (result.extra.artist) meta.push(result.extra.artist);
  if (result.duration) meta.push(Utils.formatDuration(result.duration));
  meta.push(parserFactory.detect ? parserFactory.detect(document.getElementById('url-input').value).displayName : '');
  document.getElementById('result-meta').textContent = meta.filter(Boolean).join(' · ');

  // 渲染清晰度列表
  const qList = document.getElementById('quality-list');
  qList.innerHTML = '';
  if (result.qualityList.length === 0) {
    qList.innerHTML = '<p style="color:var(--text-secondary);font-size:14px;">暂无可用清晰度</p>';
  }
  // 默认选中
  const defaultQ = state.settings.quality;
  let selectedIdx = 0;
  if (defaultQ !== 'auto') {
    const idx = result.qualityList.findIndex(q => q.quality === defaultQ);
    if (idx >= 0) selectedIdx = idx;
  }
  result.qualityList.forEach((q, i) => {
    const item = document.createElement('div');
    item.className = 'quality-item' + (i === selectedIdx ? ' selected' : '');
    item.innerHTML = `
      <span class="quality-name">${q.description || q.quality}</span>
      <span class="quality-size">${Utils.formatSize(q.fileSize)}</span>
    `;
    item.addEventListener('click', () => {
      document.querySelectorAll('.quality-item').forEach(el => el.classList.remove('selected'));
      item.classList.add('selected');
      state.selectedQuality = q.quality;
    });
    qList.appendChild(item);
  });
  state.selectedQuality = result.qualityList[selectedIdx]?.quality || '';
  document.getElementById('parse-result').classList.remove('hidden');
}

async function handleDownload() {
  if (!state.parsedResult || !state.selectedQuality) {
    showToast('请先解析并选择清晰度');
    return;
  }
  const result = state.parsedResult;
  const quality = state.selectedQuality;
  const btn = document.getElementById('btn-download');
  btn.disabled = true;
  btn.textContent = '获取下载地址...';

  try {
    const parser = parserFactory.detect(document.getElementById('url-input').value);
    const directUrl = await parser.getDownloadUrl(result, quality);
    // 判断是否 m3u8
    const isM3u8 = directUrl.includes('.m3u8') || directUrl.includes('m3u8');
    const ext = isM3u8 ? 'ts' : (result.isMusic ? 'mp3' : 'mp4');
    const filename = Utils.sanitizeFilename(result.title) + '.' + ext;
    // 添加到下载队列
    downloadManager.addTask({
      title: result.title,
      cover: result.cover,
      platform: result.platform,
      quality: quality,
      url: directUrl,
      isM3u8: isM3u8,
      filename: filename
    });
    showToast('已添加到下载队列');
    switchView('downloads');
  } catch (e) {
    showError(e.message || '获取下载地址失败');
  } finally {
    btn.disabled = false;
    btn.textContent = '下载';
  }
}

function showError(msg) {
  const box = document.getElementById('parse-error');
  box.textContent = msg;
  box.classList.remove('hidden');
}

/* ===== 下载管理页 ===== */
function initDownloadsPage() {
  downloadManager.onUpdate(() => renderDownloadList());
}

function renderDownloadList() {
  const list = document.getElementById('download-list');
  const empty = document.getElementById('downloads-empty');
  const count = downloadManager.tasks.length;
  document.getElementById('download-count').textContent = `${count} 个任务`;
  if (count === 0) {
    list.innerHTML = '';
    list.appendChild(empty);
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');
  list.innerHTML = '';
  downloadManager.tasks.forEach(task => {
    const el = document.createElement('div');
    el.className = `download-item ${task.status}`;
    const statusText = {
      pending: '等待中', downloading: '下载中', paused: '已暂停',
      completed: '已完成', failed: '失败'
    }[task.status] || task.status;
    const pct = Math.round(task.progress);
    el.innerHTML = `
      <div class="download-item-header">
        ${task.cover ? `<img class="download-thumb" src="${task.cover}" alt="">` : '<div class="download-thumb"></div>'}
        <div class="download-item-info">
          <div class="download-item-title">${task.title}</div>
          <div class="download-item-status">${statusText} ${task.status === 'downloading' ? pct + '%' : ''} ${task.error ? '· ' + task.error : ''}</div>
        </div>
      </div>
      <div class="download-progress-bar"><div class="download-progress-fill" style="width:${pct}%"></div></div>
      <div class="download-item-actions">
        ${task.status === 'downloading' ? '<button class="btn btn-secondary" data-act="pause">暂停</button>' : ''}
        ${task.status === 'paused' ? '<button class="btn btn-secondary" data-act="resume">继续</button>' : ''}
        ${task.status === 'failed' || task.status === 'paused' ? '<button class="btn btn-secondary" data-act="retry">重试</button>' : ''}
        <button class="btn btn-danger" data-act="remove">删除</button>
      </div>
    `;
    el.querySelector('[data-act="pause"]')?.addEventListener('click', () => downloadManager.pauseTask(task.id));
    el.querySelector('[data-act="resume"]')?.addEventListener('click', () => downloadManager.resumeTask(task.id));
    el.querySelector('[data-act="retry"]')?.addEventListener('click', () => {
      downloadManager.removeTask(task.id);
      // 重新添加
      downloadManager.addTask({ ...task });
    });
    el.querySelector('[data-act="remove"]')?.addEventListener('click', () => downloadManager.removeTask(task.id));
    list.appendChild(el);
  });
}

/* ===== 设置页 ===== */
function initSettingsPage() {
  const qSel = document.getElementById('setting-quality');
  const cSel = document.getElementById('setting-concurrency');
  const pSel = document.getElementById('setting-proxy');
  const pCustom = document.getElementById('setting-proxy-custom');

  qSel.value = state.settings.quality;
  cSel.value = String(state.settings.concurrency);
  pSel.value = state.settings.proxy;
  pCustom.value = state.settings.proxyCustom || '';
  pCustom.classList.toggle('hidden', state.settings.proxy !== 'custom');

  qSel.addEventListener('change', () => {
    state.settings.quality = qSel.value;
    saveSettings();
  });
  cSel.addEventListener('change', () => {
    state.settings.concurrency = parseInt(cSel.value);
    downloadManager.setConcurrency(state.settings.concurrency);
    saveSettings();
  });
  pSel.addEventListener('change', () => {
    state.settings.proxy = pSel.value;
    pCustom.classList.toggle('hidden', pSel.value !== 'custom');
    const proxy = pSel.value === 'custom' ? pCustom.value : pSel.value;
    http.setProxy(proxy);
    saveSettings();
  });
  pCustom.addEventListener('input', () => {
    state.settings.proxyCustom = pCustom.value;
    if (state.settings.proxy === 'custom') http.setProxy(pCustom.value);
    saveSettings();
  });
}

/* ===== PWA ===== */
function initPWA() {
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('sw.js').catch(err => {
        console.log('SW 注册失败:', err);
      });
    });
  }
}

/* ===== Toast ===== */
let toastTimer = null;
function showToast(msg) {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.add('hidden'), 2500);
}
