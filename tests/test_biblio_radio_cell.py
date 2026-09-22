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
def test_the_extracted_editor_grows_with_its_wrapped_text_instead_of_scrolling(qapp, panel):
    from PyQt6.QtCore import Qt
    group = QButtonGroup()
    long_title = ('Trilobites of the post-Sardic (Upper Ordovician) sequence of southern Sardinia, '
                  'with a revision of the genera and a note on their stratigraphic distribution')
    cell = panel._build_radio_cell('title', long_title, group, radio_id=1, editable=True, css_class='ConflictValue')
    cell.resize(320, 200)
    cell.show()
    qapp.processEvents()
    edit = panel._field_edits['title']
    assert edit.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    wrapped = int(edit.document().documentLayout().documentSize().height())
    assert wrapped >= 3                                     # it wraps at this width
    assert edit.height() >= wrapped * edit.fontMetrics().lineSpacing()
    narrow = edit.height()
    cell.resize(900, 200)
    qapp.processEvents()
    assert edit.height() < narrow                           # wider: fewer lines, shorter box


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


@pytest.mark.ui
def test_apply_shows_the_wait_cursor_until_the_worker_reports(qapp, panel, monkeypatch):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QPushButton

    from desktop.views import detail_panel as mod

    class Task:
        def __init__(self, fn, *a, **k):
            self.done = _Sig()
            self.failed = _Sig()

        def start(self):
            pass

    class _Sig:
        def __init__(self):
            self.slots = []

        def connect(self, fn):
            self.slots.append(fn)

        def emit(self, *a):
            for fn in self.slots:
                fn(*a)

    monkeypatch.setattr(mod, 'BackgroundTask', Task)
    panel._current_paper_id = 1
    panel._apply_btn = QPushButton('Apply')
    panel._field_groups = {}
    panel._on_apply_clicked()
    assert QApplication.overrideCursor() is not None
    assert QApplication.overrideCursor().shape() == Qt.CursorShape.WaitCursor
    monkeypatch.setattr(panel, 'show_paper', lambda pid: None)
    panel._apply_task.done.emit(('applied', False, ''))
    assert QApplication.overrideCursor() is None
    panel._on_apply_clicked()
    panel._apply_task.failed.emit('boom')
    assert QApplication.overrideCursor() is None and panel._apply_btn.text() == 'Failed'
