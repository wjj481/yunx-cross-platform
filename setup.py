"""
YunX 跨平台网盘解析 + 高速下载工具 —— 安装配置。
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="yunx-cross-platform",
    version="0.1.0",
    description="跨平台网盘解析 + 高速下载工具（核心引擎）",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="YunX Contributors",
    license="AGPL-3.0",
    packages=find_packages(exclude=["desktop_gui", "mobile_gui", "build", "tests"]),
    python_requires=">=3.9",
    install_requires=[
        "requests>=2.31.0",
        "aiohttp>=3.9.0",
        "cryptography>=41.0.0",
        "tqdm>=4.65.0",
    ],
    extras_require={
        "desktop": [],  # tkinter 内置
        "mobile": ["kivy>=2.3.0"],
        "build": ["pyinstaller>=6.0.0"],
        "test": ["pytest>=7.4.0", "pytest-mock>=3.11.0"],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: GNU Affero General Public License v3",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Internet :: File Transfer Protocol (FTP)",
        "Topic :: Utilities",
    ],
)
