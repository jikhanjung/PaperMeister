"""Citation-network ego graph — force-directed layout (pure)."""
import pytest

from desktop.windows.network_window import spring_layout


@pytest.mark.unit
def test_center_pinned_and_in_bounds():
    pos = spring_layout({1, 2, 3, 4}, [(1, 2), (1, 3), (1, 4)],
                        center_id=1, width=800, height=600, iterations=20)
    assert set(pos) == {1, 2, 3, 4}
    assert pos[1] == (400.0, 300.0)   # center pinned at the middle
    for x, y in pos.values():
        assert 0 <= x <= 800 and 0 <= y <= 600


@pytest.mark.unit
def test_edge_cases():
    assert spring_layout(set(), [], None) == {}
    assert spring_layout({9}, [], 9, width=800, height=600) == {9: (400.0, 300.0)}


@pytest.mark.unit
def test_deterministic():
    a = spring_layout({1, 2, 3}, [(1, 2)], 1, iterations=25)
    b = spring_layout({1, 2, 3}, [(1, 2)], 1, iterations=25)
    assert a == b   # no RNG — circle seed → reproducible
