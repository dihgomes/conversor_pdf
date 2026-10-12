"""Tela generica de uma ferramenta: selecao de arquivos + processamento."""
from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import Qt, QSize, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.registry import OUTPUT_IS_DIR, Tool
from app.ui.widgets.drop_zone import DropZone
from app.ui.widgets.preview import PreviewDialog
from app.ui.widgets.thumbnails import file_preview, make_thumbnail
from app.workers.worker import Worker


class ToolPage(QWidget):
    back_requested = Signal()

    def __init__(self, tool: Tool, parent=None) -> None:
        super().__init__(parent)
        self.tool = tool
        self._output_path: str | None = None

        back_btn = QPushButton("  Voltar")
        back_btn.setIcon(qta.icon("fa5s.arrow-left", color="#333333"))
        back_btn.setObjectName("LinkButton")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(self.back_requested)

        title = QLabel(tool.title)
        title.setObjectName("PageTitle")
        desc = QLabel(tool.description)
        desc.setObjectName("PageDesc")

        self.setAcceptDrops(True)

        self.file_list = QListWidget()
        self.file_list.setObjectName("FileList")
        self.file_list.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.file_list.viewport().setAcceptDrops(False)
        self.file_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.file_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.file_list.setMovement(QListWidget.Movement.Static)
        self.file_list.setWrapping(True)
        self.file_list.setUniformItemSizes(True)
        self.file_list.setWordWrap(True)
        self.file_list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.file_list.setIconSize(QSize(120, 160))
        self.file_list.setGridSize(QSize(160, 215))
        self.file_list.setSpacing(10)
        self.file_list.itemDoubleClicked.connect(self._preview_item)

        add_btn = QPushButton("Adicionar arquivos")
        add_btn.setObjectName("SecondaryButton")
        add_btn.clicked.connect(self._add_files)

        clear_btn = QPushButton("Limpar")
        clear_btn.setObjectName("SecondaryButton")
        clear_btn.clicked.connect(self._clear)

        self.run_btn = QPushButton("Processar")
        self.run_btn.setObjectName("PrimaryButton")
        self.run_btn.clicked.connect(self._run)

        self.pages_input: QLineEdit | None = None
        if tool.page_range:
            self.pages_input = QLineEdit()
            self.pages_input.setObjectName("RangeInput")
            self.pages_input.setPlaceholderText(
                "Paginas — ex.: 1-3, 5, 8-10"
            )

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminado
        self.progress.setVisible(False)

        self.status = QLabel("")
        self.status.setObjectName("StatusLabel")

        self.open_btn = QPushButton("Abrir pasta de destino")
        self.open_btn.setObjectName("SecondaryButton")
        self.open_btn.setVisible(False)
        self.open_btn.clicked.connect(self._open_output_folder)

        drop_zone = DropZone()
        drop_zone.files_dropped.connect(self._add_paths)

        files_row = QHBoxLayout()
        files_row.addWidget(add_btn)
        files_row.addWidget(clear_btn)
        files_row.addStretch()
        files_row.addWidget(self.run_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 20, 28, 24)
        layout.addWidget(back_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addSpacing(10)
        layout.addWidget(drop_zone)
        layout.addLayout(files_row)
        layout.addWidget(self.file_list)
        if self.pages_input is not None:
            layout.addWidget(self.pages_input)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addWidget(self.open_btn, alignment=Qt.AlignmentFlag.AlignRight)

    # ---------------------------------------------------------- arquivos

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        files = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if files:
            self._add_paths(files)

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Selecionar arquivos", "", self.tool.file_filter
        )
        self._add_paths(paths)

    def _add_paths(self, paths: list[str]) -> None:
        existing = self._files()
        for path in paths:
            if path not in existing:
                if not self.tool.multiple_files and self.file_list.count() >= 1:
                    self.file_list.clear()
                    existing = []
                item = QListWidgetItem(Path(path).name)
                item.setData(Qt.ItemDataRole.UserRole, path)
                item.setToolTip(f"{path}\nDuplo clique para ampliar")
                item.setIcon(make_thumbnail(path))
                self.file_list.addItem(item)
                existing.append(path)
        self.open_btn.setVisible(False)
        self.status.setText("")

    def _files(self) -> list[str]:
        return [
            self.file_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.file_list.count())
        ]

    def _clear(self) -> None:
        self.file_list.clear()
        self.status.setText("")
        self.open_btn.setVisible(False)

    def _preview_item(self, item: QListWidgetItem) -> None:
        """Abre a visualizacao ampliada do arquivo (lupa, via duplo clique)."""
        path = item.data(Qt.ItemDataRole.UserRole)
        try:
            pixmap = file_preview(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self, self.tool.title, f"Nao foi possivel visualizar: {exc}"
            )
            return
        PreviewDialog(pixmap, Path(path).name, self).exec()

    # ------------------------------------------------------ processamento

    def _pick_output(self) -> str | None:
        if self.tool.output_mode == OUTPUT_IS_DIR:
            return QFileDialog.getExistingDirectory(
                self, "Escolher pasta de destino"
            )
        default = str(Path.home() / "Documents" / f"saida{self.tool.output_suffix}")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar resultado",
            default,
            f"Arquivos (*{self.tool.output_suffix})",
        )
        return path or None

    def _options(self) -> dict:
        options: dict = {}
        if self.pages_input is not None:
            options["pages"] = self.pages_input.text().strip()
        return options

    def _run(self) -> None:
        files = self._files()
        if not files:
            QMessageBox.warning(self, self.tool.title, "Adicione arquivos primeiro.")
            return

        output = self._pick_output()
        if not output:
            return
        self._output_path = output
        options = self._options()

        self.run_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.open_btn.setVisible(False)
        self.status.setText("Processando...")

        if self.tool.run_on_main_thread:
            try:
                self._on_finished(
                    self.tool.handler(files, output, options)
                )
            except Exception as exc:  # noqa: BLE001
                self._on_error(str(exc))
            return

        worker = Worker(self.tool.handler, files, output, options)
        worker.signals.finished.connect(self._on_finished)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_finished(self, result) -> None:
        self.run_btn.setEnabled(True)
        self.progress.setVisible(False)
        count = len(result) if isinstance(result, list) else 1
        self.status.setText(f"Concluido: {count} arquivo(s) gerado(s).")
        self.open_btn.setVisible(True)

    def _on_error(self, message: str) -> None:
        self.run_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.status.setText("")
        QMessageBox.critical(self, self.tool.title, f"Erro: {message}")

    def _open_output_folder(self) -> None:
        if not self._output_path:
            return
        path = Path(self._output_path)
        folder = path if path.is_dir() else path.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
