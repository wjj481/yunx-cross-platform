/**
 * 云析 Web 客户端 - 各平台解析器
 * 从云析 Python 核心引擎移植的前端 JS 版本
 * 支持：B站、抖音、YouTube、网易云音乐、QQ音乐
 */

/* ===== 通用 HTTP 请求（带 CORS 代理） ===== */
class HttpClient {
  constructor() {
    this.proxyPrefix = '';
    this.userAgent = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1';
  }

  setProxy(prefix) {
    this.proxyPrefix = prefix || '';
  }

  // 构造代理 URL
  _proxy(url) {
    if (!this.proxyPrefix) return url;
    // 处理不同代理格式
    if (this.proxyPrefix.includes('?url=')) {
      return this.proxyPrefix + encodeURIComponent(url);
    }
    return this.proxyPrefix + url;
  }

  async get(url, headers = {}) {
    const proxied = this._proxy(url);
    const opts = { method: 'GET', headers: {} };
    // 浏览器无法设置 Referer 等敏感头，只能设置 Accept 等
    if (headers.Referer) opts.headers['Referer'] = headers.Referer;
    const resp = await fetch(proxied, opts);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp;
  }

  async getJson(url, headers = {}) {
    const resp = await this.get(url, headers);
    return resp.json();
  }

  async postJson(url, body, headers = {}) {
    const proxied = this._proxy(url);
    const opts = {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', ...headers },
      body: typeof body === 'string' ? body : new URLSearchParams(body).toString()
    };
    const resp = await fetch(proxied, opts);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  async getText(url, headers = {}) {
    const resp = await this.get(url, headers);
    return resp.text();
  }
}

const http = new HttpClient();

/* ===== 解析结果数据结构 ===== */
class QualityOption {
  constructor(quality, fileSize = 0, format = 'mp4', code = '', description = '') {
    this.quality = quality;
    this.fileSize = fileSize;
    this.format = format;
    this.code = code;
    this.description = description;
  }
}

class ParseResult {
  constructor() {
    this.title = '';
    this.cover = '';
    this.duration = 0;
    this.qualityList = [];
    this.platform = '';
    this.videoId = '';
    this.raw = {};
    this.extra = {};
    this.isMusic = false;
  }
  bestQuality() { return this.qualityList[0] || null; }
  findQuality(q) {
    const t = q.toLowerCase();
    return this.qualityList.find(item => item.quality.toLowerCase() === t) || null;
  }
}

/* ===== B站解析器 ===== */
class BilibiliParser {
  constructor() {
    this.name = 'bilibili';
    this.displayName = '哔哩哔哩';
    this.domains = ['bilibili.com', 'b23.tv', 'bilibili.cn'];
    this.apiBase = 'https://api.bilibili.com';
    this.wbiKeys = null;
    this.wbiExpire = 0;
    this.USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';
    this.REFERER = 'https://www.bilibili.com';
    // qn 映射
    this.QN_MAP = {
      127: ['8k', '8K 超高清'], 126: ['dolby', '杜比视界'], 125: ['hdr', 'HDR 真彩'],
      120: ['4k', '4K 超清'], 116: ['1080p60', '1080P 60帧'], 112: ['1080p+', '1080P 高码率'],
      80: ['1080p', '1080P 高清'], 74: ['720p60', '720P 60帧'], 64: ['720p', '720P 高清'],
      32: ['480p', '480P 清晰'], 16: ['360p', '360P 流畅']
    };
  }

  matches(url) {
    try {
      const host = new URL(url).hostname.toLowerCase();
      return this.domains.some(d => host === d || host.endsWith('.' + d));
    } catch { return false; }
  }

  async parse(url) {
    // 提取 BV/AV 号
    let bvid = '', aid = 0, page = 1;
    const bvMatch = url.match(/BV[0-9A-Za-z]{10}/);
    if (bvMatch) bvid = bvMatch[0];
    const avMatch = url.match(/[Aa][Vv](\d+)/);
    if (avMatch && !bvid) aid = parseInt(avMatch[1]);
    const pMatch = url.match(/[?&]p=(\d+)/);
    if (pMatch) page = parseInt(pMatch[1]);

    if (!bvid && !aid) throw new Error('无法从链接中提取 BV/AV 号');

    // 获取视频信息
    const viewParams = bvid ? { bvid } : { aid };
    const viewData = await this._apiGet('/x/web-interface/view', viewParams);

    const result = new ParseResult();
    result.platform = this.name;
    result.title = viewData.title || '未知视频';
    result.cover = viewData.pic || '';
    result.duration = viewData.duration || 0;
    result.videoId = bvid || String(aid);
    result.raw = viewData;

    // 分P处理
    const pages = viewData.pages || [];
    if (pages.length > 0) {
      page = Math.max(1, Math.min(page, pages.length));
      const currentPage = pages[page - 1];
      const cid = currentPage.cid || viewData.cid || 0;
      if (pages.length > 1 && currentPage.part) {
        result.title = `${result.title} - P${page} ${currentPage.part}`;
      }
      result.extra = { aid: viewData.aid, bvid: viewData.bvid, cid, page, pages };
    } else {
      result.extra = { aid: viewData.aid, bvid: viewData.bvid, cid: viewData.cid || 0, page: 1 };
    }

    // 获取清晰度列表
    result.qualityList = await this._fetchQualityList(result.extra.bvid, result.extra.cid);
    return result;
  }

  async getDownloadUrl(result, quality) {
    const opt = result.findQuality(quality);
    if (!opt) throw new Error(`不支持的清晰度: ${quality}`);
    const qn = this._qualityToQn(quality);
    const params = {
      bvid: result.extra.bvid, cid: result.extra.cid,
      qn, fnval: 16, fnver: 0, fourk: 1
    };
    const data = await this._apiGet('/x/player/playurl', params);
    // DASH 格式
    if (data.dash) {
      for (const stream of (data.dash.video || [])) {
        if (stream.id === qn) return stream.baseUrl || stream.base_url || '';
      }
    }
    // durl 格式
    if (data.durl && data.durl.length > 0) return data.durl[0].url || '';
    throw new Error('未获取到下载地址，可能需要登录或接口已变更');
  }

  async _fetchWbiKeys() {
    const now = Date.now() / 1000;
    if (this.wbiKeys && now < this.wbiExpire) return this.wbiKeys;
    try {
      const data = await this._apiGet('/x/web-interface/nav', {}, false);
      const wbiImg = data.wbi_img || {};
      const imgKey = (wbiImg.img_url || '').split('/').pop().split('.')[0];
      const subKey = (wbiImg.sub_url || '').split('/').pop().split('.')[0];
      this.wbiKeys = [imgKey, subKey];
      this.wbiExpire = now + 3600;
      return this.wbiKeys;
    } catch (e) {
      return ['', ''];
    }
  }

  async _apiGet(path, params = {}, sign = true) {
    let signedParams = Object.assign({}, params);
    if (sign && (path.includes('web-interface') || path.includes('player'))) {
      try {
        const [imgKey, subKey] = await this._fetchWbiKeys();
        if (imgKey && subKey) signedParams = BiliWbi.sign(signedParams, imgKey, subKey);
      } catch (e) { /* 降级无签名 */ }
    }
    const qs = new URLSearchParams(signedParams).toString();
    const url = `${this.apiBase}${path}?${qs}`;
    const data = await http.getJson(url, { Referer: this.REFERER });
    if (data.code !== 0) {
      if (data.code === -101 || data.code === -403) {
        throw new Error('需要登录才能获取此内容的高清晰度');
      }
      throw new Error(`B站 API 错误: ${data.message || 'unknown'}`);
    }
    return data.data;
  }

  _qualityToQn(quality) {
    const reverse = {};
    for (const [k, v] of Object.entries(this.QN_MAP)) reverse[v[0]] = parseInt(k);
    return reverse[quality.toLowerCase()] || 80;
  }

  async _fetchQualityList(bvid, cid) {
    const params = { bvid, cid, qn: 127, fnval: 16, fnver: 0, fourk: 1 };
    try {
      const data = await this._apiGet('/x/player/playurl', params);
      const acceptQuality = data.accept_quality || [];
      const list = [];
      for (const qn of acceptQuality) {
        if (this.QN_MAP[qn]) {
          const [qid, desc] = this.QN_MAP[qn];
          // 估算文件大小
          let fileSize = 0;
          if (data.dash && data.dash.video) {
            for (const s of data.dash.video) {
              if (s.id === qn) {
                fileSize = Math.floor((s.bandwidth || 0) * (data.timelength || 0) / 8000);
                break;
              }
            }
          }
          list.push(new QualityOption(qid, fileSize, 'mp4', String(qn), desc));
        }
      }
      return list;
    } catch (e) {
      // 未登录降级
      return [
        new QualityOption('720p', 0, 'flv', '64', '720P 高清'),
        new QualityOption('480p', 0, 'flv', '32', '480P 清晰'),
        new QualityOption('360p', 0, 'flv', '16', '360P 流畅')
      ];
    }
  }
}

/* ===== 抖音解析器 ===== */
class DouyinParser {
  constructor() {
    this.name = 'douyin';
    this.displayName = '抖音';
    this.domains = ['douyin.com', 'iesdouyin.com'];
    this.apiBase = 'https://www.douyin.com';
    this.USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';
    this.REFERER = 'https://www.douyin.com/';
  }

  matches(url) {
    try {
      const host = new URL(url).hostname.toLowerCase();
      return this.domains.some(d => host === d || host.endsWith('.' + d)) || url.includes('v.douyin.com');
    } catch { return false; }
  }

  async parse(url) {
    // 短链重定向
    let resolvedUrl = url;
    if (url.includes('v.douyin.com')) {
      try {
        const resp = await fetch(url, { method: 'HEAD', redirect: 'follow' });
        resolvedUrl = resp.url;
      } catch (e) { /* 尝试直接解析 */ }
    }
    // 提取 aweme_id
    let awemeId = '';
    const m1 = resolvedUrl.match(/\/video\/(\d+)/);
    const m2 = resolvedUrl.match(/\/note\/(\d+)/);
    if (m1) awemeId = m1[1];
    else if (m2) awemeId = m2[1];
    else throw new Error('无法从链接中提取视频 ID，请确认链接是否正确');

    // 调用详情 API
    const awemeData = await this._fetchDetail(awemeId);
    const result = new ParseResult();
    result.platform = this.name;
    result.videoId = awemeId;
    result.title = (awemeData.desc || '抖音视频').replace(/\s+/g, ' ').trim();
    result.duration = Math.floor((awemeData.video?.duration || 0) / 1000);
    result.cover = awemeData.video?.cover?.url_list?.[0] || '';
    result.raw = awemeData;
    result.extra = {
      author: awemeData.author?.nickname || '',
      isNote: awemeData.aweme_type === 68
    };
    // 清晰度列表
    result.qualityList = this._buildQualityList(awemeData.video || {});
    return result;
  }

  async getDownloadUrl(result, quality) {
    const video = result.raw.video || {};
    const playAddr = video.play_addr || {};
    let urlList = playAddr.url_list || [];
    // 降级到 bit_rate
    if (urlList.length === 0) {
      for (const br of (video.bit_rate || [])) {
        if ((br.gear_name || '').toLowerCase() === quality.toLowerCase()) {
          urlList = br.play_addr?.url_list || [];
          break;
        }
      }
    }
    if (urlList.length === 0) throw new Error('未找到视频下载地址');
    return urlList[0];
  }

  async _fetchDetail(awemeId) {
    const params = {
      aweme_id: awemeId, device_platform: 'webapp', aid: '6383',
      channel: 'channel_pc_web', pc_client_type: '1', version_code: '190500',
      version_name: '19.5.0', cookie_enabled: 'true', platform: 'PC', downlink: '10'
    };
    // 生成简易 X-Bogus（前端简化版）
    const qs = new URLSearchParams(params).toString();
    const xb = this._generateXBogus(qs, this.USER_AGENT);
    params['X-Bogus'] = xb;
    const apiUrl = `${this.apiBase}/aweme/v1/web/aweme/detail/?${new URLSearchParams(params).toString()}`;
    try {
      const data = await http.getJson(apiUrl, { Referer: `${this.REFERER}video/${awemeId}` });
      if (data.status_code !== 0) throw new Error(data.status_msg || '解析失败');
      return data.aweme_detail || {};
    } catch (e) {
      // 降级：尝试从页面 HTML 提取 RENDER_DATA
      const pageData = await this._fetchFromPage(awemeId);
      if (pageData) return pageData;
      throw new Error(`抖音解析失败: ${e.message || '接口可能已变更'}`);
    }
  }

  async _fetchFromPage(awemeId) {
    try {
      const html = await http.getText(`${this.apiBase}/video/${awemeId}`, { Referer: this.REFERER });
      const m = html.match(/<script id="RENDER_DATA"[^>]*>(.*?)<\/script>/s);
      if (!m) return null;
      const decoded = decodeURIComponent(m[1]);
      const data = JSON.parse(decoded);
      const app = data.app || data;
      const items = app.videoInfoRes?.item_list || [];
      return items[0] || null;
    } catch { return null; }
  }

  _generateXBogus(query, ua) {
    // 简化版 X-Bogus（前端环境下完整算法难以复刻，使用简化签名）
    const salt = [0xF0,0xE5,0x6A,0x3C,0x8F,0xDB,0x52,0x99,0x17,0xB4,0x7E,0xC8,0x2D,0xA1,0x46,0x03];
    const qMd5 = MD5.hash(query).slice(0, 16);
    const uMd5 = MD5.hash(ua).slice(0, 16);
    const ts = Math.floor(Date.now() / 1000);
    // 组合并简单变换
    let combined = qMd5 + uMd5 + ts.toString(16);
    let result = MD5.hash(combined).slice(0, 24);
    // 加前缀
    return 'DFLS' + result;
  }

  _buildQualityList(video) {
    const list = [];
    const bitRates = video.bit_rate || [];
    if (bitRates.length > 0) {
      for (const br of bitRates) {
        const gear = (br.gear_name || '').toLowerCase();
        list.push(new QualityOption(
          gear || '480p',
          br.play_addr?.data_size || 0,
          'mp4', String(br.bit_rate || ''),
          br.gear_name || gear
        ));
      }
    } else {
      list.push(new QualityOption('720p', video.play_addr?.data_size || 0, 'mp4', '0', '720P 高清'));
    }
    list.sort((a, b) => b.fileSize - a.fileSize);
    return list;
  }
}

/* ===== YouTube 解析器 ===== */
class YoutubeParser {
  constructor() {
    this.name = 'youtube';
    this.displayName = 'YouTube';
    this.domains = ['youtube.com', 'youtu.be', 'youtube-nocookie.com'];
    this.WATCH_URL = 'https://www.youtube.com/watch';
    this.USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';
    // itag 映射
    this.ITAG_MAP = {
      18: ['360p', 'mp4', true], 22: ['720p', 'mp4', true],
      37: ['1080p', 'mp4', true], 43: ['360p', 'webm', true],
      44: ['480p', 'webm', true], 45: ['720p', 'webm', true], 46: ['1080p', 'webm', true],
      133: ['240p', 'mp4', false], 134: ['360p', 'mp4', false],
      135: ['480p', 'mp4', false], 136: ['720p', 'mp4', false], 137: ['1080p', 'mp4', false],
      138: ['2160p', 'mp4', false], 160: ['144p', 'mp4', false],
      298: ['720p60', 'mp4', false], 299: ['1080p60', 'mp4', false],
      167: ['360p', 'webm', false], 168: ['480p', 'webm', false],
      169: ['720p', 'webm', false], 170: ['1080p', 'webm', false]
    };
  }

  matches(url) {
    try {
      const host = new URL(url).hostname.toLowerCase();
      return this.domains.some(d => host === d || host.endsWith('.' + d));
    } catch { return false; }
  }

  async parse(url) {
    const videoId = this._extractId(url);
    // 从 watch 页面提取 playerResponse
    const playerResp = await this._fetchPlayerResponse(videoId);
    const result = new ParseResult();
    result.platform = this.name;
    result.videoId = videoId;
    const details = playerResp.videoDetails || {};
    result.title = details.title || 'YouTube Video';
    result.cover = details.thumbnail?.thumbnails?.pop()?.url || '';
    result.duration = parseInt(details.lengthSeconds || 0);
    result.raw = playerResp;
    result.extra = { author: details.author || '' };
    result.qualityList = this._buildQualityList(playerResp);
    return result;
  }

  async getDownloadUrl(result, quality) {
    const opt = result.findQuality(quality);
    if (!opt) throw new Error(`不支持的清晰度: ${quality}`);
    const itag = parseInt(opt.code);
    const streaming = result.raw.streamingData || {};
    // 渐进式格式
    for (const fmt of (streaming.formats || [])) {
      if (fmt.itag === itag) return this._extractUrl(fmt);
    }
    // DASH 格式
    for (const fmt of (streaming.adaptiveFormats || [])) {
      if (fmt.itag === itag) return this._extractUrl(fmt);
    }
    throw new Error('视频流 URL 被加密保护，YouTube 签名解密在纯前端支持有限');
  }

  _extractId(url) {
    try {
      const u = new URL(url);
      if (u.hostname.includes('youtu.be')) {
        const id = u.pathname.slice(1);
        if (/^[0-9A-Za-z_-]{11}$/.test(id)) return id;
      }
      if (u.pathname === '/watch') {
        const v = u.searchParams.get('v');
        if (v) return v;
      }
      for (const prefix of ['/embed/', '/shorts/', '/live/', '/v/']) {
        if (u.pathname.startsWith(prefix)) {
          const id = u.pathname.slice(prefix.length).split('/')[0];
          if (/^[0-9A-Za-z_-]{11}$/.test(id)) return id;
        }
      }
    } catch {}
    const m = url.match(/[0-9A-Za-z_-]{11}/);
    if (m) return m[0];
    throw new Error('无法从链接中提取 YouTube 视频 ID');
  }

  async _fetchPlayerResponse(videoId) {
    const url = `${this.WATCH_URL}?v=${videoId}&hl=en&has_verified=1`;
    const html = await http.getText(url);
    // 提取 ytInitialPlayerResponse
    let m = html.match(/ytInitialPlayerResponse\s*=\s*(\{.+?\})\s*;/s);
    if (!m) m = html.match(/"playerResponse":\s*(\{.+?\})\s*,\s*"/s);
    if (!m) throw new Error('无法从页面中提取视频数据，YouTube 页面结构可能已变更');
    try {
      return JSON.parse(m[1]);
    } catch {
      throw new Error('视频数据解析失败');
    }
  }

  _buildQualityList(playerResp) {
    const streaming = playerResp.streamingData || {};
    if (!streaming) {
      const status = playerResp.playabilityStatus?.status || 'ERROR';
      const reason = playerResp.playabilityStatus?.reason || '未知';
      throw new Error(`视频不可播放: ${status} - ${reason}`);
    }
    const qmap = {};
    const addFmt = (fmt, hasAudio) => {
      const itag = fmt.itag;
      if (!this.ITAG_MAP[itag]) return;
      const [q, ft] = this.ITAG_MAP[itag];
      const size = parseInt(fmt.contentLength || 0);
      if (!qmap[q] || (hasAudio && !qmap[q]._hasAudio)) {
        qmap[q] = new QualityOption(q, size, ft, String(itag), `${q.toUpperCase()} ${ft.toUpperCase()}${hasAudio ? '（含音频）' : '（仅视频）'}`);
        qmap[q]._hasAudio = hasAudio;
      }
    };
    for (const fmt of (streaming.formats || [])) addFmt(fmt, true);
    for (const fmt of (streaming.adaptiveFormats || [])) {
      if ((fmt.mimeType || '').startsWith('video')) addFmt(fmt, false);
    }
    // 按清晰度排序
    const order = ['2160p','1440p','1080p60','1080p','720p60','720p','480p','360p','240p','144p'];
    const result = [];
    for (const q of order) if (qmap[q]) result.push(qmap[q]);
    for (const q in qmap) if (!result.includes(qmap[q])) result.push(qmap[q]);
    return result;
  }

  _extractUrl(fmt) {
    if (fmt.url) return fmt.url;
    // signatureCipher 加密情况
    const cipher = fmt.signatureCipher || '';
    if (cipher) {
      const params = new URLSearchParams(cipher);
      const baseUrl = params.get('url') || '';
      if (baseUrl) return decodeURIComponent(baseUrl);
    }
    throw new Error('视频流 URL 被加密签名保护');
  }
}

/* ===== 网易云音乐解析器 ===== */
class NeteaseParser {
  constructor() {
    this.name = 'netease';
    this.displayName = '网易云音乐';
    this.domains = ['music.163.com', '163.com'];
    this.apiBase = 'https://music.163.com';
  }

  matches(url) {
    try {
      const host = new URL(url).hostname.toLowerCase();
      return this.domains.some(d => host === d || host.endsWith('.' + d));
    } catch { return false; }
  }

  async parse(url) {
    // 处理 hash 路由
    let normalized = url;
    if (url.includes('#/')) {
      const [base, frag] = url.split('#/');
      normalized = base.replace(/\/$/, '') + '/' + frag.replace(/^\//, '');
    }
    // 提取歌曲 ID
    const m = normalized.match(/(?:song[?/]id=|\/song\/)(\d+)/i);
    if (!m) throw new Error('无法从链接中提取歌曲 ID');
    const songId = m[1];
    // 请求歌曲详情
    const encrypted = await NetEaseCrypto.encrypt({ c: JSON.stringify([{ id: songId }]), ids: `[${songId}]` });
    const data = await http.postJson(`${this.apiBase}/weapi/v3/song/detail`, encrypted);
    if (data.code !== 200) throw new Error(`网易云 API 错误: ${data.message || data.msg || ''}`);
    const songs = data.songs || [];
    if (songs.length === 0) throw new Error('未找到该歌曲');
    const song = songs[0];
    const result = new ParseResult();
    result.isMusic = true;
    result.platform = this.name;
    result.videoId = String(song.id);
    result.title = song.name || '';
    result.cover = song.al?.picUrl || '';
    result.duration = Math.floor((song.dt || 0) / 1000);
    result.raw = song;
    const artists = (song.ar || []).map(a => a.name).join(' / ');
    result.extra = { artist: artists, album: song.al?.name || '', copyrightRestricted: song.noCopyrightRcmd != null };
    result.qualityList = this._buildQualityList(song, result.extra.copyrightRestricted);
    return result;
  }

  async getDownloadUrl(result, quality) {
    if (result.extra.copyrightRestricted) throw new Error('该歌曲因版权限制无法下载');
    const levelMap = { standard: 'standard', higher: 'higher', lossless: 'exhigh' };
    const level = levelMap[quality] || 'standard';
    const encrypted = await NetEaseCrypto.encrypt({
      ids: `[${result.videoId}]`, level, encodeType: 'aac'
    });
    const data = await http.postJson(`${this.apiBase}/weapi/song/enhance/player/url/v1`, encrypted);
    const list = data.data || [];
    if (list.length === 0) throw new Error('未获取到下载地址');
    const url = list[0].url || '';
    if (!url) throw new Error('该歌曲因版权限制或 VIP 限制无法下载');
    return url;
  }

  _buildQualityList(song, restricted) {
    const list = [];
    const add = (q, info, avail) => {
      const extMap = { standard: 'mp3', higher: 'mp3', lossless: 'flac' };
      const brMap = { standard: 128000, higher: 320000, lossless: 999000 };
      list.push(new QualityOption(
        q, info?.size || 0, extMap[q] || 'mp3',
        String(info?.br || brMap[q] || ''),
        `${q === 'standard' ? '标准' : q === 'higher' ? '高品质' : '无损'} ${(info?.br || brMap[q] || 0) / 1000}kbps`,
      ));
    };
    add('standard', song.m || song.l, !restricted && (song.m != null || song.l != null));
    add('higher', song.h, !restricted && song.h != null);
    add('lossless', song.sq, !restricted && song.sq != null);
    return list;
  }
}

/* ===== QQ音乐解析器 ===== */
class QQMusicParser {
  constructor() {
    this.name = 'qqmusic';
    this.displayName = 'QQ音乐';
    this.domains = ['y.qq.com', 'music.qq.com'];
    this.musicuUrl = 'https://u.y.qq.com/cgi-bin/musicu.fcg';
    this.vkeyUrl = 'https://c.y.qq.com/base/fcgi-bin/fcg_music_express_mobile3.fcg';
    this.downloadBase = 'https://dl.stream.qqmusic.qq.com';
    this.cid = '205361747';
    this.uin = '0';
    this.guid = String(Math.floor(Math.random() * 9000000000) + 1000000000);
    this.qualityPrefix = { standard: 'M500', higher: 'M800', lossless: 'F000' };
  }

  matches(url) {
    try {
      const host = new URL(url).hostname.toLowerCase();
      return this.domains.some(d => host === d || host.endsWith('.' + d));
    } catch { return false; }
  }

  async parse(url) {
    const m = url.match(/(?:songDetail\/|\/song\/|songmid=)([A-Za-z0-9]+)/i);
    if (!m) throw new Error('无法从链接中提取歌曲 ID');
    const songmid = m[1];
    const payload = {
      comm: { cv: 4747474, ct: 24, format: 'json', inCharset: 'utf-8', outCharset: 'utf-8', notice: 0, platform: 'yqq.json', needNewCode: 1, uin: this.uin, guid: this.guid },
      req_1: { module: 'music.pf_song_detail_svr', method: 'get_song_detail', param: { song_mid: songmid } }
    };
    const data = await this._musicuRequest(payload);
    const req1 = data.req_1 || {};
    if (req1.code !== 0) throw new Error(`获取歌曲详情失败: ${req1.message || ''}`);
    const track = req1.data?.track_info || {};
    const result = new ParseResult();
    result.isMusic = true;
    result.platform = this.name;
    result.videoId = track.mid || songmid;
    result.title = track.name || '';
    result.cover = track.album?.pic || track.albumPic || '';
    result.duration = track.interval || 0;
    result.raw = track;
    const singers = (track.singer || []).map(s => s.name).join(' / ');
    result.extra = { artist: singers, album: track.album?.name || '', copyrightRestricted: track.status === 1 };
    result.qualityList = this._buildQualityList(track, result.extra.copyrightRestricted);
    return result;
  }

  async getDownloadUrl(result, quality) {
    if (result.extra.copyrightRestricted) throw new Error('该歌曲因版权限制无法下载');
    const prefix = this.qualityPrefix[quality] || 'M500';
    const extMap = { standard: 'mp3', higher: 'mp3', lossless: 'flac' };
    const ext = extMap[quality] || 'mp3';
    const filename = `${prefix}${result.videoId}.${ext}`;
    // 获取 vkey
    const params = { format: 'json', cid: this.cid, uin: this.uin, songmid: result.videoId, filename, guid: this.guid };
    const vkeyData = await http.getJson(`${this.vkeyUrl}?${new URLSearchParams(params).toString()}`);
    const vkey = vkeyData.data?.vkey || '';
    if (!vkey) throw new Error('获取下载凭证失败，可能需要登录或接口已变更');
    return `${this.downloadBase}/${filename}?vkey=${vkey}&guid=${this.guid}&uin=${this.uin}&fromtag=66`;
  }

  async _musicuRequest(payload) {
    const proxied = http._proxy(this.musicuUrl);
    const resp = await fetch(proxied, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    return resp.json();
  }

  _buildQualityList(track, restricted) {
    const list = [];
    const file = track.file || {};
    const add = (q, avail) => {
      const extMap = { standard: 'mp3', higher: 'mp3', lossless: 'flac' };
      const brMap = { standard: 128000, higher: 320000, lossless: 999000 };
      list.push(new QualityOption(q, 0, extMap[q], String(brMap[q]),
        `${q === 'standard' ? '标准' : q === 'higher' ? '高品质' : '无损'} ${brMap[q] / 1000}kbps`));
    };
    add('standard', !restricted && (!file || !!file['128mp3']));
    add('higher', !restricted && !!file['320mp3']);
    add('lossless', !restricted && !!file['flac']);
    return list;
  }
}

/* ===== 解析器工厂 ===== */
class ParserFactory {
  constructor() {
    this.parsers = [
      new BilibiliParser(),
      new DouyinParser(),
      new YoutubeParser(),
      new NeteaseParser(),
      new QQMusicParser()
    ];
  }

  detect(url) {
    for (const p of this.parsers) {
      if (p.matches(url)) return p;
    }
    return null;
  }

  async parse(url) {
    const parser = this.detect(url);
    if (!parser) throw new Error('暂不支持该链接，请检查是否为 B站/抖音/YouTube/网易云/QQ音乐 链接');
    try {
      return await parser.parse(url);
    } catch (e) {
      if (e.message && e.message.includes('跨域')) {
        throw new Error('跨域请求被拦截，请在设置中更换 CORS 代理后重试');
      }
      throw e;
    }
  }
}

const parserFactory = new ParserFactory();
