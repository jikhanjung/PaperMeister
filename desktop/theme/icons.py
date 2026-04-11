"""SVG icon loader with runtime color tinting.

Icons live under `desktop/theme/icons/*.svg` and use `stroke="currentColor"`.
This module substitutes the literal `currentColor` with a concrete color
before handing the bytes to QSvgRenderer, letting us build multi-state
QIcons (normal/checked/hover) from a single source file.
"""
from pathlib import Path

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from .tokens import COLORS_DARK

ICONS_DIR = Path(__file__).parent / 'icons'


def _render_svg(name: str, color: str, size: int) -> QPixmap:
    svg_path = ICONS_DIR / f'{name}.svg'
    svg_text = svg_path.read_text(encoding='utf-8').replace('currentColor', color)
    renderer = QSvgRenderer(QByteArray(svg_text.encode('utf-8')))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    return pixmap


def rail_icon(name: str, size: int = 20) -> QIcon:
    """Build a QIcon with three tint states for the left rail.

    - Off (not checked / idle): muted secondary text color
    - On  (checked / active):   accent color
    - Active (hover):           primary text color
    """
    icon = QIcon()
    icon.addPixmap(
        _render_svg(name, COLORS_DARK['text.secondary'], size),
        QIcon.Mode.Normal, QIcon.State.Off,
    )
    icon.addPixmap(
        _render_svg(name, COLORS_DARK['accent.primary'], size),
        QIcon.Mode.Normal, QIcon.State.On,
    )
    icon.addPixmap(
        _render_svg(name, COLORS_DARK['text.primary'], size),
        QIcon.Mode.Active, QIcon.State.Off,
    )
    return icon
