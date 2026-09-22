"""The biblio comparison cell: the radio sits in the corner beside the value
(one row, for long fields too), and clicking the current value picks it."""
import pytest
from PyQt6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPlainTextEdit, QRadioButton


@pytest.fixture
def panel(qapp):
    from desktop.views.detail_panel import DetailPanel
    p = DetailPanel()
    p._field_edits = {}
    return p


@pytest.mark.ui
def test_a_long_field_keeps_the_radio_beside_the_text_not_above_it(panel):
    group = QButtonGroup()
    cell = panel._build_radio_cell('title', 'A long title\nover two lines', group, radio_id=1, editable=True,
                                   css_class='ConflictValue')
    lay = cell.layout()
    assert isinstance(lay, QHBoxLayout) and lay.count() == 3          # radio, editor, × — one row
    assert isinstance(lay.itemAt(0).widget(), QRadioButton)
    assert isinstance(lay.itemAt(1).widget(), QPlainTextEdit)
    assert lay.itemAt(1).widget().height() > lay.itemAt(0).widget().sizeHint().height()
    assert panel._field_edits['title'] is lay.itemAt(1).widget()


@pytest.mark.ui
def test_clicking_the_current_value_picks_its_radio(panel):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    group = QButtonGroup()
    paper = panel._build_radio_cell('year', '1936', group, radio_id=0, editable=False, css_class='FieldValue')
    biblio = panel._build_radio_cell('year', '1937', group, radio_id=1, editable=True, css_class='ConflictValue')
    group.button(1).setChecked(True)
    label = next(w for w in paper.findChildren(QLabel))
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(2, 2), QPointF(2, 2),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    label.mouseReleaseEvent(ev)
    assert group.checkedId() == 0
    assert biblio.layout().count() == 3 and paper.layout().count() == 2
