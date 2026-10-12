"""Dialogo de visualizacao ampliada (lupa) de uma pagina ou arquivo."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
)


class PreviewDialog(QDialog):
    """Mostra um pixmap em tamanho grande; Esc ou Fechar encerra."""

    def __init__(self, pixmap: QPixmap, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)

        image = QLabel()
        image.setPixmap(pixmap)
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)

        scroll = QScrollArea()
        scroll.setWidget(image)
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)

        close_btn = QPushButton("Fechar")
        close_btn.setObjectName("SecondaryButton")
        close_btn.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(12, 8, 12, 8)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)
        layout.addLayout(btn_row)

        self.resize(
            min(pixmap.width() + 40, 1100),
            min(pixmap.height() + 80, 900),
        )
