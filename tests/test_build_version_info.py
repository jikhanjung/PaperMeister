"""The Windows version resource must rise between builds (Modan2 devlog 285).

A uniform 0.0.0.0 passed every consistency check while Inno Setup kept the
old exe on upgrade, so test the numbers themselves, not just their agreement.
"""
import ast
from pathlib import Path

from build_version_info import prepare_version_info_file, windows_file_version
from version import __version__


def test_build_number_is_fourth_field():
    assert windows_file_version("0.2.2", "512") == (0, 2, 2, 512)


def test_prereleases_of_one_version_differ_by_build_number():
    a = windows_file_version("0.3.0-beta.1", "600")
    b = windows_file_version("0.3.0-beta.2", "601")
    assert a < b


def test_development_build_without_number_gets_zero():
    assert windows_file_version("0.2.2", "") == (0, 2, 2, 0)


def test_version_file_carries_real_version():
    text = Path(prepare_version_info_file(__version__, "PaperMeister", "123")).read_text(encoding="utf-8")
    expected = windows_file_version(__version__, "123")
    assert expected != (0, 0, 0, 0)
    assert f"filevers={expected}" in text
    assert "PaperMeister.exe" in text
    ast.parse(text)  # PyInstaller eval()s this file
