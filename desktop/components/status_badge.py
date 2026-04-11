"""Small colored status pill used in paper lists and detail panels."""
from PyQt6.QtWidgets import QLabel

_LABELS = {
    'pending':      'Pending',
    'processed':    'Processed',
    'failed':       'Failed',
    'needs_review': 'Review',
    'review':       'Review',
    'ok':           'OK',
    'info':         'Info',
}


class StatusBadge(QLabel):
    """QLabel styled as a pill. `kind` drives the QSS property selector."""

    def __init__(self, kind: str, text: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName('StatusBadge')
        self.set_kind(kind, text)

    def set_kind(self, kind: str, text: str | None = None):
        self.setProperty('kind', kind)
        self.setText(text if text is not None else _LABELS.get(kind, kind.title()))
        # Force style re-evaluation when dynamic property changes.
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)
