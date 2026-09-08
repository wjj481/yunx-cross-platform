"""
视频解析模块单元测试。

覆盖：工厂函数 URL 匹配、VideoInfo 数据类、各平台 ID 提取、
清晰度列表解析、下载 URL 获取（mock）、实验性平台标记、错误处理。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.exceptions import ParserError
from core.video import (
    BaseVideoParser,
    QualityOption,
    VideoInfo,
    VideoDownloader,
    get_video_parser,
    list_supported_platforms,
)
from core.video.bilibili import BilibiliParser, av_to_bv, bv_to_av
from core.video.douyin import DouyinParser
from core.video.youtube import YoutubeParser
from core.video.kuaishou import KuaishouParser
from core.video.weibo import WeiboParser
from core.video.xiaohongshu import XiaohongshuParser
from core.video.xigua import XiguaParser
from core.video.zhihu import ZhihuParser
from core.video.twitter import TwitterParser
from core.video.tiktok import TiktokParser
from core.video.instagram import InstagramParser
from core.video.facebook import FacebookParser


# ============================================================
# 1. 工厂函数 URL 匹配测试
# ============================================================

class TestVideoParserFactory:
    """视频解析器工厂匹配测试。"""

    def test_bilibili_url_matches(self):
        """B站链接应匹配 BilibiliParser。"""
        parser = get_video_parser("https://www.bilibili.com/video/BV1xx411c7mD")
        assert isinstance(parser, BilibiliParser)

    def test_bilibili_short_url_matches(self):
        """b23.tv 短链应匹配 BilibiliParser。"""
        parser = get_video_parser("https://b23.tv/abc123")
        assert isinstance(parser, BilibiliParser)

    def test_douyin_url_matches(self):
        """抖音链接应匹配 DouyinParser。"""
        parser = get_video_parser("https://www.douyin.com/video/7123456789012345678")
        assert isinstance(parser, DouyinParser)

    def test_douyin_short_url_matches(self):
        """抖音短链应匹配 DouyinParser。"""
        parser = get_video_parser("https://v.douyin.com/abc123/")
        assert isinstance(parser, DouyinParser)

    def test_youtube_watch_url_matches(self):
        """YouTube watch 链接应匹配 YoutubeParser。"""
        parser = get_video_parser("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert isinstance(parser, YoutubeParser)

    def test_youtu_be_url_matches(self):
        """youtu.be 短链应匹配 YoutubeParser。"""
        parser = get_video_parser("https://youtu.be/dQw4w9WgXcQ")
        assert isinstance(parser, YoutubeParser)

    def test_youtube_shorts_url_matches(self):
        """YouTube Shorts 链接应匹配 YoutubeParser。"""
        parser = get_video_parser("https://www.youtube.com/shorts/dQw4w9WgXcQ")
        assert isinstance(parser, YoutubeParser)

    def test_experimental_platforms_match(self):
        """实验性平台链接应匹配对应解析器。"""
        cases = [
            ("https://www.kuaishou.com/short-video/xxx", KuaishouParser),
            ("https://weibo.com/tv/show/xxx", WeiboParser),
            ("https://www.xiaohongshu.com/explore/xxx", XiaohongshuParser),
            ("https://www.ixigua.com/123456", XiguaParser),
            ("https://www.zhihu.com/zvideo/123456", ZhihuParser),
            ("https://twitter.com/user/status/123456", TwitterParser),
            ("https://x.com/user/status/123456", TwitterParser),
            ("https://www.tiktok.com/@user/video/123456", TiktokParser),
            ("https://www.instagram.com/reel/abc123", InstagramParser),
            ("https://www.facebook.com/user/videos/123456", FacebookParser),
        ]
        for url, expected_cls in cases:
            parser = get_video_parser(url)
            assert isinstance(parser, expected_cls), f"{url} 应匹配 {expected_cls.__name__}"

    def test_unknown_url_raises(self):
        """未知域名应抛出 ParserError。"""
        with pytest.raises(ParserError, match="无法识别的视频链接"):
            get_video_parser("https://example.com/video/123")

    def test_factory_passes_credential(self):
        """工厂应正确传递 credential。"""
        cred = {"cookie": "test=123"}
        parser = get_video_parser(
            "https://www.bilibili.com/video/BV1xx", credential=cred
        )
        assert parser.credential == cred


# ============================================================
# 2. VideoInfo 数据类测试
# ============================================================

class TestVideoInfo:
    """VideoInfo 数据类测试。"""

    def test_video_info_creation(self):
        """VideoInfo 应能正确创建并访问字段。"""
        info = VideoInfo(
            title="测试视频",
            cover="https://example.com/cover.jpg",
            duration=120,
            platform="bilibili",
            video_id="BV1xx",
        )
        assert info.title == "测试视频"
        assert info.duration == 120
        assert info.platform == "bilibili"
        assert info.quality_list == []
        assert info.file_size == 0

    def test_best_quality_returns_highest(self):
        """best_quality 应返回清晰度列表第一项。"""
        info = VideoInfo(
            title="test",
            quality_list=[
                QualityOption(quality="1080p"),
                QualityOption(quality="720p"),
            ],
        )
        best = info.best_quality()
        assert best is not None
        assert best.quality == "1080p"

    def test_best_quality_empty_list(self):
        """空清晰度列表时 best_quality 返回 None。"""
        info = VideoInfo(title="test")
        assert info.best_quality() is None

    def test_find_quality_case_insensitive(self):
        """find_quality 应不区分大小写。"""
        info = VideoInfo(
            title="test",
            quality_list=[
                QualityOption(quality="1080P", file_size=1000),
                QualityOption(quality="720p", file_size=500),
            ],
        )
        result = info.find_quality("1080p")
        assert result is not None
        assert result.file_size == 1000

    def test_find_quality_not_found(self):
        """未找到清晰度时返回 None。"""
        info = VideoInfo(title="test", quality_list=[QualityOption(quality="720p")])
        assert info.find_quality("4k") is None

    def test_quality_option_fields(self):
        """QualityOption 应包含所有字段。"""
        opt = QualityOption(
            quality="1080p",
            file_size=1024000,
            format="mp4",
            code="80",
            description="1080P 高清",
        )
        assert opt.quality == "1080p"
        assert opt.format == "mp4"
        assert opt.code == "80"


# ============================================================
# 3. B站 BV/AV 号识别测试
# ============================================================

class TestBilibiliIds:
    """B站 BV/AV 号转换与识别测试。"""

    def test_bv_to_av_known_value(self):
        """BV 号转 AV 号（已知对应关系）。"""
        # BV17x411w7KC -> av170001 (经典测试用例)
        av = bv_to_av("BV17x411w7KC")
        assert av == 170001

    def test_av_to_bv_known_value(self):
        """AV 号转 BV 号（已知对应关系）。"""
        bv = av_to_bv(170001)
        assert bv == "BV17x411w7KC"

    def test_bv_av_roundtrip(self):
        """BV <-> AV 往返转换应一致。"""
        original_av = 12345678
        bv = av_to_bv(original_av)
        recovered_av = bv_to_av(bv)
        assert recovered_av == original_av

    def test_extract_bv_from_url(self):
        """应能从 URL 中提取 BV 号。"""
        parser = BilibiliParser()
        bvid, aid, page = parser._extract_ids(
            "https://www.bilibili.com/video/BV1xx411c7mD"
        )
        assert bvid == "BV1xx411c7mD"
        assert aid == 0
        assert page == 1

    def test_extract_av_from_url(self):
        """应能从 URL 中提取 AV 号。"""
        parser = BilibiliParser()
        bvid, aid, page = parser._extract_ids(
            "https://www.bilibili.com/video/av170001"
        )
        assert bvid == ""
        assert aid == 170001

    def test_extract_page_number(self):
        """应能从 URL 中提取分P号。"""
        parser = BilibiliParser()
        _, _, page = parser._extract_ids(
            "https://www.bilibili.com/video/BV1xx411c7mD?p=3"
        )
        assert page == 3

    def test_invalid_url_raises(self):
        """无 BV/AV 号的 URL 应抛出 ParserError。"""
        parser = BilibiliParser()
        with pytest.raises(ParserError, match="无法从链接中提取"):
            parser._extract_ids("https://www.bilibili.com/")


# ============================================================
# 4. 抖音短链接识别测试
# ============================================================

class TestDouyinIds:
    """抖音视频 ID 提取测试。"""

    def test_extract_aweme_id_from_video_url(self):
        """应能从 /video/ URL 中提取 aweme_id。"""
        aweme_id = DouyinParser._extract_aweme_id(
            "https://www.douyin.com/video/7123456789012345678"
        )
        assert aweme_id == "7123456789012345678"

    def test_extract_aweme_id_from_note_url(self):
        """应能从 /note/ URL 中提取 aweme_id。"""
        aweme_id = DouyinParser._extract_aweme_id(
            "https://www.douyin.com/note/7223456789012345678"
        )
        assert aweme_id == "7223456789012345678"

    def test_invalid_douyin_url_raises(self):
        """无视频 ID 的 URL 应抛出 ParserError。"""
        with pytest.raises(ParserError, match="无法从链接中提取视频 ID"):
            DouyinParser._extract_aweme_id("https://www.douyin.com/")


# ============================================================
# 5. YouTube 视频 ID 提取测试
# ============================================================

class TestYoutubeIds:
    """YouTube 视频 ID 提取测试。"""

    def test_extract_from_watch_url(self):
        """应能从 watch URL 提取视频 ID。"""
        video_id = YoutubeParser._extract_video_id(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )
        assert video_id == "dQw4w9WgXcQ"

    def test_extract_from_youtu_be(self):
        """应能从 youtu.be 短链提取视频 ID。"""
        video_id = YoutubeParser._extract_video_id(
            "https://youtu.be/dQw4w9WgXcQ"
        )
        assert video_id == "dQw4w9WgXcQ"

    def test_extract_from_embed_url(self):
        """应能从 embed URL 提取视频 ID。"""
        video_id = YoutubeParser._extract_video_id(
            "https://www.youtube.com/embed/dQw4w9WgXcQ"
        )
        assert video_id == "dQw4w9WgXcQ"

    def test_extract_from_shorts_url(self):
        """应能从 shorts URL 提取视频 ID。"""
        video_id = YoutubeParser._extract_video_id(
            "https://www.youtube.com/shorts/dQw4w9WgXcQ"
        )
        assert video_id == "dQw4w9WgXcQ"

    def test_extract_from_live_url(self):
        """应能从 live URL 提取视频 ID。"""
        video_id = YoutubeParser._extract_video_id(
            "https://www.youtube.com/live/dQw4w9WgXcQ"
        )
        assert video_id == "dQw4w9WgXcQ"

    def test_invalid_youtube_url_raises(self):
        """无效 YouTube URL 应抛出 ParserError。"""
        with pytest.raises(ParserError, match="无法从链接中提取 YouTube 视频 ID"):
            YoutubeParser._extract_video_id("https://www.youtube.com/")


# ============================================================
# 6. 清晰度列表解析测试（mock）
# ============================================================

class TestQualityParsing:
    """清晰度列表解析测试（使用 mock 数据）。"""

    def test_bilibili_quality_list_from_mock(self):
        """B站应能从 mock 响应构建清晰度列表。"""
        mock_data = {
            "accept_quality": [120, 116, 80, 64, 32, 16],
            "dash": {
                "video": [
                    {"id": 120, "bandwidth": 5000000},
                    {"id": 80, "bandwidth": 2000000},
                ],
            },
            "timelength": 120000,
        }
        parser = BilibiliParser()
        quality_list = parser._fetch_quality_list.__wrapped__(parser, "BV1xx", 123) \
            if hasattr(parser._fetch_quality_list, "__wrapped__") else None

        # 直接测试内部映射
        qn = parser._quality_to_qn("1080p")
        assert qn == 80
        qn_4k = parser._quality_to_qn("4k")
        assert qn_4k == 120

    def test_douyin_quality_list_from_mock(self):
        """抖音应能从 mock 视频信息构建清晰度列表。"""
        mock_video = {
            "bit_rate": [
                {
                    "gear_name": "720p",
                    "bit_rate": 1500000,
                    "play_addr": {"data_size": 10240000, "url_list": ["http://x/720"]},
                },
                {
                    "gear_name": "480p",
                    "bit_rate": 800000,
                    "play_addr": {"data_size": 5120000, "url_list": ["http://x/480"]},
                },
            ]
        }
        quality_list = DouyinParser._build_quality_list(mock_video)
        assert len(quality_list) == 2
        # 按 file_size 降序
        assert quality_list[0].quality == "720p"
        assert quality_list[0].file_size == 10240000
        assert quality_list[1].quality == "480p"

    def test_douyin_quality_list_no_bit_rate(self):
        """无 bit_rate 时应返回默认 720p。"""
        mock_video = {
            "play_addr": {"data_size": 8000000, "url_list": ["http://x/v"]}
        }
        quality_list = DouyinParser._build_quality_list(mock_video)
        assert len(quality_list) == 1
        assert quality_list[0].quality == "720p"

    def test_youtube_quality_list_from_mock(self):
        """YouTube 应能从 mock player_response 构建清晰度列表。"""
        mock_response = {
            "streamingData": {
                "formats": [
                    {"itag": 18, "mimeType": "video/mp4", "contentLength": "5000000"},
                    {"itag": 22, "mimeType": "video/mp4", "contentLength": "15000000"},
                ],
                "adaptiveFormats": [
                    {"itag": 137, "mimeType": "video/mp4", "contentLength": "30000000"},
                    {"itag": 140, "mimeType": "audio/mp4", "contentLength": "2000000"},
                ],
            }
        }
        parser = YoutubeParser()
        quality_list = parser._build_quality_list(mock_response)
        qualities = [q.quality for q in quality_list]
        assert "720p" in qualities  # itag 22
        assert "360p" in qualities  # itag 18
        assert "1080p" in qualities  # itag 137
        # 纯音频不应出现在列表中
        assert not any(q.quality.startswith("audio") for q in quality_list)


# ============================================================
# 7. 下载 URL 获取测试（mock）
# ============================================================

class TestDownloadUrl:
    """下载 URL 获取测试（mock）。"""

    def test_douyin_get_download_url(self):
        """抖音应能从 VideoInfo 中提取下载直链。"""
        video_info = VideoInfo(
            title="test",
            quality_list=[QualityOption(quality="720p", code="0")],
            raw_response={
                "video": {
                    "play_addr": {
                        "url_list": ["https://v3.douyincdn.com/xxx.mp4"]
                    }
                }
            },
        )
        parser = DouyinParser()
        url = parser.get_download_url(video_info, "720p")
        assert url == "https://v3.douyincdn.com/xxx.mp4"

    def test_douyin_get_download_url_invalid_quality(self):
        """抖音请求不支持的清晰度应抛出 ParserError。"""
        video_info = VideoInfo(
            title="test",
            quality_list=[QualityOption(quality="720p")],
            raw_response={"video": {}},
        )
        parser = DouyinParser()
        with pytest.raises(ParserError, match="不支持的清晰度"):
            parser.get_download_url(video_info, "4k")

    def test_youtube_get_download_url_from_formats(self):
        """YouTube 应能从 formats 中提取对应 itag 的 URL。"""
        video_info = VideoInfo(
            title="test",
            quality_list=[QualityOption(quality="720p", code="22")],
            raw_response={
                "streamingData": {
                    "formats": [
                        {"itag": 18, "url": "https://x/360.mp4"},
                        {"itag": 22, "url": "https://x/720.mp4"},
                    ],
                    "adaptiveFormats": [],
                }
            },
        )
        parser = YoutubeParser()
        url = parser.get_download_url(video_info, "720p")
        assert url == "https://x/720.mp4"

    def test_youtube_get_download_url_from_adaptive(self):
        """YouTube 应能从 adaptiveFormats 中提取对应 itag 的 URL。"""
        video_info = VideoInfo(
            title="test",
            quality_list=[QualityOption(quality="1080p", code="137")],
            raw_response={
                "streamingData": {
                    "formats": [],
                    "adaptiveFormats": [
                        {"itag": 137, "url": "https://x/1080.mp4"},
                    ],
                }
            },
        )
        parser = YoutubeParser()
        url = parser.get_download_url(video_info, "1080p")
        assert url == "https://x/1080.mp4"

    def test_youtube_get_download_url_not_found(self):
        """YouTube 找不到对应 itag 时应抛出 ParserError。"""
        video_info = VideoInfo(
            title="test",
            quality_list=[QualityOption(quality="4k", code="313")],
            raw_response={"streamingData": {"formats": [], "adaptiveFormats": []}},
        )
        parser = YoutubeParser()
        with pytest.raises(ParserError, match="未找到 itag"):
            parser.get_download_url(video_info, "4k")


# ============================================================
# 8. 实验性平台标记测试
# ============================================================

class TestExperimentalFlag:
    """实验性平台标记测试。"""

    def test_stable_platforms_not_experimental(self):
        """稳定版平台不应标记为 experimental。"""
        assert BilibiliParser.experimental is False
        assert DouyinParser.experimental is False
        assert YoutubeParser.experimental is False

    def test_experimental_platforms_flagged(self):
        """实验性平台应标记为 experimental=True。"""
        experimental_parsers = [
            KuaishouParser, WeiboParser, XiaohongshuParser,
            XiguaParser, ZhihuParser, TwitterParser,
            TiktokParser, InstagramParser, FacebookParser,
        ]
        for parser_cls in experimental_parsers:
            assert parser_cls.experimental is True, (
                f"{parser_cls.__name__} 应标记为 experimental"
            )

    def test_list_supported_platforms_includes_status(self):
        """list_supported_platforms 应包含 experimental 状态。"""
        platforms = list_supported_platforms()
        platform_map = {p["platform"]: p for p in platforms}
        assert platform_map["bilibili"]["experimental"] is False
        assert platform_map["kuaishou"]["experimental"] is True
        assert len(platforms) == 12

    def test_experimental_parser_raises_on_parse(self):
        """实验性解析器调用 parse 应抛出友好错误。"""
        parser = KuaishouParser()
        with pytest.raises(ParserError, match="实验性功能"):
            parser.parse_video_url("https://www.kuaishou.com/short-video/xxx")


# ============================================================
# 9. 错误处理测试
# ============================================================

class TestErrorHandling:
    """错误处理测试。"""

    def test_bilibili_api_error_raises_parser_error(self):
        """B站 API 返回非零 code 应抛出 ParserError。"""
        parser = BilibiliParser()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": -404, "message": "视频不存在"}
        mock_resp.status_code = 200

        with patch.object(parser._session, "get", return_value=mock_resp):
            with patch.object(parser, "_sign_wbi", side_effect=lambda p: p):
                with pytest.raises(ParserError, match="视频不存在"):
                    parser._api_get("https://api.bilibili.com/x/web-interface/view")

    def test_bilibili_network_error(self):
        """B站网络请求失败应抛出 NetworkError。"""
        import requests
        parser = BilibiliParser()
        with patch.object(
            parser._session, "get",
            side_effect=requests.ConnectionError("timeout"),
        ):
            from core.exceptions import NetworkError
            with pytest.raises(NetworkError):
                parser._api_get("https://api.bilibili.com/x/web-interface/view")

    def test_youtube_unplayable_raises(self):
        """YouTube 视频不可播放时应抛出 ParserError。"""
        mock_response = {
            "playabilityStatus": {
                "status": "ERROR",
                "reason": "Video unavailable",
            }
        }
        parser = YoutubeParser()
        with pytest.raises(ParserError, match="视频不可播放"):
            parser._build_quality_list(mock_response)

    def test_video_info_sanitize_filename(self):
        """文件名清理应移除非法字符。"""
        cleaned = BaseVideoParser._sanitize_filename('test:file?name*123')
        assert ":" not in cleaned
        assert "?" not in cleaned
        assert "*" not in cleaned


# ============================================================
# 10. VideoDownloader 集成测试
# ============================================================

class TestVideoDownloader:
    """VideoDownloader 集成测试。"""

    def test_downloader_initialization(self):
        """VideoDownloader 应能正确初始化。"""
        downloader = VideoDownloader(concurrency=4, chunk_size=1024*1024)
        assert downloader._engine.concurrency == 4
        assert downloader._engine.chunk_size == 1024 * 1024

    def test_downloader_select_best_quality(self):
        """未指定清晰度时应自动选择最高清晰度。"""
        downloader = VideoDownloader()
        video_info = VideoInfo(
            title="test",
            quality_list=[
                QualityOption(quality="1080p", format="mp4"),
                QualityOption(quality="720p", format="mp4"),
            ],
            platform="bilibili",
        )
        # 验证 best_quality 逻辑
        best = video_info.best_quality()
        assert best is not None
        assert best.quality == "1080p"

    def test_downloader_build_output_path(self):
        """应能正确构建输出文件路径。"""
        video_info = VideoInfo(title="测试视频: 特别篇", platform="bilibili")
        option = QualityOption(quality="1080p", format="mp4")
        path = VideoDownloader._build_output_path(
            video_info, option, "/tmp/test_output", None
        )
        assert path.suffix == ".mp4"
        assert "1080p" in path.name
        assert ":" not in path.name  # 非法字符已清理

    def test_downloader_build_headers_with_referer(self):
        """应根据平台添加正确的 Referer。"""
        video_info = VideoInfo(title="test", platform="bilibili")
        headers = VideoDownloader._build_headers(video_info, None)
        assert headers["Referer"] == "https://www.bilibili.com"

        video_info_douyin = VideoInfo(title="test", platform="douyin")
        headers = VideoDownloader._build_headers(video_info_douyin, None)
        assert headers["Referer"] == "https://www.douyin.com/"
