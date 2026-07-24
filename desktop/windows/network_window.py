"""Citation-network graph view — an ego network around a selected paper.

Held->held citation edges (reference.resolved_paper_id) form a graph; a global
view of thousands of papers is a hairball, so this shows the 1–2-hop ego network
around one paper, force-directed. Double-click a node to walk the graph
(re-center on it); "Open in list" reveals the centered paper in the main window.
"""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QComboBox,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_BG = QColor('#16181d')
_EDGE = QColor('#4a4f5a')
_NODE = QColor('#2a2d34')            # 2-hop / not directly linked to center
_NODE_CENTER = QColor('#3a8ee6')     # the focused paper
_NODE_CITEDBY = QColor('#4ade80')    # green — papers that CITE the center
_NODE_CITES = QColor('#fbbf24')      # amber — papers the center CITES
_NODE_BOTH = QColor('#22d3ee')       # cyan — mutual citation
_NODE_BORDER = QColor('#5a6069')
_TEXT = QColor('#d7dae0')
_R = 9          # neighbour node radius
_RC = 14        # center node radius


def spring_layout(node_ids, edges, center_id, width=900, height=600, iterations=120):
    """Force-directed (Fruchterman–Reingold) layout with the center pinned.

    Pure function → returns {node_id: (x, y)}. Deterministic (circle seed, no RNG)
    so the same graph always lays out the same way.
    """
    ids = sorted(node_ids)
    n = len(ids)
    cx, cy = width / 2, height / 2
    if n == 0:
        return {}
    if n == 1:
        return {ids[0]: (cx, cy)}

    pos = {}
    radius = min(width, height) * 0.35
    for i, nid in enumerate(ids):
        ang = 2 * math.pi * i / n
        pos[nid] = [cx + radius * math.cos(ang), cy + radius * math.sin(ang)]
    pos[center_id] = [cx, cy]

    k = math.sqrt(width * height / n) * 0.6
    temp = width * 0.1
    for _ in range(iterations):
        disp = {nid: [0.0, 0.0] for nid in ids}
        for a in range(n):
            for b in range(a + 1, n):
                va, vb = ids[a], ids[b]
                dx = pos[va][0] - pos[vb][0]
                dy = pos[va][1] - pos[vb][1]
                d = math.hypot(dx, dy) or 0.01
                f = k * k / d
                ux, uy = dx / d, dy / d
                disp[va][0] += ux * f
                disp[va][1] += uy * f
                disp[vb][0] -= ux * f
                disp[vb][1] -= uy * f
        for s, t in edges:
            if s == t or s not in pos or t not in pos:
                continue
            dx = pos[s][0] - pos[t][0]
            dy = pos[s][1] - pos[t][1]
            d = math.hypot(dx, dy) or 0.01
            f = d * d / k
            ux, uy = dx / d, dy / d
            disp[s][0] -= ux * f
            disp[s][1] -= uy * f
            disp[t][0] += ux * f
            disp[t][1] += uy * f
        for nid in ids:
            if nid == center_id:
                continue  # pinned
            dx, dy = disp[nid]
            d = math.hypot(dx, dy) or 0.01
            step = min(d, temp)
            pos[nid][0] = min(width - 20, max(20, pos[nid][0] + dx / d * step))
            pos[nid][1] = min(height - 20, max(20, pos[nid][1] + dy / d * step))
        temp *= 0.95
    return {nid: (pos[nid][0], pos[nid][1]) for nid in ids}


class _NetworkView(QGraphicsView):
    node_activated = pyqtSignal(int)   # double-clicked node's paper_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setBackgroundBrush(QBrush(_BG))
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def _node_at(self, viewpos):
        item = self.itemAt(viewpos)
        while item is not None and item.data(0) is None:
            item = item.parentItem()
        return None if item is None else int(item.data(0))

    def mousePressEvent(self, event):
        # Remember the node under the press so a plain click (not a pan-drag)
        # re-centers on release.
        self._press_pos = event.pos()
        self._press_pid = self._node_at(event.pos())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        pid = getattr(self, '_press_pid', None)
        moved = (event.pos() - getattr(self, '_press_pos', event.pos())).manhattanLength()
        if pid is not None and moved < 5 and self._node_at(event.pos()) == pid:
            self.node_activated.emit(pid)   # single click on a node → explore

    def render_graph(self, center_id, nodes, edges, pos):
        scene = self.scene()
        scene.clear()
        # edges first (under nodes), with an arrowhead at the cited end.
        pen = QPen(_EDGE, 1.2)
        for s, t in edges:
            if s not in pos or t not in pos:
                continue
            x1, y1 = pos[s]
            x2, y2 = pos[t]
            scene.addLine(x1, y1, x2, y2, pen)
            self._arrow(scene, x1, y1, x2, y2)
        # Classify each node by its direct relationship to the center so the
        # papers that CITE this one (incoming) are visually distinct from the
        # ones this paper cites (outgoing).
        cites = {d for s, d in edges if s == center_id}      # center -> d
        citedby = {s for s, d in edges if d == center_id}    # s -> center
        # nodes
        for pid, (x, y) in pos.items():
            info = nodes.get(pid)
            is_center = pid == center_id
            r = _RC if is_center else _R
            if is_center:
                fill = _NODE_CENTER
            elif pid in cites and pid in citedby:
                fill = _NODE_BOTH
            elif pid in citedby:
                fill = _NODE_CITEDBY
            elif pid in cites:
                fill = _NODE_CITES
            else:
                fill = _NODE
            ell = scene.addEllipse(
                QRectF(x - r, y - r, 2 * r, 2 * r),
                QPen(_NODE_BORDER, 1.5),
                QBrush(fill))
            ell.setData(0, pid)
            ell.setZValue(2)
            if info is not None:
                ell.setToolTip(info.title)
            label = scene.addText(info.label if info else str(pid))
            label.setDefaultTextColor(_TEXT)
            f = label.font()
            f.setPointSize(9 if is_center else 8)
            f.setBold(is_center)
            label.setFont(f)
            label.setData(0, pid)
            label.setZValue(3)
            label.setPos(x + r + 2, y - 9)
        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-40, -40, 40, 40))
        self.resetTransform()
        self.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _arrow(self, scene, x1, y1, x2, y2):
        dx, dy = x2 - x1, y2 - y1
        d = math.hypot(dx, dy) or 0.01
        ux, uy = dx / d, dy / d
        # place the tip just outside the target node
        tipx, tipy = x2 - ux * _R, y2 - uy * _R
        size = 7
        left = QPointF(tipx - ux * size - uy * size * 0.5,
                       tipy - uy * size + ux * size * 0.5)
        right = QPointF(tipx - ux * size + uy * size * 0.5,
                        tipy - uy * size - ux * size * 0.5)
        poly = QPolygonF([QPointF(tipx, tipy), left, right])
        scene.addPolygon(poly, QPen(_EDGE, 1), QBrush(_EDGE))


class NetworkWindow(QWidget):
    """Ego-network explorer for the held→held citation graph."""

    open_paper = pyqtSignal(int)   # "Open in list" → reveal in the main window

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Citation Network')
        self.setMinimumSize(900, 640)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Window)
        self._center = None
        self._history: list[int] = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.back_btn = QPushButton('◀ Back')
        self.back_btn.clicked.connect(self._go_back)
        self.back_btn.setEnabled(False)
        bar.addWidget(self.back_btn)

        self.title_label = QLabel('—')
        self.title_label.setStyleSheet('font-weight: bold;')
        bar.addWidget(self.title_label, 1)

        bar.addWidget(QLabel('Hops:'))
        self.hops = QComboBox()
        self.hops.addItems(['1', '2'])
        self.hops.currentTextChanged.connect(self._rerender)
        bar.addWidget(self.hops)

        self.open_btn = QPushButton('Open in list')
        self.open_btn.clicked.connect(
            lambda: self._center and self.open_paper.emit(self._center))
        bar.addWidget(self.open_btn)
        layout.addLayout(bar)

        self.view = _NetworkView()
        self.view.node_activated.connect(self._recenter)
        layout.addWidget(self.view, 1)

        self.status = QLabel('')
        self.status.setStyleSheet('color: #888; font-size: 11px;')
        layout.addWidget(self.status)

    # ── public ───────────────────────────────────────────────
    def show_ego(self, paper_id: int):
        if self._center is not None and self._center != paper_id:
            self._history.append(self._center)
        self._center = paper_id
        self.back_btn.setEnabled(bool(self._history))
        self._render_current()
        self.show()
        self.raise_()
        self.activateWindow()

    # ── internal ─────────────────────────────────────────────
    def _recenter(self, paper_id: int):
        if paper_id != self._center:
            self.show_ego(paper_id)

    def _go_back(self):
        if not self._history:
            return
        self._center = self._history.pop()
        self.back_btn.setEnabled(bool(self._history))
        self._render_current()

    def _rerender(self, *_):
        if self._center is not None:
            self._render_current()

    def _render_current(self):
        from desktop.services.paper_service import load_ego_network
        hops = int(self.hops.currentText())
        center, nodes, edges = load_ego_network(self._center, hops=hops)
        info = nodes.get(center)
        self.title_label.setText(info.title if info else f'Paper {center}')
        pos = spring_layout(set(nodes), edges, center)
        self.view.render_graph(center, nodes, edges, pos)
        n_cites = len({d for s, d in edges if s == center})     # center cites
        n_citedby = len({s for s, d in edges if d == center})   # cite the center
        self.status.setText(
            f'<span style="color:#4ade80">●</span> cites this ({n_citedby}) &nbsp; '
            f'<span style="color:#fbbf24">●</span> this cites ({n_cites}) &nbsp; '
            f'<span style="color:#22d3ee">●</span> both &nbsp; '
            f'<span style="color:#8a919c">●</span> 2-hop &nbsp;·&nbsp; '
            f'{len(nodes) - 1} papers, {len(edges)} edges within {hops} hop(s) '
            f'· click a node to re-center, drag to pan')
