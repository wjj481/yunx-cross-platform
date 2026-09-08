"""
音乐解析下载模块单元测试。

覆盖：工厂函数 URL 匹配、数据类、各平台 ID 提取、音质列表、
下载 URL 获取（mock）、ID3 标签嵌入、实验性平台标记、错误处理。
"""

from __future__ import annotations

import os
import struct
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.exceptions import ParserError
from core.music import (
    BaseMusicParser,
    MusicDownloader,
    PlaylistInfo,
    QUALITY_HIGHER,
    QUALITY_LOSSLESS,
    QUALITY_STANDARD,
    QualityInfo,
    SongInfo,
    embed_id3_tags,
    get_music_parser,
    is_mutagen_available,
    list_supported_music_sources,
)
from core.music.netease import NetEaseParser, eapi_encrypt, weapi_encrypt
from core.music.qqmusic import QQMusicParser
from core.music.kugou import KuGouParser
from core.music.kuwo import KuWoParser
from core.music.id3tagger import (
    _build_id3v23_tag,
    _int_to_synchsafe,
    _strip_id3v2,
    _synchsafe_to_int,
)


# ========== 工厂函数 URL 匹配测试 ==========


class TestMusicParserFactory:
    """音乐解析器工厂匹配测试。"""

    def test_netease_url_matches(self):
        """网易云链接应匹配 NetEaseParser。"""
        parser = get_music_parser("https://music.163.com/#/song?id=123456")
        assert isinstance(parser, NetEaseParser)

    def test_netease_song_path_matches(self):
        """网易云 /song?id= 格式应匹配。"""
        parser = get_music_parser("https://music.163.com/song?id=123456")
        assert isinstance(parser, NetEaseParser)

    def test_qqmusic_url_matches(self):
        """QQ音乐链接应匹配 QQMusicParser。"""
        parser = get_music_parser("https://y.qq.com/n/ryqq/songDetail/003aAYrm3GE0Ac")
        assert isinstance(parser, QQMusicParser)

    def test_kugou_url_matches(self):
        """酷狗链接应匹配 KuGouParser。"""
        parser = get_music_parser("https://www.kugou.com/song/#hash=abc123")
        assert isinstance(parser, KuGouParser)

    def test_kuwo_url_matches(self):
        """酷我链接应匹配 KuWoParser。"""
        parser = get_music_parser("http://www.kuwo.cn/play_detail/123456")
        assert isinstance(parser, KuWoParser)

    def test_unknown_url_raises(self):
        """未知域名应抛出 ParserError。"""
        with pytest.raises(ParserError, match="无法识别的音乐平台链接"):
            get_music_parser("https://example.com/song/123")

    def test_factory_passes_credential(self):
        """工厂应正确传递 credential。"""
        cred = {"cookie": "MUSIC_U=test123"}
        parser = get_music_parser("https://music.163.com/song?id=1", credential=cred)
        assert parser.credential == cred

    def test_list_supported_sources(self):
        """list_supported_music_sources 应返回所有平台。"""
        sources = list_supported_music_sources()
        source_names = [s["source"] for s in sources]
        assert "netease" in source_names
        assert "qqmusic" in source_names
        assert "kugou" in source_names
        assert "kuwo" in source_names


# ========== 数据类测试 ==========


class TestDataClasses:
    """SongInfo / PlaylistInfo / QualityInfo 数据类测试。"""

    def test_song_info_creation(self):
        """SongInfo 应正确创建并存储字段。"""
        song = SongInfo(
            song_id="123",
            title="晴天",
            artist="周杰伦",
            album="叶惠美",
            duration=269,
        )
        assert song.song_id == "123"
        assert song.title == "晴天"
        assert song.artist == "周杰伦"
        assert song.album == "叶惠美"
        assert song.duration == 269
        assert song.quality_list == []
        assert song.copyright_restricted is False

    def test_song_info_get_quality(self):
        """SongInfo.get_quality 应返回对应音质。"""
        song = SongInfo(
            song_id="1",
            title="test",
            quality_list=[
                QualityInfo(quality=QUALITY_STANDARD, available=True),
                QualityInfo(quality=QUALITY_HIGHER, available=True),
                QualityInfo(quality=QUALITY_LOSSLESS, available=False),
            ],
        )
        assert song.get_quality(QUALITY_STANDARD) is not None
        assert song.get_quality(QUALITY_HIGHER) is not None
        assert song.get_quality(QUALITY_LOSSLESS) is None  # 不可用
        assert song.get_quality("nonexistent") is None

    def test_song_info_best_available_quality(self):
        """best_available_quality 应返回最高可用音质。"""
        song = SongInfo(
            song_id="1",
            title="test",
            quality_list=[
                QualityInfo(quality=QUALITY_STANDARD, available=True),
                QualityInfo(quality=QUALITY_HIGHER, available=True),
                QualityInfo(quality=QUALITY_LOSSLESS, available=False),
            ],
        )
        best = song.best_available_quality()
        assert best is not None
        assert best.quality == QUALITY_HIGHER

    def test_song_info_no_available_quality(self):
        """无可用音质时 best_available_quality 返回 None。"""
        song = SongInfo(
            song_id="1",
            title="test",
            quality_list=[QualityInfo(quality=QUALITY_STANDARD, available=False)],
        )
        assert song.best_available_quality() is None

    def test_playlist_info_creation(self):
        """PlaylistInfo 应正确创建。"""
        songs = [SongInfo(song_id=str(i), title=f"song{i}") for i in range(3)]
        playlist = PlaylistInfo(
            playlist_id="pl123",
            title="我的歌单",
            creator="testuser",
            song_count=3,
            songs=songs,
            playlist_type="playlist",
        )
        assert playlist.playlist_id == "pl123"
        assert len(playlist.songs) == 3
        assert playlist.songs[0].title == "song0"

    def test_quality_info_defaults(self):
        """QualityInfo 应自动填充 label 和 extension。"""
        q = QualityInfo(quality=QUALITY_HIGHER)
        assert q.label == "高品质 320kbps"
        assert q.extension == "mp3"
        assert q.available is True


# ========== 网易云 ID 提取测试 ==========


class TestNetEaseIdExtraction:
    """网易云歌曲/歌单 ID 提取测试。"""

    def setup_method(self):
        self.parser = NetEaseParser()

    def test_extract_song_id_from_hash_url(self):
        """应从 #/song?id= URL 提取歌曲 ID。"""
        song_id = self.parser._extract_song_id("https://music.163.com/#/song?id=123456")
        assert song_id == "123456"

    def test_extract_song_id_from_path_url(self):
        """应从 /song?id= URL 提取歌曲 ID。"""
        song_id = self.parser._extract_song_id("https://music.163.com/song?id=789")
        assert song_id == "789"

    def test_extract_playlist_id(self):
        """应从歌单 URL 提取歌单 ID。"""
        pid = self.parser._extract_playlist_id(
            "https://music.163.com/#/playlist?id=123456"
        )
        assert pid == "123456"

    def test_extract_album_id(self):
        """应从专辑 URL 提取专辑 ID。"""
        aid = self.parser._extract_album_id("https://music.163.com/#/album?id=999")
        assert aid == "999"

    def test_invalid_song_url_raises(self):
        """无效 URL 应抛出 ParserError。"""
        with pytest.raises(ParserError):
            self.parser._extract_song_id("https://music.163.com/#/artist?id=123")


# ========== QQ 音乐 songmid 提取测试 ==========


class TestQQMusicIdExtraction:
    """QQ音乐 songmid 提取测试。"""

    def setup_method(self):
        self.parser = QQMusicParser()

    def test_extract_songmid_from_song_detail(self):
        """应从 songDetail URL 提取 songmid。"""
        mid = self.parser._extract_songmid(
            "https://y.qq.com/n/ryqq/songDetail/003aAYrm3GE0Ac"
        )
        assert mid == "003aAYrm3GE0Ac"

    def test_extract_songmid_from_song_path(self):
        """应从 /song/ URL 提取 songmid。"""
        mid = self.parser._extract_songmid("https://y.qq.com/n/yqq/song/001abc.html")
        assert mid == "001abc"

    def test_extract_playlist_id(self):
        """应从歌单 URL 提取 ID。"""
        pid = self.parser._extract_playlist_id(
            "https://y.qq.com/n/ryqq/playlist/1234567"
        )
        assert pid == "1234567"

    def test_extract_albummid(self):
        """应从专辑 URL 提取 albummid。"""
        mid = self.parser._extract_albummid(
            "https://y.qq.com/n/ryqq/albumDetail/001abc"
        )
        assert mid == "001abc"


# ========== 音质列表解析测试 ==========


class TestQualityListParsing:
    """音质列表构建与解析测试。"""

    def test_netease_build_quality_list_all_available(self):
        """网易云全音质可用时应返回三档。"""
        parser = NetEaseParser()
        song_data = {
            "h": {"br": 320000, "size": 10000000},
            "m": {"br": 128000, "size": 4000000},
            "l": {"br": 96000, "size": 3000000},
            "sq": {"br": 999000, "size": 30000000},
        }
        qualities = parser._build_quality_list(song_data, False)
        assert len(qualities) == 3
        assert qualities[0].quality == QUALITY_STANDARD
        assert qualities[0].available is True
        assert qualities[1].quality == QUALITY_HIGHER
        assert qualities[1].bitrate == 320000
        assert qualities[2].quality == QUALITY_LOSSLESS
        assert qualities[2].available is True

    def test_netease_build_quality_list_copyright_restricted(self):
        """版权受限时所有音质应标记为不可用。"""
        parser = NetEaseParser()
        song_data = {"h": {"br": 320000}, "m": {"br": 128000}}
        qualities = parser._build_quality_list(song_data, True)
        assert all(q.available is False for q in qualities)

    def test_netease_build_quality_list_standard_only(self):
        """仅标准音质可用时应只有 standard 可用。"""
        parser = NetEaseParser()
        song_data = {"m": {"br": 128000}}
        qualities = parser._build_quality_list(song_data, False)
        assert qualities[0].available is True  # standard
        assert qualities[1].available is False  # higher
        assert qualities[2].available is False  # lossless

    def test_qqmusic_build_quality_list(self):
        """QQ音乐音质列表应正确构建。"""
        parser = QQMusicParser()
        track = {
            "file": {
                "128mp3": True,
                "320mp3": True,
                "flac": False,
                "size_128mp3": 4000000,
                "size_320mp3": 10000000,
            }
        }
        qualities = parser._build_quality_list(track, False)
        assert qualities[0].available is True
        assert qualities[1].available is True
        assert qualities[2].available is False
        assert qualities[0].size == 4000000


# ========== 下载 URL 获取测试（mock） ==========


class TestDownloadUrl:
    """下载直链获取测试（使用 mock 避免真实网络请求）。"""

    def test_netease_get_download_url_mock(self):
        """网易云 get_download_url 应返回直链。"""
        parser = NetEaseParser()
        song = SongInfo(
            song_id="123",
            title="test",
            quality_list=[QualityInfo(quality=QUALITY_STANDARD, available=True)],
        )
        mock_response = {
            "code": 200,
            "data": [{"url": "https://example.com/song.mp3", "br": 128000}],
        }
        with patch.object(parser, "_weapi_request", return_value=mock_response):
            url = parser.get_download_url(song, QUALITY_STANDARD)
            assert url == "https://example.com/song.mp3"

    def test_netease_copyright_restricted_raises(self):
        """版权受限歌曲应抛出 ParserError。"""
        parser = NetEaseParser()
        song = SongInfo(
            song_id="123",
            title="test",
            copyright_restricted=True,
            quality_list=[QualityInfo(quality=QUALITY_STANDARD, available=True)],
        )
        with pytest.raises(ParserError, match="版权限制"):
            parser.get_download_url(song, QUALITY_STANDARD)

    def test_netease_quality_fallback(self):
        """请求音质不可用时应自动降级。"""
        parser = NetEaseParser()
        song = SongInfo(
            song_id="123",
            title="test",
            quality_list=[
                QualityInfo(quality=QUALITY_STANDARD, available=True),
                QualityInfo(quality=QUALITY_HIGHER, available=False),
            ],
        )
        mock_response = {
            "code": 200,
            "data": [{"url": "https://example.com/standard.mp3"}],
        }
        with patch.object(parser, "_weapi_request", return_value=mock_response):
            url = parser.get_download_url(song, QUALITY_HIGHER)
            assert url == "https://example.com/standard.mp3"

    def test_qqmusic_get_download_url_mock(self):
        """QQ音乐 get_download_url 应返回带 vkey 的直链。"""
        parser = QQMusicParser()
        song = SongInfo(
            song_id="001abc",
            title="test",
            quality_list=[QualityInfo(quality=QUALITY_STANDARD, available=True)],
        )
        with patch.object(parser, "_get_vkey", return_value="testvkey123"):
            url = parser.get_download_url(song, QUALITY_STANDARD)
            assert "vkey=testvkey123" in url
            assert "M500001abc.mp3" in url
            assert "guid=" in url


# ========== weapi/eapi 加密测试 ==========


class TestNetEaseEncryption:
    """网易云 weapi/eapi 加密测试。"""

    def test_weapi_encrypt_returns_params_and_encseckey(self):
        """weapi_encrypt 应返回 params 和 encSecKey。"""
        result = weapi_encrypt({"ids": "[123]", "level": "standard"})
        assert "params" in result
        assert "encSecKey" in result
        assert len(result["encSecKey"]) == 256  # 256 hex chars = 128 bytes

    def test_weapi_encrypt_deterministic_params_structure(self):
        """weapi_encrypt 每次加密 params 长度应一致（base64 输出）。"""
        r1 = weapi_encrypt({"test": "value"})
        r2 = weapi_encrypt({"test": "value"})
        # 因为随机密钥不同，params 不同，但长度应相同
        assert len(r1["params"]) == len(r2["params"])

    def test_eapi_encrypt_returns_params(self):
        """eapi_encrypt 应返回 params。"""
        result = eapi_encrypt("/api/song/detail", {"id": "123"})
        assert "params" in result
        # eapi 输出为十六进制，应为偶数长度
        assert len(result["params"]) % 2 == 0


# ========== ID3 标签嵌入测试 ==========


class TestID3TagEmbedding:
    """ID3 标签嵌入测试。"""

    @staticmethod
    def _create_minimal_mp3(path: Path) -> None:
        """创建一个最小的有效 MP3 文件（含 MPEG 帧头）。"""
        # MPEG1 Layer3 帧头：FF FB 90 00
        # FF FB = sync + MPEG1 + Layer3 + no CRC
        # 90 = bitrate 128kbps + sample rate 44100
        # 00 = no padding + private + channel mode stereo
        frame_header = bytes([0xFF, 0xFB, 0x90, 0x00])
        # 填充一帧数据（128kbps @ 44100Hz = 417 字节/帧，含头）
        frame_data = frame_header + b"\x00" * 413
        path.write_bytes(frame_data * 10)  # 10 帧

    @staticmethod
    def _create_minimal_jpeg() -> bytes:
        """创建最小的有效 JPEG 图片。"""
        # 最小 JPEG：SOI + APP0(JFIF) + SOF0 + DQT + DHT + SOS + EOI
        return bytes(
            [
                0xFF, 0xD8,  # SOI
                0xFF, 0xE0,  # APP0
                0x00, 0x10,  # length
                0x4A, 0x46, 0x49, 0x46, 0x00,  # JFIF\0
                0x01, 0x01,  # version
                0x00,  # units
                0x00, 0x01, 0x00, 0x01,  # density
                0x00, 0x00,  # thumbnail
                0xFF, 0xD9,  # EOI
            ]
        )

    def test_embed_id3_tags_mp3_with_mutagen(self):
        """MP3 文件应成功嵌入 ID3 标签（mutagen 路径）。"""
        if not is_mutagen_available():
            pytest.skip("mutagen not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            mp3_path = Path(tmpdir) / "test.mp3"
            self._create_minimal_mp3(mp3_path)

            song = SongInfo(
                song_id="123",
                title="测试歌曲",
                artist="测试歌手",
                album="测试专辑",
            )
            cover = self._create_minimal_jpeg()

            result = embed_id3_tags(mp3_path, song, cover)
            assert result is True

            # 验证标签可读回
            from mutagen.id3 import ID3

            tags = ID3(mp3_path)
            assert str(tags["TIT2"]) == "测试歌曲"
            assert str(tags["TPE1"]) == "测试歌手"
            assert str(tags["TALB"]) == "测试专辑"
            # mutagen 中 APIC 帧 key 带描述后缀（如 APIC:Cover）
            apic_frames = tags.getall("APIC")
            assert len(apic_frames) > 0
            assert apic_frames[0].mime == "image/jpeg"

    def test_embed_id3_tags_mp3_pure_python(self):
        """MP3 文件应成功嵌入 ID3 标签（纯 Python 降级路径）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mp3_path = Path(tmpdir) / "test_pure.mp3"
            self._create_minimal_mp3(mp3_path)

            song = SongInfo(
                song_id="123",
                title="PurePython Song",
                artist="Test Artist",
                album="Test Album",
            )
            cover = self._create_minimal_jpeg()

            # 直接调用纯 Python 实现
            from core.music.id3tagger import _embed_pure_python

            result = _embed_pure_python(mp3_path, "mp3", song, cover)
            assert result is True

            # 验证文件以 ID3 头开头
            data = mp3_path.read_bytes()
            assert data[:3] == b"ID3"
            assert data[3] == 0x03  # v2.3
            assert data[4] == 0x00

            # 验证包含 TIT2 帧
            assert b"TIT2" in data
            assert b"TPE1" in data
            assert b"TALB" in data
            assert b"APIC" in data

    def test_embed_id3_nonexistent_file(self):
        """不存在的文件应返回 False。"""
        song = SongInfo(song_id="1", title="test")
        result = embed_id3_tags("/nonexistent/path.mp3", song)
        assert result is False

    def test_synchsafe_conversion(self):
        """synchsafe 整数转换应正确。"""
        # 测试值
        test_cases = [
            (0, bytes([0, 0, 0, 0])),
            (255, bytes([0, 0, 1, 127])),
            (16383, bytes([0, 0, 127, 127])),
            (268435455, bytes([127, 127, 127, 127])),
        ]
        for value, expected_bytes in test_cases:
            encoded = _int_to_synchsafe(value)
            assert encoded == expected_bytes
            decoded = _synchsafe_to_int(encoded)
            assert decoded == value

    def test_strip_id3v2(self):
        """_strip_id3v2 应正确移除已有 ID3 标签。"""
        # 构造一个带 ID3v2 标签的文件
        id3_header = b"ID3" + bytes([0x03, 0x00, 0x00]) + _int_to_synchsafe(10)
        id3_body = b"\x00" * 10
        audio_data = b"\xFF\xFB\x90\x00" + b"\x00" * 100
        full_data = id3_header + id3_body + audio_data

        stripped = _strip_id3v2(full_data)
        assert stripped == audio_data

    def test_build_id3v23_tag_structure(self):
        """_build_id3v23_tag 应生成正确的 ID3v2.3 结构。"""
        song = SongInfo(song_id="1", title="Test", artist="Artist", album="Album")
        tag = _build_id3v23_tag(song, None)

        assert tag[:3] == b"ID3"
        assert tag[3] == 0x03  # version major
        assert tag[4] == 0x00  # version minor
        # 验证大小字段可正确解析
        size = _synchsafe_to_int(tag[6:10])
        assert size == len(tag) - 10


# ========== 实验性平台标记测试 ==========


class TestExperimentalPlatforms:
    """实验性平台标记测试。"""

    def test_kugou_experimental_flag(self):
        """酷狗应标记为实验性。"""
        assert KuGouParser.experimental is True
        assert KuGouParser.status == "experimental"

    def test_kuwo_experimental_flag(self):
        """酷我应标记为实验性。"""
        assert KuWoParser.experimental is True
        assert KuWoParser.status == "experimental"

    def test_netease_not_experimental(self):
        """网易云不应标记为实验性。"""
        assert NetEaseParser.experimental is False
        assert NetEaseParser.status == "stable"

    def test_qqmusic_not_experimental(self):
        """QQ音乐不应标记为实验性。"""
        assert QQMusicParser.experimental is False
        assert QQMusicParser.status == "stable"

    def test_kugou_parse_raises_experimental(self):
        """酷狗解析应抛出实验性提示。"""
        parser = KuGouParser()
        with pytest.raises(ParserError, match="实验性"):
            parser.parse_song_url("https://www.kugou.com/song/abc")

    def test_kuwo_parse_raises_experimental(self):
        """酷我解析应抛出实验性提示。"""
        parser = KuWoParser()
        with pytest.raises(ParserError, match="实验性"):
            parser.parse_song_url("http://www.kuwo.cn/play_detail/123")


# ========== 错误处理测试 ==========


class TestErrorHandling:
    """错误处理测试。"""

    def test_invalid_netease_url_raises(self):
        """无效网易云 URL 应抛出 ParserError。"""
        parser = NetEaseParser()
        with pytest.raises(ParserError):
            parser.parse_song_url("https://music.163.com/#/invalid/path")

    def test_netease_no_song_found_mock(self):
        """歌曲不存在时应抛出 ParserError。"""
        parser = NetEaseParser()
        with patch.object(
            parser, "_weapi_request", return_value={"songs": []}
        ):
            with pytest.raises(ParserError, match="未找到歌曲"):
                parser._parse_song_by_id("999999")

    def test_netease_api_error_code_mock(self):
        """API 返回非 200 code 时应抛出 ParserError。"""
        parser = NetEaseParser()
        with patch.object(
            parser,
            "_weapi_request",
            side_effect=ParserError("网易云 API 错误 (code=-462)"),
        ):
            with pytest.raises(ParserError):
                parser._parse_song_by_id("123")

    def test_copyright_restricted_song_info(self):
        """版权受限 SongInfo 应正确标记。"""
        song = SongInfo(
            song_id="1",
            title="受限歌曲",
            copyright_restricted=True,
            quality_list=[QualityInfo(quality=QUALITY_STANDARD, available=False)],
        )
        assert song.copyright_restricted is True
        assert song.get_quality(QUALITY_STANDARD) is None


# ========== MusicDownloader 集成测试 ==========


class TestMusicDownloader:
    """MusicDownloader 集成测试（mock 网络请求）。"""

    def test_downloader_initialization(self):
        """MusicDownloader 应正确初始化。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            downloader = MusicDownloader(output_dir=tmpdir)
            assert downloader.output_dir == Path(tmpdir)
            assert downloader.embed_tags is True
            assert downloader.download_cover is True

    def test_downloader_parse_song_mock(self):
        """parse_song 应正确解析（mock 解析器）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            downloader = MusicDownloader(output_dir=tmpdir)
            mock_song = SongInfo(song_id="123", title="Mock Song")
            with patch.object(
                NetEaseParser, "parse_song_url", return_value=mock_song
            ):
                song = downloader.parse_song("https://music.163.com/song?id=123")
                assert song.title == "Mock Song"

    def test_downloader_build_filename(self):
        """应构建安全的文件名。"""
        song = SongInfo(
            song_id="1",
            title='测试:歌曲/名称*特别?',
            artist='歌手/名字',
        )
        filename = MusicDownloader._build_filename(song, "mp3")
        assert filename.endswith(".mp3")
        # 非法字符应被替换
        assert ":" not in filename
        assert "/" not in filename
        assert "*" not in filename
        assert "?" not in filename

    def test_downloader_resolve_quality_fallback(self):
        """音质不可用时应自动降级。"""
        song = SongInfo(
            song_id="1",
            title="test",
            quality_list=[
                QualityInfo(quality=QUALITY_STANDARD, available=True),
                QualityInfo(quality=QUALITY_HIGHER, available=False),
            ],
        )
        result = MusicDownloader._resolve_quality(song, QUALITY_LOSSLESS)
        assert result == QUALITY_STANDARD
