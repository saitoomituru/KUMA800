"""Python package骨格の回帰試験。"""

from kuma800 import __version__


def test_package_version_is_exposed() -> None:
    """packageが初期versionを公開することを確認する。"""
    assert __version__ == "0.0.1"
