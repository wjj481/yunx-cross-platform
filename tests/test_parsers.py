"""
解析器工厂匹配测试。

测试 get_parser() 能否根据 URL 域名正确匹配到对应解析器。
"""

import pytest

from core.parsers import get_parser, list_supported_drives
from core.parsers.quark import QuarkParser
from core.parsers.pan123 import Pan123Parser
from core.parsers.xunlei import XunleiParser
from core.parsers.baidu import BaiduParser
from core.parsers.uc import UCParser
from core.parsers.caiyun import CaiyunParser
from core.exceptions import ParserError


class TestParserFactory:
    """解析器工厂匹配测试。"""

    def test_quark_url_matches(self):
        """夸克链接应匹配 QuarkParser。"""
        parser = get_parser("https://pan.quark.cn/s/abc123")
        assert isinstance(parser, QuarkParser)

    def test_pan123_url_matches(self):
        """123 云盘链接应匹配 Pan123Parser。"""
        parser = get_parser("https://www.123pan.com/s/abc-def")
        assert isinstance(parser, Pan123Parser)

    def test_pan123_123865_url_matches(self):
        """123865 域名应匹配 Pan123Parser。"""
        parser = get_parser("https://www.123865.com/s/abc-def")
        assert isinstance(parser, Pan123Parser)

    def test_xunlei_url_matches(self):
        """迅雷链接应匹配 XunleiParser。"""
        parser = get_parser("https://pan.xunlei.com/s/abc-123")
        assert isinstance(parser, XunleiParser)

    def test_baidu_url_matches(self):
        """百度链接应匹配 BaiduParser。"""
        parser = get_parser("https://pan.baidu.com/s/1abc123")
        assert isinstance(parser, BaiduParser)

    def test_uc_url_matches(self):
        """UC 链接应匹配 UCParser。"""
        parser = get_parser("https://drive.uc.cn/s/abc123")
        assert isinstance(parser, UCParser)

    def test_caiyun_url_matches(self):
        """和彩云链接应匹配 CaiyunParser。"""
        parser = get_parser("https://yun.139.com/shareweb/#/w/i/abc123")
        assert isinstance(parser, CaiyunParser)

    def test_unknown_url_raises(self):
        """未知域名应抛出 ParserError。"""
        with pytest.raises(ParserError):
            get_parser("https://example.com/s/abc")

    def test_parser_with_credential(self):
        """工厂应正确传递 credential。"""
        cred = {"cookie": "test=123"}
        parser = get_parser("https://pan.quark.cn/s/abc", credential=cred)
        assert parser.credential == cred

    def test_list_supported_drives(self):
        """list_supported_drives 应返回所有网盘。"""
        drives = list_supported_drives()
        drive_names = [d["drive"] for d in drives]
        assert "quark" in drive_names
        assert "pan123" in drive_names
        assert "xunlei" in drive_names
        assert "baidu" in drive_names
        assert "uc" in drive_names
        assert "caiyun" in drive_names

    def test_stable_vs_experimental(self):
        """稳定版和实验性解析器状态应正确。"""
        drives = {d["drive"]: d["status"] for d in list_supported_drives()}
        assert drives["quark"] == "stable"
        assert drives["pan123"] == "stable"
        assert drives["xunlei"] == "stable"
        assert drives["baidu"] == "experimental"
        assert drives["uc"] == "experimental"
        assert drives["caiyun"] == "experimental"


class TestExtractCodeFromUrl:
    """URL 提取码自动识别测试。"""

    def test_extract_code_from_fragment(self):
        """应从 URL fragment 中提取提取码。"""
        parser = get_parser("https://pan.quark.cn/s/abc#1234")
        code = parser._resolve_extract_code(
            "https://pan.quark.cn/s/abc#1234", None
        )
        assert code == "1234"

    def test_extract_code_from_query_pwd(self):
        """应从 ?pwd= 参数中提取提取码。"""
        parser = get_parser("https://pan.baidu.com/s/1abc?pwd=abcd")
        code = parser._resolve_extract_code(
            "https://pan.baidu.com/s/1abc?pwd=abcd", None
        )
        assert code == "abcd"

    def test_explicit_code_overrides_url(self):
        """显式传入的提取码应优先于 URL 中的。"""
        parser = get_parser("https://pan.quark.cn/s/abc#1234")
        code = parser._resolve_extract_code(
            "https://pan.quark.cn/s/abc#1234", "5678"
        )
        assert code == "5678"
