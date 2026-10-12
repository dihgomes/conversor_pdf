"""Card de ferramenta exibido na tela inicial (estilo iLovePDF)."""
import qtawesome as qta
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from app.registry import Tool
from app.ui import theme


class ToolCard(QFrame):
    clicked = Signal(str)

    def __init__(self, tool: Tool, parent=None) -> None:
        super().__init__(parent)
        self.tool = tool
        self.setObjectName("ToolCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(220, 150)

        icon_label = QLabel()
        icon_label.setPixmap(
            qta.icon(tool.icon, color=theme.PRIMARY).pixmap(38, 38)
        )
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel(tool.title)
        title.setObjectName("ToolCardTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        desc = QLabel(tool.description)
        desc.setObjectName("ToolCardDesc")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(icon_label)
        layout.addWidget(title)
        layout.addWidget(desc)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.tool.id)
        super().mousePressEvent(event)
