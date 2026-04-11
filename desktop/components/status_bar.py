"""Bottom status bar showing corpus counts and background task state."""
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget


class StatusBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('StatusBar')
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(0)

        self.counts_label = QLabel('—')
        layout.addWidget(self.counts_label)
        layout.addStretch(1)

        self.task_label = QLabel('Idle')
        layout.addWidget(self.task_label)

    def set_counts(self, total: int, pending: int, review: int):
        self.counts_label.setText(
            f'{total:,} papers  ·  {pending:,} pending  ·  {review:,} needs review'
        )

    def set_task(self, text: str):
        self.task_label.setText(text)
