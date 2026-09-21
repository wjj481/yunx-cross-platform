/**
 * 云析 Web 客户端 - Service Worker（懒加载缓存版 v0.2.0）
 *
 * 设计原则：
 * 1. install 阶段不预缓存任何资源，避免网络波动导致整个 SW 安装失败（Load failed）
 * 2. 资源被浏览器实际请求后才写入缓存（按需缓存）
 * 3. 网络优先：页面永远尽量拿最新版；失败时回退缓存（离线可用）
 * 4. 跨域 API 请求（解析接口/CORS 代理）一律不拦截，直接走网络
 */

const CACHE_NAME = 'yunx-v0.2.0';

// 安装：不预缓存，立即激活
self.addEventListener('install', event => {
  self.skipWaiting();
});

// 激活：清理旧版本缓存，接管所有客户端
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// 拦截请求
self.addEventListener('fetch', event => {
  const req = event.request;

  // 只处理 GET
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  // 跨域请求（解析 API、CORS 代理等）不缓存，直接放行
  if (url.origin !== location.origin) return;

  // 网络优先：先尝试网络，成功后缓存副本；失败时回退本地缓存
  event.respondWith(
    fetch(req).then(resp => {
      // 只缓存成功的、同源的基本响应
      if (resp && resp.ok && resp.type === 'basic') {
        const clone = resp.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(req, clone));
      }
      return resp;
    }).catch(() =>
      caches.match(req).then(cached => cached || caches.match('./'))
    )
  );
});
