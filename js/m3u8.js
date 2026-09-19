/**
 * 云析 Web 客户端 - m3u8 下载合并模块
 * 解析 m3u8 播放列表，下载分片，合并为单个视频文件
 */

class M3u8Downloader {
  constructor() {
    this.abortController = null;
  }

  /**
   * 解析 m3u8 内容，获取分片 URL 列表
   */
  async parseM3u8(m3u8Url, m3u8Content) {
    const lines = m3u8Content.split('\n').map(l => l.trim()).filter(l => l && !l.startsWith('#'));
    const segments = [];
    for (const line of lines) {
      // 相对路径转绝对路径
      const absUrl = Utils.resolveUrl(m3u8Url, line);
      segments.push(absUrl);
    }
    // 检查是否为 m3u8 索引（多级播放列表）
    if (m3u8Content.includes('#EXT-X-STREAM-INF')) {
      // 这是一个 master playlist，需要选择最高码率的子播放列表
      const subUrls = [];
      const lines2 = m3u8Content.split('\n').map(l => l.trim());
      for (let i = 0; i < lines2.length; i++) {
        if (lines2[i].startsWith('#EXT-X-STREAM-INF')) {
          // 下一行是 URL
          if (i + 1 < lines2.length && lines2[i+1] && !lines2[i+1].startsWith('#')) {
            subUrls.push({ url: lines2[i+1], line: lines2[i] });
          }
        }
      }
      if (subUrls.length > 0) {
        // 选择第一个（通常是最高码率）
        const subUrl = Utils.resolveUrl(m3u8Url, subUrls[0].url);
        const subContent = await this._fetchText(subUrl);
        return this.parseM3u8(subUrl, subContent);
      }
    }
    return segments;
  }

  async _fetchText(url) {
    const proxied = http._proxy(url);
    const resp = await fetch(proxied);
    return resp.text();
  }

  async _fetchArrayBuffer(url) {
    const proxied = http._proxy(url);
    const resp = await fetch(proxied);
    return resp.arrayBuffer();
  }

  /**
   * 下载 m3u8 视频并合并
   * @param {string} m3u8Url - m3u8 播放列表 URL
   * @param {Function} onProgress - 进度回调 (percent, downloadedBytes, totalBytes)
   * @returns {Blob} 合并后的视频 Blob
   */
  async download(m3u8Url, onProgress) {
    this.abortController = new AbortController();
    // 获取 m3u8 内容
    const m3u8Content = await this._fetchText(m3u8Url);
    // 解析分片
    const segments = await this.parseM3u8(m3u8Url, m3u8Content);
    if (segments.length === 0) throw new Error('m3u8 中未找到视频分片');
    // 检查是否加密
    if (m3u8Content.includes('#EXT-X-KEY')) {
      throw new Error('资源受保护（加密视频），无法在纯前端环境下载');
    }
    // 并发下载分片（限制为 3 个并发）
    const CONCURRENCY = 3;
    const total = segments.length;
    const downloaded = new Array(total);
    let completed = 0;
    let index = 0;

    const worker = async () => {
      while (index < total) {
        const myIndex = index++;
        if (this.abortController.signal.aborted) throw new Error('下载已取消');
        try {
          const buf = await this._fetchArrayBuffer(segments[myIndex]);
          downloaded[myIndex] = buf;
          completed++;
          if (onProgress) onProgress(completed / total * 100, completed, total);
        } catch (e) {
          // 单个分片失败，重试一次
          try {
            const buf = await this._fetchArrayBuffer(segments[myIndex]);
            downloaded[myIndex] = buf;
            completed++;
            if (onProgress) onProgress(completed / total * 100, completed, total);
          } catch (e2) {
            throw new Error(`分片 ${myIndex + 1} 下载失败: ${e2.message}`);
          }
        }
      }
    };

    // 启动并发 worker
    const workers = [];
    for (let i = 0; i < Math.min(CONCURRENCY, total); i++) workers.push(worker());
    await Promise.all(workers);

    // 合并所有分片
    const blob = new Blob(downloaded, { type: 'video/MP2T' });
    return blob;
  }

  cancel() {
    if (this.abortController) this.abortController.abort();
  }
}

/* ===== 普通文件下载（非 m3u8） ===== */
class DirectDownloader {
  constructor() {
    this.abortController = null;
  }

  /**
   * 直接下载文件为 Blob
   */
  async download(url, onProgress) {
    this.abortController = new AbortController();
    const proxied = http._proxy(url);
    const resp = await fetch(proxied);
    if (!resp.ok) throw new Error(`下载失败: HTTP ${resp.status}`);
    // 尝试获取总大小
    const total = parseInt(resp.headers.get('content-length') || 0);
    if (resp.body && total > 0) {
      // 流式下载，支持进度
      const reader = resp.body.getReader();
      const chunks = [];
      let received = 0;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        received += value.length;
        if (onProgress) onProgress(received / total * 100, received, total);
      }
      return new Blob(chunks);
    } else {
      // 无进度模式
      const buf = await resp.arrayBuffer();
      if (onProgress) onProgress(100, buf.byteLength, buf.byteLength);
      return new Blob([buf]);
    }
  }

  cancel() {
    if (this.abortController) this.abortController.abort();
  }
}

/* ===== 保存文件到 iPhone「文件」App ===== */
const FileSaver = {
  /**
   * 触发浏览器下载，保存到 iPhone 文件 App
   */
  saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    // iOS Safari 兼容：延迟移除
    setTimeout(() => {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 1000);
  },

  /**
   * 直接打开 URL 下载（用于无法跨域的直链）
   */
  openUrl(url) {
    window.open(url, '_blank');
  }
};
