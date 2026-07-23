"""Author-name display formatting (paper list citation style)."""
import pytest

from desktop.services.paper_service import _cite_name


@pytest.mark.unit
@pytest.mark.parametrize("name,expected", [
    ("정, 직한", "정직한"),        # Zotero split "Last, First"
    ("정직한", "정직한"),           # unspaced
    ("정 직한", "정직한"),          # legacy "Last First"
    ("최, 덕근", "최덕근"),
    ("小林, 一", "小林一"),          # Japanese "Last, First"
    ("고바야시이치로", "고바야시이치로"),
])
def test_cite_name_cjk_surname_first_joined(name, expected):
    # CJK names render surname-first with no separator (LastnameFirstname).
    assert _cite_name(name) == expected


@pytest.mark.unit
@pytest.mark.parametrize("name,expected", [
    ("Smith", "Smith"),
    ("John Smith", "Smith"),
    ("Smith, John", "Smith"),
])
def test_cite_name_western_lastname_only(name, expected):
    assert _cite_name(name) == expected
