/**
 * 云析 Web 客户端 - 加密工具库
 * 包含：MD5、AES-CBC、RSA教科书加密、B站wbi签名、抖音X-Bogus签名
 * 从云析 Python 核心引擎移植的加密逻辑
 */

/* ===== MD5 实现（纯JS同步） ===== */
const MD5 = (function() {
  function md5cycle(x, k) {
    var a = x[0], b = x[1], c = x[2], d = x[3];
    a = ff(a,b,c,d,k[0],7,-680876936); d = ff(d,a,b,c,k[1],12,-389564586);
    c = ff(c,d,a,b,k[2],17,606105819); b = ff(b,c,d,a,k[3],22,-1044525330);
    a = ff(a,b,c,d,k[4],7,-176418897); d = ff(d,a,b,c,k[5],12,1200080426);
    c = ff(c,d,a,b,k[6],17,-1473231341); b = ff(b,c,d,a,k[7],22,-45705983);
    a = ff(a,b,c,d,k[8],7,1770035416); d = ff(d,a,b,c,k[9],12,-1958414417);
    c = ff(c,d,a,b,k[10],17,-42063); b = ff(b,c,d,a,k[11],22,-1990404162);
    a = ff(a,b,c,d,k[12],7,1804603682); d = ff(d,a,b,c,k[13],12,-40341101);
    c = ff(c,d,a,b,k[14],17,-1502002290); b = ff(b,c,d,a,k[15],22,1236535329);
    a = gg(a,b,c,d,k[1],5,-165796510); d = gg(d,a,b,c,k[6],9,-1069501632);
    c = gg(c,d,a,b,k[11],14,643717713); b = gg(b,c,d,a,k[0],20,-373897302);
    a = gg(a,b,c,d,k[5],5,-701558691); d = gg(d,a,b,c,k[10],9,38016083);
    c = gg(c,d,a,b,k[15],14,-660478335); b = gg(b,c,d,a,k[4],20,-405537848);
    a = gg(a,b,c,d,k[9],5,568446438); d = gg(d,a,b,c,k[14],9,-1019803690);
    c = gg(c,d,a,b,k[3],14,-187363961); b = gg(b,c,d,a,k[8],20,1163531501);
    a = gg(a,b,c,d,k[13],5,-1444681467); d = gg(d,a,b,c,k[2],9,-51403784);
    c = gg(c,d,a,b,k[7],14,1735328473); b = gg(b,c,d,a,k[12],20,-1926607734);
    a = hh(a,b,c,d,k[5],4,-378558); d = hh(d,a,b,c,k[8],11,-2022574463);
    c = hh(c,d,a,b,k[11],16,1839030562); b = hh(b,c,d,a,k[14],23,-35309556);
    a = hh(a,b,c,d,k[1],4,-1530992060); d = hh(d,a,b,c,k[4],11,1272893353);
    c = hh(c,d,a,b,k[7],16,-155497632); b = hh(b,c,d,a,k[10],23,-1094730640);
    a = hh(a,b,c,d,k[13],4,681279174); d = hh(d,a,b,c,k[0],11,-358537222);
    c = hh(c,d,a,b,k[3],16,-722521979); b = hh(b,c,d,a,k[6],23,76029189);
    a = hh(a,b,c,d,k[9],4,-640364487); d = hh(d,a,b,c,k[12],11,-421815835);
    c = hh(c,d,a,b,k[15],16,530742520); b = hh(b,c,d,a,k[2],23,-995338651);
    a = ii(a,b,c,d,k[0],6,-198630844); d = ii(d,a,b,c,k[7],10,1126891415);
    c = ii(c,d,a,b,k[14],15,-1416354905); b = ii(b,c,d,a,k[5],21,-57434055);
    a = ii(a,b,c,d,k[12],6,1700485571); d = ii(d,a,b,c,k[3],10,-1894986606);
    c = ii(c,d,a,b,k[10],15,-1051523); b = ii(b,c,d,a,k[1],21,-2054922799);
    a = ii(a,b,c,d,k[8],6,1873313359); d = ii(d,a,b,c,k[15],10,-30611744);
    c = ii(c,d,a,b,k[6],15,-1560198380); b = ii(b,c,d,a,k[13],21,1309151649);
    a = ii(a,b,c,d,k[4],6,-145523070); d = ii(d,a,b,c,k[11],10,-1120210379);
    c = ii(c,d,a,b,k[2],15,718787259); b = ii(b,c,d,a,k[9],21,-343485551);
    x[0] = add32(a,x[0]); x[1] = add32(b,x[1]); x[2] = add32(c,x[2]); x[3] = add32(d,x[3]);
  }
  function cmn(q,a,b,x,s,t){ a=add32(add32(add32(a,q),add32(x,t)),s); return add32(add32(a,b),b); }
  function ff(a,b,c,d,x,s,t){ return cmn((b&c)|((~b)&d),a,b,x,s,t); }
  function gg(a,b,c,d,x,s,t){ return cmn((b&d)|(c&(~d)),a,b,x,s,t); }
  function hh(a,b,c,d,x,s,t){ return cmn(b^c^d,a,b,x,s,t); }
  function ii(a,b,c,d,x,s,t){ return cmn(c^(b|(~d)),a,b,x,s,t); }
  function safe_add(x,y){ var lsw=(x&0xFFFF)+(y&0xFFFF); var msw=(x>>16)+(y>>16)+(lsw>>16); return (msw<<16)|(lsw&0xFFFF); }
  function add32(x,y){ return safe_add(x,y); }
  function rhex(n){ var s=""; for(var j=0;j<4;j++) s+=hexchr(n>>(j*8+4)&0x0F)+hexchr(n>>(j*8)&0x0F); return s; }
  function hexchr(x){ return "0123456789abcdef".charAt(x); }
  function str2blks(str){
    var nblk=((str.length+8)>>6)+1; var blks=new Array(nblk*16);
    for(var i=0;i<nblk*16;i++) blks[i]=0;
    for(var i=0;i<str.length;i++) blks[i>>2]|=str.charCodeAt(i)<<((i%4)*8);
    blks[i>>2]|=0x80<<((i%4)*8); blks[nblk*16-2]=str.length*8;
    return blks;
  }
  function md5(str){
    str = unescape(encodeURIComponent(str));
    var x=str2blks(str);
    var a=1732584193, b=-271733879, c=-1732584194, d=271733878;
    for(var i=0;i<x.length;i+=16){
      var olda=a, oldb=b, oldc=c, oldd=d;
      md5cycle([a,b,c,d],x.slice(i,i+16));
      a=x[0]+olda; b=x[1]+oldb; c=x[2]+oldc; d=x[3]+oldd;
    }
    return rhex(a)+rhex(b)+rhex(c)+rhex(d);
  }
  return { hash: md5 };
})();

/* ===== Base64 工具 ===== */
const Base64Util = {
  encode: function(bytes) {
    let binary = '';
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    return btoa(binary);
  },
  decode: function(str) {
    const binary = atob(str);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes;
  },
  // URL安全的base64
  urlSafeEncode: function(bytes) {
    return this.encode(bytes).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
};

/* ===== AES-CBC 加密（Web Crypto API） ===== */
const AES = {
  async encryptCBC(plaintext, key, iv) {
    const enc = new TextEncoder();
    const data = enc.encode(plaintext);
    const cryptoKey = await crypto.subtle.importKey('raw', key, { name: 'AES-CBC' }, false, ['encrypt']);
    const encrypted = await crypto.subtle.encrypt({ name: 'AES-CBC', iv: iv }, cryptoKey, data);
    return new Uint8Array(encrypted);
  }
};

/* ===== RSA 教科书加密（网易云 weapi 用） ===== */
const RSA = {
  // 将十六进制字符串转 BigInt
  hexToBigInt: function(hex) {
    return BigInt('0x' + hex);
  },
  // RSA 教科书加密：反转明文后模幂
  async encrypt(text, modulusHex, exponentHex) {
    const modulus = this.hexToBigInt(modulusHex);
    const exponent = this.hexToBigInt(exponentHex);
    // 反转字符串
    const reversed = text.split('').reverse().join('');
    // 转为字节数组再转 BigInt（大端）
    const bytes = new TextEncoder().encode(reversed);
    let m = 0n;
    for (const b of bytes) m = (m << 8n) | BigInt(b);
    const c = m ** exponent % modulus;
    // 输出为定长 256 字节（512 hex chars）
    return c.toString(16).padStart(512, '0');
  }
};

/* ===== 网易云 weapi 加密 ===== */
const NetEaseCrypto = {
  FIRST_KEY: '0CoJUm6Qyw8W8jud',
  IV: '0102030405060708',
  RSA_MODULUS: '00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7',
  RSA_EXPONENT: '010001',
  CHARSET: 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',

  randomString: function(len) {
    let s = '';
    const arr = new Uint8Array(len);
    crypto.getRandomValues(arr);
    for (let i = 0; i < len; i++) s += this.CHARSET[arr[i] % this.CHARSET.length];
    return s;
  },

  async encrypt(params) {
    const jsonStr = JSON.stringify(params);
    // 第一次 AES-CBC
    const key1 = new TextEncoder().encode(this.FIRST_KEY);
    const iv = new TextEncoder().encode(this.IV);
    const enc1 = await AES.encryptCBC(jsonStr, key1, iv);
    const enc1B64 = Base64Util.encode(enc1);
    // 第二次 AES-CBC（用随机密钥）
    const randomKey = this.randomString(16);
    const key2 = new TextEncoder().encode(randomKey);
    const enc2 = await AES.encryptCBC(enc1B64, key2, iv);
    const enc2B64 = Base64Util.encode(enc2);
    // RSA 加密随机密钥
    const encSecKey = await RSA.encrypt(randomKey, this.RSA_MODULUS, this.RSA_EXPONENT);
    return { params: enc2B64, encSecKey: encSecKey };
  }
};

/* ===== B站 wbi 签名 ===== */
const BiliWbi = {
  MIXIN_KEY_ENC_TAB: [46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13,37,48,7,16,24,55,40,61,26,17,0,1,60,51,30,4,22,25,54,21,56,59,6,63,57,62,11,36,20,34,44,52],

  getMixinKey: function(orig) {
    let key = '';
    for (let i = 0; i < 32; i++) key += orig[this.MIXIN_KEY_ENC_TAB[i]];
    return key;
  },

  sign: function(params, imgKey, subKey) {
    const mixinKey = this.getMixinKey(imgKey + subKey);
    const newParams = Object.assign({}, params);
    newParams.wts = Math.floor(Date.now() / 1000);
    // 按 key 排序
    const sorted = {};
    Object.keys(newParams).sort().forEach(k => sorted[k] = newParams[k]);
    const query = Object.entries(sorted).map(([k,v]) => `${k}=${encodeURIComponent(v)}`).join('&');
    const wRid = MD5.hash(query + mixinKey);
    newParams.w_rid = wRid;
    return newParams;
  }
};

/* ===== BV/AV 号转换 ===== */
const BiliBV = {
  TABLE: 'fZodR9XQDSUm21yCkr6zBqiveYah8bt4xsWpHnJE7jL5VG3guMTKNPAwcF',
  XOR: 177451812,
  ADD: 8728348608,
  POS: [11, 10, 3, 8, 4, 6],

  bvToAv: function(bvid) {
    let r = 0;
    for (let i = 0; i < this.POS.length; i++) {
      r += this.TABLE.indexOf(bvid[this.POS[i]]) * Math.pow(58, i);
    }
    return (r - this.ADD) ^ this.XOR;
  },

  avToBv: function(aid) {
    let x = (aid ^ this.XOR) + this.ADD;
    const r = ['B','V','1',' ',' ','4','1',' ','7',' ',' '];
    for (let i = 0; i < this.POS.length; i++) {
      r[this.POS[i]] = this.TABLE[Math.floor(x / Math.pow(58, i)) % 58];
    }
    return r.join('');
  }
};

/* ===== 工具函数 ===== */
const Utils = {
  // 格式化文件大小
  formatSize: function(bytes) {
    if (!bytes || bytes === 0) return '未知';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
  },
  // 格式化时长
  formatDuration: function(seconds) {
    if (!seconds) return '';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    return `${m}:${String(s).padStart(2,'0')}`;
  },
  // 清理文件名
  sanitizeFilename: function(name) {
    return name.replace(/[\\/:*?"<>|]/g, '_').trim().substring(0, 100);
  },
  // 拼接 URL（处理相对路径）
  resolveUrl: function(baseUrl, relativeUrl) {
    try {
      return new URL(relativeUrl, baseUrl).href;
    } catch (e) {
      return relativeUrl;
    }
  }
};
