"""Generate Qt StyleSheet from design tokens."""
from .tokens import FONT, LAYOUT, RADIUS


def build_stylesheet(c: dict) -> str:
    """Build the global QSS from a color token dict.

    Keeping this in Python (rather than a .qss file) so tokens drive the
    output: dark/light swap is a dict change, not an edit.
    """
    return f"""
/* ── Base ─────────────────────────────────────────────────── */
QWidget {{
    background-color: {c['bg.app']};
    color: {c['text.primary']};
    font-size: {FONT['size.md']}px;
    selection-background-color: {c['accent.muted']};
    selection-color: {c['text.primary']};
}}

QMainWindow {{
    background-color: {c['bg.app']};
}}

/* ── Scroll bars ──────────────────────────────────────────── */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {c['border.default']};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {c['border.strong']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: {c['border.default']};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {c['border.strong']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── Top bar ──────────────────────────────────────────────── */
#TopBar {{
    background-color: {c['bg.panel']};
    border-bottom: 1px solid {c['border.subtle']};
    min-height: {LAYOUT['topbar.height']}px;
    max-height: {LAYOUT['topbar.height']}px;
}}
#TopBar QLabel#AppTitle {{
    color: {c['text.primary']};
    font-size: {FONT['size.lg']}px;
    font-weight: {FONT['weight.bold']};
    padding-left: 14px;
}}

/* ── Search bar ───────────────────────────────────────────── */
#SearchBar {{
    background-color: {c['bg.elevated']};
    border: 1px solid {c['border.default']};
    border-radius: {RADIUS['md']}px;
    padding: 6px 10px;
    color: {c['text.primary']};
}}
#SearchBar:focus {{
    border: 1px solid {c['accent.primary']};
}}

/* ── Rail (leftmost) ──────────────────────────────────────── */
#Rail {{
    background-color: {c['bg.panel']};
    border-right: 1px solid {c['border.subtle']};
    min-width: {LAYOUT['rail.width']}px;
    max-width: {LAYOUT['rail.width']}px;
}}
#Rail QToolButton {{
    background: transparent;
    border: none;
    color: {c['text.secondary']};
    padding: 10px;
    margin: 2px 4px;
    border-radius: {RADIUS['md']}px;
}}
#Rail QToolButton:hover {{
    background-color: {c['bg.hover']};
    color: {c['text.primary']};
}}
#Rail QToolButton:checked {{
    background-color: {c['bg.selected']};
    color: {c['accent.primary']};
}}

/* ── Side panels ──────────────────────────────────────────── */
#SourceNav, #DetailPanel {{
    background-color: {c['bg.panel']};
    border-right: 1px solid {c['border.subtle']};
}}
#DetailPanel {{
    border-right: none;
    border-left: 1px solid {c['border.subtle']};
}}

QLabel.SectionHeader {{
    color: {c['text.muted']};
    font-size: {FONT['size.xs']}px;
    font-weight: {FONT['weight.medium']};
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 12px 12px 6px 12px;
}}

/* ── Tree (SourceNav) ─────────────────────────────────────── */
QTreeView, QTreeWidget {{
    background-color: {c['bg.panel']};
    border: none;
    outline: 0;
    padding: 4px 4px;
    color: {c['text.primary']};
    show-decoration-selected: 1;
}}
QTreeView::item, QTreeWidget::item {{
    padding: 6px 6px;
    border-radius: {RADIUS['sm']}px;
    color: {c['text.primary']};
}}
QTreeView::item:hover, QTreeWidget::item:hover {{
    background-color: {c['bg.hover']};
}}
QTreeView::item:selected, QTreeWidget::item:selected {{
    background-color: {c['bg.selected']};
    color: {c['text.primary']};
}}
QTreeView::branch, QTreeWidget::branch {{
    background: transparent;
}}
QTreeView::branch:has-children:!has-siblings:closed,
QTreeView::branch:closed:has-children:has-siblings {{
    border-image: none;
}}
QTreeView::branch:open:has-children:!has-siblings,
QTreeView::branch:open:has-children:has-siblings  {{
    border-image: none;
}}

/* ── Paper list (center) ──────────────────────────────────── */
#PaperList {{
    background-color: {c['bg.app']};
    border: none;
    outline: 0;
    color: {c['text.primary']};
}}
#PaperList::item {{
    padding: 8px 12px;
    border-bottom: 1px solid {c['border.subtle']};
}}
#PaperList::item:hover {{
    background-color: {c['bg.hover']};
}}
#PaperList::item:selected {{
    background-color: {c['bg.selected']};
    color: {c['text.primary']};
}}
QHeaderView::section {{
    background-color: {c['bg.panel']};
    color: {c['text.secondary']};
    padding: 8px 12px;
    border: none;
    border-bottom: 1px solid {c['border.subtle']};
    font-weight: {FONT['weight.medium']};
    font-size: {FONT['size.sm']}px;
}}

/* ── Detail panel cards ───────────────────────────────────── */
QFrame.Card {{
    background-color: {c['bg.elevated']};
    border: 1px solid {c['border.subtle']};
    border-radius: {RADIUS['lg']}px;
}}
QLabel.CardTitle {{
    color: {c['text.secondary']};
    font-size: {FONT['size.sm']}px;
    font-weight: {FONT['weight.medium']};
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
QLabel.FieldLabel {{
    color: {c['text.muted']};
    font-size: {FONT['size.sm']}px;
}}
QLabel.FieldValue {{
    color: {c['text.primary']};
    font-size: {FONT['size.md']}px;
}}
QLabel.FieldValueStub {{
    color: {c['text.muted']};
    font-size: {FONT['size.md']}px;
    font-style: italic;
}}
QLabel.StubBanner {{
    background-color: {c['accent.muted']};
    color: {c['accent.hover']};
    padding: 8px 12px;
    border-radius: {RADIUS['md']}px;
    font-size: {FONT['size.sm']}px;
}}

/* ── Buttons ──────────────────────────────────────────────── */
QPushButton {{
    background-color: {c['bg.elevated']};
    border: 1px solid {c['border.default']};
    border-radius: {RADIUS['md']}px;
    padding: 7px 14px;
    color: {c['text.primary']};
    font-weight: {FONT['weight.medium']};
}}
QPushButton:hover {{
    background-color: {c['bg.hover']};
    border-color: {c['border.strong']};
}}
QPushButton:pressed {{
    background-color: {c['bg.selected']};
}}
QPushButton:disabled {{
    color: {c['text.muted']};
    background-color: {c['bg.panel']};
    border-color: {c['border.subtle']};
}}
QPushButton.Primary {{
    background-color: {c['accent.primary']};
    border: 1px solid {c['accent.primary']};
    color: {c['text.inverse']};
}}
QPushButton.Primary:hover {{
    background-color: {c['accent.hover']};
    border-color: {c['accent.hover']};
}}
QPushButton.Primary:disabled {{
    background-color: {c['accent.muted']};
    color: {c['text.muted']};
    border-color: {c['accent.muted']};
}}

/* ── Status badge ─────────────────────────────────────────── */
QLabel#StatusBadge {{
    padding: 2px 8px;
    border-radius: {RADIUS['sm']}px;
    font-size: {FONT['size.xs']}px;
    font-weight: {FONT['weight.medium']};
}}
QLabel#StatusBadge[kind="ok"], QLabel#StatusBadge[kind="processed"] {{
    background-color: rgba(74, 222, 128, 0.15);
    color: {c['status.ok']};
}}
QLabel#StatusBadge[kind="pending"] {{
    background-color: rgba(107, 112, 128, 0.18);
    color: {c['status.pending']};
}}
QLabel#StatusBadge[kind="failed"] {{
    background-color: rgba(248, 113, 113, 0.15);
    color: {c['status.error']};
}}
QLabel#StatusBadge[kind="review"], QLabel#StatusBadge[kind="needs_review"] {{
    background-color: rgba(251, 191, 36, 0.15);
    color: {c['status.warn']};
}}
QLabel#StatusBadge[kind="info"] {{
    background-color: rgba(96, 165, 250, 0.15);
    color: {c['status.info']};
}}

/* ── Status bar (bottom) ──────────────────────────────────── */
#StatusBar {{
    background-color: {c['bg.panel']};
    border-top: 1px solid {c['border.subtle']};
    min-height: {LAYOUT['statusbar.height']}px;
    max-height: {LAYOUT['statusbar.height']}px;
    color: {c['text.muted']};
    font-size: {FONT['size.xs']}px;
}}
#StatusBar QLabel {{
    color: {c['text.muted']};
    padding: 0 10px;
}}

/* ── Splitter handle ──────────────────────────────────────── */
QSplitter::handle {{
    background-color: {c['border.subtle']};
    width: 1px;
}}
QSplitter::handle:hover {{
    background-color: {c['border.strong']};
}}
"""
