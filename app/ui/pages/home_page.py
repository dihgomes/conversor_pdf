"""Tela inicial com o grid de ferramentas agrupadas por categoria."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.registry import TOOLS, Tool
from app.ui.widgets.tool_card import ToolCard

COLUMNS = 4


def _categories() -> list[tuple[str, list[Tool]]]:
    """Agrupa as ferramentas por categoria na ordem de aparicao."""
    groups: dict[str, list[Tool]] = {}
    for tool in TOOLS:
        groups.setdefault(tool.category, []).append(tool)
    return list(groups.items())


class HomePage(QWidget):
    tool_selected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        header = QLabel("Todas as ferramentas de PDF")
        header.setObjectName("HomeHeader")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel(
            "Junte, divida, comprima e converta PDFs em poucos cliques."
        )
        subtitle.setObjectName("HomeSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        content = QWidget()
        inner = QVBoxLayout(content)
        inner.setContentsMargins(36, 28, 36, 28)
        inner.addWidget(header)
        inner.addWidget(subtitle)
        inner.addSpacing(24)

        for category, tools in _categories():
            cat_label = QLabel(category)
            cat_label.setObjectName("CategoryHeader")
            inner.addWidget(cat_label)
            inner.addSpacing(8)

            grid = QGridLayout()
            grid.setSpacing(14)
            grid.setAlignment(Qt.AlignmentFlag.AlignLeft)
            for index, tool in enumerate(tools):
                card = ToolCard(tool)
                card.clicked.connect(self.tool_selected)
                grid.addWidget(card, index // COLUMNS, index % COLUMNS)
            inner.addLayout(grid)
            inner.addSpacing(18)

        inner.addStretch()

        scroll = QScrollArea()
        scroll.setObjectName("HomeScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)
