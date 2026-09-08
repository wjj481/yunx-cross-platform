"""
网易云音乐解析器。

完整支持单曲/歌单/专辑解析与多音质直链获取。

加密机制：
- **weapi**：AES-CBC 双重加密 + RSA 加密随机密钥
  1. JSON 参数经 AES-CBC（key=``0CoJUm6Qyw8W8jud``，IV=``0102030405060708``）加密
  2. 生成 16 位随机字符串作为二次 AES-CBC 密钥
  3. 随机密钥经 RSA（公钥模数/指数）加密为 ``encSecKey``
- **eapi**：AES-ECB 单重加密（key=``e82ckenh8dichen8``），用于客户端接口

高音质（320kbps / 无损 FLAC）需要登录 Cookie（包含 ``MUSIC_U`` 字段）。

API 端点：
- 歌曲详情：``/weapi/v3/song/detail``
- 歌曲直链：``/weapi/song/enhance/player/url/v1``
- 歌单详情：``/weapi/v3/playlist/detail``
- 专辑详情：``/weapi/v1/album/{album_id}``
"""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any
from urllib.parse import urlparse, parse_qs

import requests

from ..exceptions import NetworkError, ParserError
from .base import (
    BaseMusicParser,
    PlaylistInfo,
    QUALITY_EXTENSIONS,
    QUALITY_HIGHER,
    QUALITY_LOSSLESS,
    QUALITY_STANDARD,
    SongInfo,
    QualityInfo,
)

# ---------- 常量 ----------

API_BASE = "https://music.163.com"
WEAPI_BASE = f"{API_BASE}/weapi"
EAPI_BASE = f"{API_BASE}/eapi"

# weapi AES 密钥与 IV
_WEAPI_FIRST_KEY = b"0CoJUm6Qyw8W8jud"
_WEAPI_IV = b"0102030405060708"
# eapi AES 密钥
_EAPI_KEY = b"e82ckenh8dichen8"

# RSA 公钥（模数 / 指数）
_RSA_MODULUS = (
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725152b3ab17"
    "a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312ecbda92557c93870114"
    "af6c9d05c4f7f0c3685b7a46bee255932575cce10b424d813cfe4875d3e82047b97ddef5274"
    "1d546b8e289dc6935b3ece0462db0a22b8e7"
)
_RSA_EXPONENT = "010001"

# 随机字符串字符集
_RANDOM_CHARSET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

# 网易云音质 level 映射
_QUALITY_LEVEL_MAP = {
    QUALITY_STANDARD: "standard",
    QUALITY_HIGHER: "higher",
    QUALITY_LOSSLESS: "exhigh",
}

# 网易云音质 br（比特率）映射
_QUALITY_BITRATE_MAP = {
    QUALITY_STANDARD: 128000,
    QUALITY_HIGHER: 320000,
    QUALITY_LOSSLESS: 999000,
}

# User-Agent
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# URL 正则
_SONG_ID_RE = re.compile(r"(?:song[?/]id=|/song/)(\d+)", re.IGNORECASE)
_PLAYLIST_ID_RE = re.compile(r"(?:playlist[?/]id=|/playlist/)(\d+)", re.IGNORECASE)
_ALBUM_ID_RE = re.compile(r"(?:album[?/]id=|/album/)(\d+)", re.IGNORECASE)


def _random_string(length: int = 16) -> str:
    """生成指定长度的随机字符串。

    Args:
        length: 字符串长度。

    Returns:
        随机字符串。
    """
    return "".join(
        _RANDOM_CHARSET[os.urandom(1)[0] % len(_RANDOM_CHARSET)]
        for _ in range(length)
    )


def _aes_cbc_encrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    """AES-CBC 加密（PKCS7 填充）。

    Args:
        data: 待加密数据。
        key: AES 密钥（16/24/32 字节）。
        iv: 初始化向量（16 字节）。

    Returns:
        Base64 编码的密文。
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_padding

    padder = sym_padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    ct = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(ct)


def _aes_ecb_encrypt(data: bytes, key: bytes) -> bytes:
    """AES-ECB 加密（PKCS7 填充）。

    Args:
        data: 待加密数据。
        key: AES 密钥。

    Returns:
        十六进制密文。
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_padding

    padder = sym_padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()

    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    ct = encryptor.update(padded) + encryptor.finalize()
    return ct.hex().encode("ascii")


def _rsa_encrypt(data: bytes) -> str:
    """RSA 加密（使用网易云公钥，无填充，结果反转后十六进制编码）。

    Args:
        data: 待加密数据（通常为随机密钥字符串）。

    Returns:
        十六进制密文。
    """
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
    from cryptography.hazmat.backends import default_backend

    modulus = int(_RSA_MODULUS, 16)
    exponent = int(_RSA_EXPONENT, 16)
    public_numbers = RSAPublicNumbers(exponent, modulus)
    public_key = public_numbers.public_key(default_backend())

    # 网易云 RSA：反转明文后做模幂（等价于无填充 RSA）
    reversed_data = data[::-1]
    m = int.from_bytes(reversed_data, "big")
    c = pow(m, exponent, modulus)
    # 输出为定长 256 字节十六进制
    return format(c, "0256x")


def weapi_encrypt(params: dict[str, Any]) -> dict[str, str]:
    """weapi 参数加密。

    Args:
        params: 原始参数字典。

    Returns:
        包含 ``params`` 和 ``encSecKey`` 的加密后字典。
    """
    json_str = json.dumps(params, ensure_ascii=False, separators=(",", ":"))

    # 第一次 AES-CBC 加密
    first_encrypted = _aes_cbc_encrypt(
        json_str.encode("utf-8"), _WEAPI_FIRST_KEY, _WEAPI_IV
    )

    # 生成随机密钥并第二次 AES-CBC 加密
    random_key = _random_string(16)
    second_encrypted = _aes_cbc_encrypt(
        first_encrypted, random_key.encode("utf-8"), _WEAPI_IV
    )

    # RSA 加密随机密钥
    enc_sec_key = _rsa_encrypt(random_key.encode("utf-8"))

    return {
        "params": second_encrypted.decode("ascii"),
        "encSecKey": enc_sec_key,
    }


def eapi_encrypt(path: str, params: dict[str, Any]) -> dict[str, str]:
    """eapi 参数加密。

    Args:
        path: API 路径（如 ``/api/song/enhance/player/url``）。
        params: 原始参数字典。

    Returns:
        包含 ``params`` 的加密后字典。
    """
    json_str = json.dumps(params, ensure_ascii=False, separators=(",", ":"))
    # eapi 前缀：path + "-36cd479b6b5-" + json
    prefix = f"{path}-36cd479b6b5-{json_str}"
    encrypted = _aes_ecb_encrypt(prefix.encode("utf-8"), _EAPI_KEY)
    return {"params": encrypted.decode("ascii")}


class NetEaseParser(BaseMusicParser):
    """网易云音乐解析器。

    支持单曲、歌单、专辑解析，以及标准/高品质/无损三档音质直链获取。

    高音质需要登录 Cookie（包含 ``MUSIC_U`` 字段）::

        credential = {"cookie": "MUSIC_U=xxx; ..."}
    """

    supported_domains = ["music.163.com", "163.com"]
    source_name = "netease"
    status = "stable"
    experimental = False

    def __init__(self, credential: dict[str, Any] | None = None) -> None:
        super().__init__(credential)
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": DEFAULT_USER_AGENT,
                "Referer": "https://music.163.com/",
                "Content-Type": "application/x-www-form-urlencoded",
            }
        )
        self._cookie: str = (credential or {}).get("cookie", "")
        if self._cookie:
            self._session.headers["Cookie"] = self._cookie

    # ---------- 公共接口 ----------

    def parse_song_url(self, url: str) -> SongInfo:
        """解析网易云单曲链接。

        Args:
            url: 单曲链接（``https://music.163.com/#/song?id=xxx`` 或
                ``https://music.163.com/song?id=xxx``）。

        Returns:
            :class:`SongInfo`，包含歌曲信息和可用音质列表。

        Raises:
            ParserError: 解析失败。
        """
        song_id = self._extract_song_id(url)
        return self._parse_song_by_id(song_id)

    def parse_playlist_url(self, url: str) -> PlaylistInfo:
        """解析网易云歌单或专辑链接。

        Args:
            url: 歌单链接（``/playlist?id=xxx``）或专辑链接（``/album?id=xxx``）。

        Returns:
            :class:`PlaylistInfo`，包含歌单元数据和歌曲列表。

        Raises:
            ParserError: 解析失败。
        """
        # 判断是歌单还是专辑
        if re.search(r"/album[?/]id=|/album/", url, re.IGNORECASE):
            album_id = self._extract_album_id(url)
            return self._parse_album_by_id(album_id)
        else:
            playlist_id = self._extract_playlist_id(url)
            return self._parse_playlist_by_id(playlist_id)

    def get_download_url(self, song_info: SongInfo, quality: str) -> str:
        """获取网易云歌曲指定音质的下载直链。

        Args:
            song_info: 已解析的歌曲信息。
            quality: 音质标识（``standard`` / ``higher`` / ``lossless``）。

        Returns:
            下载直链 URL。

        Raises:
            ParserError: 版权受限或音质不可用。
        """
        if song_info.copyright_restricted:
            raise ParserError("该歌曲因版权限制无法下载")

        quality_info = song_info.get_quality(quality)
        if quality_info is None:
            # 尝试降级到最高可用音质
            best = song_info.best_available_quality()
            if best is None:
                raise ParserError(f"歌曲 {song_info.title} 无可用音质")
            quality = best.quality

        level = _QUALITY_LEVEL_MAP.get(quality, "standard")
        song_id = song_info.song_id

        data = self._weapi_request(
            "/song/enhance/player/url/v1",
            {"ids": f"[{song_id}]", "level": level, "encodeType": "aac"},
        )

        data_list = data.get("data", [])
        if not data_list:
            raise ParserError("未获取到下载地址")

        song_data = data_list[0]
        url = song_data.get("url", "")

        if not url:
            # 检查是否为版权受限
            if song_data.get("code") == -110 or "版权" in str(song_data):
                raise ParserError("该歌曲因版权限制无法下载")
            raise ParserError(f"未获取到 {quality} 音质下载地址")

        return url

    # ---------- 内部解析逻辑 ----------

    def _parse_song_by_id(self, song_id: str) -> SongInfo:
        """根据歌曲 ID 解析歌曲详情。"""
        data = self._weapi_request(
            "/v3/song/detail",
            {"c": json.dumps([{"id": song_id}]), "ids": f"[{song_id}]"},
        )

        songs = data.get("songs", [])
        if not songs:
            raise ParserError(f"未找到歌曲 ID: {song_id}")

        song = songs[0]
        return self._build_song_info(song)

    def _parse_playlist_by_id(self, playlist_id: str) -> PlaylistInfo:
        """根据歌单 ID 解析歌单详情。"""
        data = self._weapi_request(
            "/v3/playlist/detail",
            {"id": playlist_id, "n": 1000, "s": 8},
        )

        playlist = data.get("playlist", {})
        if not playlist:
            raise ParserError(f"未找到歌单 ID: {playlist_id}")

        track_ids = playlist.get("trackIds", [])
        tracks = playlist.get("tracks", [])

        # 歌单可能只返回部分 tracks，需要用 trackIds 补全
        songs: list[SongInfo] = []
        if tracks:
            for track in tracks:
                songs.append(self._build_song_info(track))
        elif track_ids:
            # 批量获取歌曲详情（每次最多 1000 首）
            ids = [str(t["id"]) for t in track_ids[:1000]]
            if ids:
                detail_data = self._weapi_request(
                    "/v3/song/detail",
                    {
                        "c": json.dumps([{"id": i} for i in ids]),
                        "ids": f"[{','.join(ids)}]",
                    },
                )
                for track in detail_data.get("songs", []):
                    songs.append(self._build_song_info(track))

        creator_name = ""
        creator = playlist.get("creator", {})
        if creator:
            creator_name = creator.get("nickname", "")

        return PlaylistInfo(
            playlist_id=playlist_id,
            title=playlist.get("name", ""),
            creator=creator_name,
            cover=playlist.get("coverImgUrl", ""),
            description=playlist.get("description", ""),
            song_count=playlist.get("trackCount", len(songs)),
            songs=songs,
            source=self.source_name,
            playlist_type="playlist",
            raw_response={"playlist": playlist},
        )

    def _parse_album_by_id(self, album_id: str) -> PlaylistInfo:
        """根据专辑 ID 解析专辑详情。"""
        data = self._weapi_request(f"/v1/album/{album_id}", {})

        album = data.get("album", {})
        songs_data = data.get("songs", [])

        if not album:
            raise ParserError(f"未找到专辑 ID: {album_id}")

        songs = [self._build_song_info(s) for s in songs_data]

        artist_name = ""
        artists = album.get("artists", [])
        if artists:
            artist_name = "/".join(a.get("name", "") for a in artists)

        return PlaylistInfo(
            playlist_id=album_id,
            title=album.get("name", ""),
            creator=artist_name,
            cover=album.get("picUrl", ""),
            description=album.get("description", ""),
            song_count=len(songs),
            songs=songs,
            source=self.source_name,
            playlist_type="album",
            raw_response={"album": album},
        )

    def _build_song_info(self, song: dict[str, Any]) -> SongInfo:
        """从 API 响应构建 SongInfo。"""
        song_id = str(song.get("id", ""))
        title = song.get("name", "")

        # 歌手
        artists = song.get("ar", []) or song.get("artists", [])
        artist = "/".join(a.get("name", "") for a in artists)

        # 专辑
        album_data = song.get("al", {}) or song.get("album", {})
        album = album_data.get("name", "")
        cover = album_data.get("picUrl", "") or album_data.get("pic_str", "")

        # 时长
        duration = int(song.get("dt", 0) or song.get("duration", 0))
        if duration > 1000:
            duration = duration // 1000  # 毫秒转秒

        # 版权受限检测
        copyright_restricted = False
        fee = song.get("fee", 0)
        # fee=1 为 VIP 专享（仍可试听），fee=4 为购买专辑
        # noCopyrightRcmd 存在表示无版权
        if song.get("noCopyrightRcmd") is not None:
            copyright_restricted = True

        # 构建音质列表
        quality_list = self._build_quality_list(song, copyright_restricted)

        return SongInfo(
            song_id=song_id,
            title=title,
            artist=artist,
            album=album,
            cover=cover,
            duration=duration,
            quality_list=quality_list,
            source=self.source_name,
            raw_response={"song": song},
            copyright_restricted=copyright_restricted,
        )

    def _build_quality_list(
        self, song: dict[str, Any], copyright_restricted: bool
    ) -> list[QualityInfo]:
        """根据歌曲信息构建可用音质列表。"""
        quality_list: list[QualityInfo] = []

        # 各音质对应的字段
        # h: 高品质(320k), m: 标准(128k), l: 低品质(96k)
        # 网易云新接口用 h/m/l 标记各音质是否可用
        h_info = song.get("h")
        m_info = song.get("m")
        l_info = song.get("l")
        # sq: 无损
        sq_info = song.get("sq")

        def _make_quality(
            quality: str, info: dict[str, Any] | None, available: bool
        ) -> QualityInfo:
            bitrate = None
            size = None
            if info:
                bitrate = info.get("br")
                size = info.get("size")
            if bitrate is None:
                bitrate = _QUALITY_BITRATE_MAP.get(quality)
            return QualityInfo(
                quality=quality,
                bitrate=bitrate,
                extension=QUALITY_EXTENSIONS.get(quality, "mp3"),
                size=size,
                available=available and not copyright_restricted,
            )

        # 标准音质（m 或 l 可用即认为标准可用）
        standard_avail = (m_info is not None) or (l_info is not None)
        quality_list.append(_make_quality(QUALITY_STANDARD, m_info or l_info, standard_avail))

        # 高品质（h 可用）
        higher_avail = h_info is not None
        quality_list.append(_make_quality(QUALITY_HIGHER, h_info, higher_avail))

        # 无损（sq 可用，需要登录）
        lossless_avail = sq_info is not None
        quality_list.append(_make_quality(QUALITY_LOSSLESS, sq_info, lossless_avail))

        return quality_list

    # ---------- ID 提取 ----------

    def _extract_song_id(self, url: str) -> str:
        """从 URL 提取歌曲 ID。"""
        # 处理 hash 路由（#/song?id=xxx）
        normalized = self._normalize_url(url)
        return self._extract_id_from_url(normalized, _SONG_ID_RE.pattern)

    def _extract_playlist_id(self, url: str) -> str:
        """从 URL 提取歌单 ID。"""
        normalized = self._normalize_url(url)
        return self._extract_id_from_url(normalized, _PLAYLIST_ID_RE.pattern)

    def _extract_album_id(self, url: str) -> str:
        """从 URL 提取专辑 ID。"""
        normalized = self._normalize_url(url)
        return self._extract_id_from_url(normalized, _ALBUM_ID_RE.pattern)

    @staticmethod
    def _normalize_url(url: str) -> str:
        """将 hash 路由 URL 转换为普通路径 URL。

        网易云 SPA 使用 ``#/song?id=xxx`` 形式，需要将 fragment 转为路径。
        """
        if "#/" in url:
            base, fragment = url.split("#/", 1)
            # fragment 可能是 song?id=xxx 或 /song?id=xxx
            if not fragment.startswith("/"):
                fragment = "/" + fragment
            return base.rstrip("/") + fragment
        return url

    # ---------- HTTP 请求 ----------

    def _weapi_request(
        self, path: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """发送 weapi 请求并解析响应。

        Args:
            path: API 路径（如 ``/v3/song/detail``）。
            params: 原始参数。

        Returns:
            响应 JSON 字典。

        Raises:
            NetworkError: 网络请求失败。
            ParserError: 响应解析失败或 API 返回错误。
        """
        encrypted = weapi_encrypt(params)
        url = f"{WEAPI_BASE}{path}"

        try:
            resp = self._session.post(url, data=encrypted, timeout=30)
        except requests.RequestException as exc:
            raise NetworkError(f"网易云 API 请求失败: {exc}") from exc

        try:
            result = resp.json()
        except ValueError as exc:
            raise ParserError(f"网易云响应解析失败: {exc}") from exc

        code = result.get("code", -1)
        if code != 200:
            message = result.get("message", "") or result.get("msg", "")
            if code == -462:
                raise ParserError("网易云接口调用过于频繁，请稍后重试")
            if code == 301:
                raise ParserError("需要登录才能访问该资源")
            raise ParserError(f"网易云 API 错误 (code={code}): {message}")

        return result
