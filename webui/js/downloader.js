/**
 * 云析 Web 客户端 - 下载管理器
 * 任务队列、并发控制、进度跟踪、暂停/继续/删除
 */

class DownloadTask {
  constructor(options) {
    this.id = Date.now() + Math.random().toString(36).slice(2, 8);
    this.title = options.title || '未命名';
    this.cover = options.cover || '';
    this.platform = options.platform || '';
    this.quality = options.quality || '';
    this.url = options.url || '';
    this.isM3u8 = options.isM3u8 || false;
    this.filename = options.filename || 'download.mp4';
    this.status = 'pending'; // pending | downloading | paused | completed | failed
    this.progress = 0;
    this.downloadedBytes = 0;
    this.totalBytes = 0;
    this.speed = 0;
    this.error = '';
    this._m3u8dl = null;
    this._directdl = null;
  }
}

class DownloadManager {
  constructor() {
    this.tasks = [];
    this.maxConcurrency = 2;
    this.activeCount = 0;
    this.listeners = [];
  }

  setConcurrency(n) {
    this.maxConcurrency = Math.max(1, Math.min(2, n));
    this._processQueue();
  }

  // 添加任务
  addTask(options) {
    const task = new DownloadTask(options);
    this.tasks.unshift(task);
    this._notify();
    this._processQueue();
    return task;
  }

  // 处理队列
  _processQueue() {
    const pending = this.tasks.filter(t => t.status === 'pending');
    const running = this.tasks.filter(t => t.status === 'downloading');
    const slots = this.maxConcurrency - running.length;
    for (let i = 0; i < Math.min(slots, pending.length); i++) {
      this._startTask(pending[i]);
    }
  }

  async _startTask(task) {
    task.status = 'downloading';
    task.error = '';
    this._notify();
    try {
      let blob;
      if (task.isM3u8) {
        task._m3u8dl = new M3u8Downloader();
        blob = await task._m3u8dl.download(task.url, (percent, done, total) => {
          task.progress = percent;
          task.downloadedBytes = done;
          task.totalBytes = total;
          this._notify();
        });
      } else {
        task._directdl = new DirectDownloader();
        blob = await task._directdl.download(task.url, (percent, done, total) => {
          task.progress = percent;
          task.downloadedBytes = done;
          task.totalBytes = total;
          this._notify();
        });
      }
      // 保存文件
      FileSaver.saveBlob(blob, task.filename);
      task.status = 'completed';
      task.progress = 100;
    } catch (e) {
      task.status = 'failed';
      task.error = e.message || '下载失败';
    }
    this._notify();
    this._processQueue();
  }

  // 暂停任务
  pauseTask(taskId) {
    const task = this.tasks.find(t => t.id === taskId);
    if (!task || task.status !== 'downloading') return;
    if (task._m3u8dl) task._m3u8dl.cancel();
    if (task._directdl) task._directdl.cancel();
    task.status = 'paused';
    this._notify();
  }

  // 继续任务
  resumeTask(taskId) {
    const task = this.tasks.find(t => t.id === taskId);
    if (!task || task.status !== 'paused') return;
    task.status = 'pending';
    task.progress = 0;
    this._notify();
    this._processQueue();
  }

  // 删除任务
  removeTask(taskId) {
    const idx = this.tasks.findIndex(t => t.id === taskId);
    if (idx === -1) return;
    const task = this.tasks[idx];
    if (task._m3u8dl) task._m3u8dl.cancel();
    if (task._directdl) task._directdl.cancel();
    this.tasks.splice(idx, 1);
    this._notify();
    this._processQueue();
  }

  // 清空已完成
  clearCompleted() {
    this.tasks = this.tasks.filter(t => t.status !== 'completed');
    this._notify();
  }

  // 监听变化
  onUpdate(cb) {
    this.listeners.push(cb);
  }

  _notify() {
    this.listeners.forEach(cb => cb(this.tasks));
  }

  get count() { return this.tasks.length; }
}

const downloadManager = new DownloadManager();
