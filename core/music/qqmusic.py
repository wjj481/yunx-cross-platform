"""
QQ音乐解析器。

完整支持单曲/歌单/专辑解析与多音质直链获取。

认证机制：
- **guid**：随机数字标识，每次会话生成
- **vkey**：通过 ``fcg_music_express_mobile3.fcg`` 接口获取的临时签名
- 下载直链格式：``http://dl.stream.qqmusic.qq.com/{filename}?vkey={vkey}&guid={guid}``

音质与文件名前缀映射：
- ``standard`` — ``M500{songmid}.mp3``（128kbps）
- ``higher``   — ``M800{songmid}.mp3``（320kbps）
- ``lossless`` — ``F000{songmid}.flac``（无损 FLAC）

高音质需要登录 Cookie（包含 ``uin`` / ``qqmusic_key`` 等字段）。
"""

from __future__ import annotations

import json
import random
import re
import time
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

API_BASE = "https://c.y.qq.com"
UAPI_BASE = "https://u.y.qq.com"
MUSICU_URL = f"{UAPI_BASE}/cgi-bin/musicu.fcg"
VKEY_URL = f"{API_BASE}/base/fcgi-bin/fcg_music_express_mobile3.fcg"
DOWNLOAD_BASE = "http://dl.stream.qqmusic.qq.com"

# 固定 cid（客户端标识）
DEFAULT_CID = "205361747"
DEFAULT_UIN = "0"

# 音质 -> 文件名前缀映射
_QUALITY_PREFIX_MAP = {
    QUALITY_STANDARD: "M500",
    QUALITY_HIGHER: "M800",
    QUALITY_LOSSLESS: "F000",
}

# 音质 -> 比特率映射
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
_SONG_MID_RE = re.compile(
    r"(?:songDetail/|/song/|songmid=)([A-Za-z0-9]+)", re.IGNORECASE
)
_PLAYLIST_ID_RE = re.compile(
    r"(?:playlist/|playsquare/|playlistid=|id=)(\d+)", re.IGNORECASE
)
_ALBUM_MID_RE = re.compile(
    r"(?:albumDetail/|/album/|albummid=)([A-Za-z0-9]+)", re.IGNORECASE
)


def _generate_guid() -> str:
    """生成 QQ 音乐 guid（随机数字字符串）。

    Returns:
        10 位随机数字字符串。
    """
    return str(random.randint(1000000000, 9999999999))


class QQMusicParser(BaseMusicParser):
    """QQ音乐解析器。

    支持单曲、歌单、专辑解析，以及标准/高品质/无损三档音质直链获取。

    高音质需要登录 Cookie::

        credential = {"cookie": "uin=xxx; qqmusic_key=xxx; ...", "uin": "xxx"}
    """

    supported_domains = ["y.qq.com", "qq.com", "music.qq.com"]
    source_name = "qqmusic"
    status = "stable"
    experimental = False

    def __init__(self, credential: dict[str, Any] | None = None) -> None:
        super().__init__(credential)
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": DEFAULT_USER_AGENT,
                "Referer": "https://y.qq.com/",
            }
        )
        self._cookie: str = (credential or {}).get("cookie", "")
        self._uin: str = str((credential or {}).get("uin", DEFAULT_UIN))
        if self._cookie:
            self._session.headers["Cookie"] = self._cookie
        self._guid = _generate_guid()
        # vkey 缓存：{filename: (vkey, expire_time)}
        self._vkey_cache: dict[str, tuple[str, float]] = {}

    # ---------- 公共接口 ----------

    def parse_song_url(self, url: str) -> SongInfo:
        """解析 QQ 音乐单曲链接。

        Args:
            url: 单曲链接（``https://y.qq.com/n/ryqq/songDetail/{songmid}`` 等）。

        Returns:
            :class:`SongInfo`，包含歌曲信息和可用音质列表。

        Raises:
            ParserError: 解析失败。
        """
        songmid = self._extract_songmid(url)
        return self._parse_song_by_mid(songmid)

    def parse_playlist_url(self, url: str) -> PlaylistInfo:
        """解析 QQ 音乐歌单或专辑链接。

        Args:
            url: 歌单链接（``/playlist/{id}``）或专辑链接（``/albumDetail/{albummid}``）。

        Returns:
            :class:`PlaylistInfo`，包含歌单元数据和歌曲列表。

        Raises:
            ParserError: 解析失败。
        """
        if re.search(r"albumDetail/|/album/|albummid=", url, re.IGNORECASE):
            albummid = self._extract_albummid(url)
            return self._parse_album_by_mid(albummid)
        else:
            playlist_id = self._extract_playlist_id(url)
            return self._parse_playlist_by_id(playlist_id)

    def get_download_url(self, song_info: SongInfo, quality: str) -> str:
        """获取 QQ 音乐歌曲指定音质的下载直链。

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
            best = song_info.best_available_quality()
            if best is None:
                raise ParserError(f"歌曲 {song_info.title} 无可用音质")
            quality = best.quality

        songmid = song_info.song_id
        prefix = _QUALITY_PREFIX_MAP.get(quality, "M500")
        ext = QUALITY_EXTENSIONS.get(quality, "mp3")
        filename = f"{prefix}{songmid}.{ext}"

        vkey = self._get_vkey(songmid, filename)
        if not vkey:
            raise ParserError(f"获取 {quality} 音质 vkey 失败")

        url = (
            f"{DOWNLOAD_BASE}/{filename}"
            f"?vkey={vkey}&guid={self._guid}&uin={self._uin}&fromtag=66"
        )
        return url

    # ---------- 内部解析逻辑 ----------

    def _parse_song_by_mid(self, songmid: str) -> SongInfo:
        """根据 songmid 解析歌曲详情。"""
        # 使用 musicu.fcg 统一接口
        payload = {
            "comm": {
                "cv": 4747474,
                "ct": 24,
                "format": "json",
                "inCharset": "utf-8",
                "outCharset": "utf-8",
                "notice": 0,
                "platform": "yqq.json",
                "needNewCode": 1,
                "uin": self._uin,
                "guid": self._guid,
            },
            "req_1": {
                "module": "music.pf_song_detail_svr",
                "method": "get_song_detail",
                "param": {"song_mid": songmid},
            },
        }

        data = self._musicu_request(payload)
        req_1 = data.get("req_1", {})
        if req_1.get("code") != 0:
            raise ParserError(f"获取歌曲详情失败: {req_1.get('message', '')}")

        song_data = req_1.get("data", {})
        track_info = song_data.get("track_info", {})
        if not track_info:
            raise ParserError(f"未找到歌曲: {songmid}")

        return self._build_song_info(track_info)

    def _parse_playlist_by_id(self, playlist_id: str) -> PlaylistInfo:
        """根据歌单 ID 解析歌单详情。"""
        payload = {
            "comm": {
                "cv": 4747474,
                "ct": 24,
                "format": "json",
                "inCharset": "utf-8",
                "outCharset": "utf-8",
                "notice": 0,
                "platform": "yqq.json",
                "needNewCode": 1,
                "uin": self._uin,
                "guid": self._guid,
            },
            "req_1": {
                "module": "music.srfDissInfo.aiDissInfo",
                "method": "uniform_get_Dissinfo",
                "param": {
                    "disstid": int(playlist_id),
                    "tag_user": 0,
                    "song_begin": 0,
                    "song_num": 1000,
                },
            },
        }

        data = self._musicu_request(payload)
        req_1 = data.get("req_1", {})
        if req_1.get("code") != 0:
            raise ParserError(f"获取歌单详情失败: {req_1.get('message', '')}")

        playlist_data = req_1.get("data", {})
        songs_data = playlist_data.get("songlist", [])
        songs = [self._build_song_info(s) for s in songs_data]

        creator_name = ""
        creator = playlist_data.get("creator", {})
        if creator:
            creator_name = creator.get("name", "") or creator.get("nick", "")

        return PlaylistInfo(
            playlist_id=playlist_id,
            title=playlist_data.get("dissname", "") or playlist_data.get("title", ""),
            creator=creator_name,
            cover=playlist_data.get("imgurl", "") or playlist_data.get("logo", ""),
            description=playlist_data.get("introduction", "") or playlist_data.get("desc", ""),
            song_count=playlist_data.get("song_count", len(songs)),
            songs=songs,
            source=self.source_name,
            playlist_type="playlist",
            raw_response={"playlist": playlist_data},
        )

    def _parse_album_by_mid(self, albummid: str) -> PlaylistInfo:
        """根据 albummid 解析专辑详情。"""
        payload = {
            "comm": {
                "cv": 4747474,
                "ct": 24,
                "format": "json",
                "inCharset": "utf-8",
                "outCharset": "utf-8",
                "notice": 0,
                "platform": "yqq.json",
                "needNewCode": 1,
                "uin": self._uin,
                "guid": self._guid,
            },
            "req_1": {
                "module": "music.musichallAlbum.AlbumInfoServer",
                "method": "GetAlbumDetail",
                "param": {"albumMid": albummid},
            },
        }

        data = self._musicu_request(payload)
        req_1 = data.get("req_1", {})
        if req_1.get("code") != 0:
            raise ParserError(f"获取专辑详情失败: {req_1.get('message', '')}")

        album_data = req_1.get("data", {})
        album_info = album_data.get("albumInfo", {})
        songs_data = album_data.get("list", [])
        songs = [self._build_song_info(s) for s in songs_data]

        artist_name = ""
        singers = album_info.get("singer", [])
        if singers:
            artist_name = "/".join(s.get("name", "") for s in singers)

        return PlaylistInfo(
            playlist_id=albummid,
            title=album_info.get("albumName", ""),
            creator=artist_name,
            cover=album_info.get("albumPic", ""),
            description=album_info.get("albumDesc", ""),
            song_count=len(songs),
            songs=songs,
            source=self.source_name,
            playlist_type="album",
            raw_response={"album": album_data},
        )

    def _build_song_info(self, track: dict[str, Any]) -> SongInfo:
        """从 API 响应构建 SongInfo。"""
        songmid = track.get("mid", "") or track.get("songmid", "") or str(track.get("id", ""))
        title = track.get("name", "") or track.get("songName", "") or track.get("title", "")

        # 歌手
        singers = track.get("singer", []) or track.get("artists", []) or []
        artist = "/".join(s.get("name", "") for s in singers)

        # 专辑
        album_data = track.get("album", {}) or {}
        album = album_data.get("name", "") or track.get("albumName", "") or track.get("albumname", "")
        cover = (
            album_data.get("pic", "")
            or track.get("albumPic", "")
            or track.get("albumpic", "")
            or ""
        )

        # 时长
        duration = int(track.get("interval", 0) or track.get("duration", 0) or 0)

        # 版权受限检测
        copyright_restricted = False
        # QQ 音乐用 status 字段标记：0=正常，1=无版权，2=VIP
        status = track.get("status", 0)
        if status == 1:
            copyright_restricted = True
        # action 字段中的 alert 标记也可能表示无版权
        action = track.get("action", {})
        if action.get("alert") == 1:
            copyright_restricted = True

        # 构建音质列表
        quality_list = self._build_quality_list(track, copyright_restricted)

        return SongInfo(
            song_id=songmid,
            title=title,
            artist=artist,
            album=album,
            cover=cover,
            duration=duration,
            quality_list=quality_list,
            source=self.source_name,
            raw_response={"track": track},
            copyright_restricted=copyright_restricted,
        )

    def _build_quality_list(
        self, track: dict[str, Any], copyright_restricted: bool
    ) -> list[QualityInfo]:
        """根据歌曲信息构建可用音质列表。"""
        quality_list: list[QualityInfo] = []

        # QQ 音乐用 file 字段标记各音质文件信息
        file_info = track.get("file", {})

        def _make_quality(quality: str, available: bool) -> QualityInfo:
            size = None
            if file_info:
                size_key = {
                    QUALITY_STANDARD: "size_128mp3",
                    QUALITY_HIGHER: "size_320mp3",
                    QUALITY_LOSSLESS: "size_flac",
                }.get(quality)
                if size_key and size_key in file_info:
                    size = file_info[size_key]
            return QualityInfo(
                quality=quality,
                bitrate=_QUALITY_BITRATE_MAP.get(quality),
                extension=QUALITY_EXTENSIONS.get(quality, "mp3"),
                size=size,
                available=available and not copyright_restricted,
            )

        # 标准音质
        standard_avail = True
        if file_info:
            standard_avail = bool(file_info.get("128mp3", True))
        quality_list.append(_make_quality(QUALITY_STANDARD, standard_avail))

        # 高品质
        higher_avail = True
        if file_info:
            higher_avail = bool(file_info.get("320mp3", False))
        quality_list.append(_make_quality(QUALITY_HIGHER, higher_avail))

        # 无损
        lossless_avail = False
        if file_info:
            lossless_avail = bool(file_info.get("flac", False))
        quality_list.append(_make_quality(QUALITY_LOSSLESS, lossless_avail))

        return quality_list

    # ---------- vkey 获取 ----------

    def _get_vkey(self, songmid: str, filename: str) -> str:
        """获取下载 vkey（带缓存）。

        Args:
            songmid: 歌曲 mid。
            filename: 文件名（含前缀和扩展名）。

        Returns:
            vkey 字符串；失败时返回空字符串。
        """
        # 检查缓存
        now = time.time()
        if filename in self._vkey_cache:
            vkey, expire = self._vkey_cache[filename]
            if now < expire:
                return vkey

        params = {
            "format": "json",
            "cid": DEFAULT_CID,
            "uin": self._uin,
            "songmid": songmid,
            "filename": filename,
            "guid": self._guid,
        }

        try:
            resp = self._session.get(VKEY_URL, params=params, timeout=30)
            result = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise NetworkError(f"获取 vkey 失败: {exc}") from exc

        data = result.get("data", {})
        vkey = data.get("vkey", "")

        if vkey:
            # 缓存 vkey，有效期约 1 小时（保守设为 50 分钟）
            self._vkey_cache[filename] = (vkey, now + 3000)

        return vkey

    # ---------- ID 提取 ----------

    def _extract_songmid(self, url: str) -> str:
        """从 URL 提取 songmid。"""
        return self._extract_id_from_url(url, _SONG_MID_RE.pattern)

    def _extract_playlist_id(self, url: str) -> str:
        """从 URL 提取歌单 ID。"""
        return self._extract_id_from_url(url, _PLAYLIST_ID_RE.pattern)

    def _extract_albummid(self, url: str) -> str:
        """从 URL 提取 albummid。"""
        return self._extract_id_from_url(url, _ALBUM_MID_RE.pattern)

    # ---------- HTTP 请求 ----------

    def _musicu_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """发送 musicu.fcg 统一接口请求。

        Args:
            payload: 请求 payload（包含 comm 和各模块请求）。

        Returns:
            响应 JSON 字典。

        Raises:
            NetworkError: 网络请求失败。
            ParserError: 响应解析失败。
        """
        try:
            resp = self._session.post(
                MUSICU_URL,
                data=json.dumps(payload, ensure_ascii=False),
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            result = resp.json()
        except requests.RequestException as exc:
            raise NetworkError(f"QQ音乐 API 请求失败: {exc}") from exc
        except ValueError as exc:
            raise ParserError(f"QQ音乐响应解析失败: {exc}") from exc

        # 检查全局 code
        code = result.get("code", -1)
        if code not in (0, 200):
            raise ParserError(f"QQ音乐 API 错误 (code={code})")

        return result
