"""Pagina da ferramenta Organizar PDF.

Permite reordenar (arrastar ou botoes), girar e remover paginas de um
ou mais PDFs, depois salvar o resultado em um novo arquivo.
"""
from pathlib import Path

import pymupdf
import qtawesome as qta
from PySide6.QtCore import Qt, QSize, QThreadPool, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core import auto_sort
from app.registry import PDF_FILTER, Tool
from app.ui.widgets.drop_zone import DropZone
from app.ui.widgets.preview import PreviewDialog
from app.ui.widgets.thumbnails import page_pixmap, page_thumbnail
from app.workers.worker import Worker


class PageGrid(QListWidget):
    """QListWidget em modo icone com reordenacao manual no drop.

    O InternalMove nativo do Qt e inconsistente no IconMode: o drop pode
    ser descartado dependendo da posicao/versao. Aqui recolocamos os
    itens arrastados manualmente na posicao alvo.
    """

    _INTERNAL_MIME = "application/x-qabstractitemmodeldatalist"

    # O Qt so aceita o drop sobre um item valido; nos vao entre as celulas
    # do grid ele rejeita e mostra o cursor de "proibido". Aceitamos o drag
    # interno em qualquer ponto e calculamos o destino manualmente no drop.
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(self._INTERNAL_MIME):
            event.acceptProposedAction()
        elif event.mimeData().hasUrls():
            event.ignore()  # sobe p/ o OrganizePage (arquivos externos)
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(self._INTERNAL_MIME):
            event.acceptProposedAction()
        elif event.mimeData().hasUrls():
            event.ignore()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        rows = sorted(index.row() for index in self.selectedIndexes())
        if not rows or not event.mimeData().hasFormat(self._INTERNAL_MIME):
            event.ignore()
            return

        # Usa a direcao do arraste: alvo depois da posicao original insere
        # DEPOIS dele; alvo antes insere ANTES. Assim a celula inteira e um
        # alvo valido, sem "metade morta" que nao muda nada.
        pos = event.position().toPoint()
        target = self.indexAt(pos)
        if target.isValid():
            t = target.row()
            if t > rows[-1]:
                target_row = t + 1
            else:
                target_row = t
        else:
            target_row = self.count()

        self._reinsert(rows, target_row)
        # Reporta Copy propositalmente: se o drop for Move, o Qt remove os
        # itens arrastados da origem apos o dropEvent (limpeza do InternalMove)
        # e apagaria os itens que ja reinserimos manualmente.
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def _reinsert(self, rows: list[int], target_row: int) -> None:
        items = [self.takeItem(row) for row in reversed(rows)]
        items.reverse()
        insert_at = target_row - sum(r < target_row for r in rows)
        for item in items:
            self.insertItem(insert_at, item)
            item.setSelected(True)
            insert_at += 1


class OrganizePage(QWidget):
    back_requested = Signal()

    def __init__(self, tool: Tool, parent=None) -> None:
        super().__init__(parent)
        self.tool = tool
        self.setAcceptDrops(True)

        self._docs: list["pymupdf.Document"] = []
        self._output_path: str | None = None
        self._rotations: dict[tuple[int, int], int] = {}  # (doc, pag) -> graus
        # Enquanto o worker de OCR roda, nenhuma operacao que toca nos
        # Document pode acontecer (pymupdf nao e thread-safe e fechar um
        # doc em uso derruba o worker). O token de geracao descarta o
        # resultado se a grade mudou desde o disparo.
        self._sort_running = False
        self._sort_gen = 0
        self._sort_docs: list["pymupdf.Document"] = []
        self._loaded: set[str] = set()  # evita abrir o mesmo PDF 2x

        back_btn = QPushButton("  Voltar")
        back_btn.setIcon(qta.icon("fa5s.arrow-left", color="#333333"))
        back_btn.setObjectName("LinkButton")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(self.back_requested)

        title = QLabel(tool.title)
        title.setObjectName("PageTitle")
        desc = QLabel(tool.description)
        desc.setObjectName("PageDesc")

        # ---- estado inicial: escolher o(s) PDF(s) ----
        pick_btn = QPushButton("Selecionar PDFs")
        pick_btn.setObjectName("PrimaryButton")
        pick_btn.clicked.connect(self._pick_files)

        drop = DropZone()
        drop.files_dropped.connect(self._on_dropped)

        self.picker = QWidget()
        pick_layout = QVBoxLayout(self.picker)
        pick_layout.setContentsMargins(0, 0, 0, 0)
        pick_layout.addWidget(drop)
        pick_layout.addWidget(pick_btn, alignment=Qt.AlignmentFlag.AlignRight)
        pick_layout.addStretch()

        # ---- estado carregado: grade de paginas ----
        self.pages = PageGrid()
        self.pages.setObjectName("PageGrid")
        self.pages.setViewMode(QListWidget.ViewMode.IconMode)
        self.pages.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.pages.setDefaultDropAction(Qt.DropAction.MoveAction)
        # MultiSelection: cada clique alterna a selecao do item, sem
        # precisar segurar Ctrl. O Qt adia a desselecao para o release,
        # entao arrastar itens ja selecionados continua funcionando.
        self.pages.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection
        )
        self.pages.setMovement(QListWidget.Movement.Snap)
        self.pages.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.pages.setWrapping(True)
        self.pages.setUniformItemSizes(True)
        self.pages.setWordWrap(True)
        self.pages.setIconSize(QSize(120, 160))
        self.pages.setGridSize(QSize(160, 210))
        self.pages.setSpacing(10)
        self.pages.itemDoubleClicked.connect(self._preview_item)

        self.change_btn = QPushButton("Recomecar")
        self.change_btn.setObjectName("SecondaryButton")
        self.change_btn.clicked.connect(self._reset)

        self.add_btn = QPushButton("Adicionar PDF")
        self.add_btn.setObjectName("SecondaryButton")
        self.add_btn.clicked.connect(self._pick_files)

        left_btn = QPushButton("←")
        left_btn.setObjectName("SecondaryButton")
        left_btn.clicked.connect(lambda: self._move_current(-1))

        right_btn = QPushButton("→")
        right_btn.setObjectName("SecondaryButton")
        right_btn.clicked.connect(lambda: self._move_current(1))

        self.rotate_btn = QPushButton("Girar 90°")
        self.rotate_btn.setObjectName("SecondaryButton")
        self.rotate_btn.clicked.connect(self._rotate_selected)

        remove_btn = QPushButton("Remover selecionadas")
        remove_btn.setObjectName("SecondaryButton")
        remove_btn.clicked.connect(self._remove_selected)

        self.orto_btn = QPushButton("Ortopedia")
        self.orto_btn.setObjectName("SecondaryButton")
        self.orto_btn.setIcon(qta.icon("fa5s.x-ray", color="#16a34a"))
        self.orto_btn.setToolTip(
            "Ordena as paginas no padrao do dossie de ortopedia (OCR)"
        )
        self.orto_btn.clicked.connect(self._auto_sort)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminado
        self.progress.setVisible(False)

        self.save_btn = QPushButton("Salvar PDF")
        self.save_btn.setObjectName("PrimaryButton")
        self.save_btn.clicked.connect(self._save)

        buttons = QHBoxLayout()
        buttons.addWidget(self.change_btn)
        buttons.addWidget(self.add_btn)
        buttons.addWidget(left_btn)
        buttons.addWidget(right_btn)
        buttons.addWidget(self.rotate_btn)
        buttons.addWidget(remove_btn)
        buttons.addWidget(self.orto_btn)
        buttons.addStretch()
        buttons.addWidget(self.save_btn)

        self.editor = QWidget()
        editor_layout = QVBoxLayout(self.editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.addLayout(buttons)
        editor_layout.addWidget(self.progress)
        editor_layout.addWidget(self.pages)
        self.editor.setVisible(False)

        # ---- status ----
        self.status = QLabel("")
        self.status.setObjectName("StatusLabel")

        self.open_btn = QPushButton("Abrir pasta de destino")
        self.open_btn.setObjectName("SecondaryButton")
        self.open_btn.setVisible(False)
        self.open_btn.clicked.connect(self._open_output_folder)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 20, 28, 24)
        layout.addWidget(back_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addSpacing(10)
        layout.addWidget(self.picker)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self.status)
        layout.addWidget(self.open_btn, alignment=Qt.AlignmentFlag.AlignRight)

    # ---------------------------------------------------- arrastar/soltar

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        self._on_dropped(
            [
                url.toLocalFile()
                for url in event.mimeData().urls()
                if url.isLocalFile()
            ]
        )

    def _on_dropped(self, files: list[str]) -> None:
        pdfs = [f for f in files if f.lower().endswith(".pdf")]
        if pdfs:
            self._load(pdfs)

    # ------------------------------------------------------------ arquivo

    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Selecionar PDFs", "", PDF_FILTER
        )
        if paths:
            self._load(paths)

    def _load(self, paths: list[str]) -> None:
        if self._sort_running:
            self.status.setText(
                "Aguarde a ordenacao terminar para adicionar arquivos."
            )
            return
        for path in paths:
            real = str(Path(path).resolve())
            if real in self._loaded:
                continue  # mesmo arquivo ja esta na grade
            try:
                doc = pymupdf.open(path)
            except Exception as exc:
                QMessageBox.critical(
                    self, self.tool.title, f"Erro ao abrir {Path(path).name}: {exc}"
                )
                continue
            self._loaded.add(real)
            doc_index = len(self._docs)
            self._docs.append(doc)
            for i in range(doc.page_count):
                item = QListWidgetItem(f"Pag. {i + 1}")
                item.setData(Qt.ItemDataRole.UserRole, (doc_index, i))
                item.setToolTip(
                    f"{Path(path).name} — pag. {i + 1}\nDuplo clique para ampliar"
                )
                try:
                    item.setIcon(page_thumbnail(doc, i))
                except Exception:  # noqa: BLE001 - pagina danificada nao
                    pass                # deve abortar a carga do resto
                self.pages.addItem(item)

        if not self._docs:
            return
        self.picker.setVisible(False)
        self.editor.setVisible(True)
        self.open_btn.setVisible(False)
        self._update_status()

    def _reset(self) -> None:
        if self._sort_running:
            self.status.setText(
                "Aguarde a ordenacao terminar para recomecar."
            )
            return
        self._sort_gen += 1  # invalida um resultado tardio, se houver
        self._loaded.clear()
        self._close_docs()
        self.pages.clear()
        self._rotations = {}
        self.editor.setVisible(False)
        self.picker.setVisible(True)
        self.status.setText("")
        self.open_btn.setVisible(False)

    def _close_docs(self) -> None:
        for doc in self._docs:
            doc.close()
        self._docs = []

    def _update_status(self) -> None:
        self.status.setText(
            f"{len(self._docs)} arquivo(s), {self.pages.count()} paginas"
            " — arraste ou use ← → para reordenar"
        )

    def load_for_review(self, path: str, positions: list[int]) -> None:
        """Abre um dossie vindo do Organizar em Lote e destaca com borda
        vermelha as paginas suspeitas de ser de outro paciente
        (posicoes 1-based no PDF final, = linhas da grade)."""
        if self._sort_running:
            return
        self._reset()
        self._load([path])
        marked = []
        for pos in positions:
            item = self.pages.item(pos - 1)
            if item is None:
                continue
            pix = item.icon().pixmap(self.pages.iconSize())
            if pix.isNull():
                pix = QPixmap(self.pages.iconSize())
                pix.fill(Qt.GlobalColor.white)
            painter = QPainter(pix)
            painter.setPen(QPen(QColor("#dc2626"), 4))
            painter.drawRect(pix.rect().adjusted(2, 2, -3, -3))
            painter.end()
            item.setIcon(QIcon(pix))
            item.setBackground(QColor("#fee2e2"))
            marked.append(pos)
        if marked:
            first = self.pages.item(min(marked) - 1)
            self.pages.scrollToItem(first)
            first.setSelected(True)
            self.status.setText(
                f"REVISAO: pagina(s) {', '.join(map(str, marked))} "
                "marcada(s) em vermelho — confira se sao de outro "
                "paciente."
            )

    # ------------------------------------------------------------- edicao

    def _order(self) -> list[tuple[int, int]]:
        return [
            self.pages.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.pages.count())
        ]

    def _move_current(self, direction: int) -> None:
        row = self.pages.currentRow()
        target = row + direction
        if row < 0 or not 0 <= target < self.pages.count():
            return
        item = self.pages.takeItem(row)
        self.pages.insertItem(target, item)
        self.pages.setCurrentRow(target)

    def _rotate_selected(self) -> None:
        items = self.pages.selectedItems()
        if not items:
            self.status.setText("Selecione as paginas para girar.")
            return
        for item in items:
            key = item.data(Qt.ItemDataRole.UserRole)
            self._rotations[key] = (self._rotations.get(key, 0) + 90) % 360
            doc_index, page_index = key
            item.setIcon(
                page_thumbnail(
                    self._docs[doc_index], page_index, self._rotations[key]
                )
            )

    def _remove_selected(self) -> None:
        for item in self.pages.selectedItems():
            self.pages.takeItem(self.pages.row(item))
        self._update_status()

    def _preview_item(self, item: QListWidgetItem) -> None:
        """Abre a pagina em tamanho grande (lupa, via duplo clique)."""
        if self._sort_running:
            self.status.setText(
                "Aguarde a ordenacao terminar para ampliar a pagina."
            )
            return
        doc_index, page_index = item.data(Qt.ItemDataRole.UserRole)
        rotation = self._rotations.get((doc_index, page_index), 0)
        pixmap = page_pixmap(self._docs[doc_index], page_index, rotation)
        title = item.toolTip().split("\n")[0]
        PreviewDialog(pixmap, title, self).exec()

    # ------------------------------------------------- ordenacao automatica

    def _set_sort_ui(self, running: bool) -> None:
        """Trava/destrava as acoes que tocam nos Document durante o OCR."""
        self._sort_running = running
        self.orto_btn.setEnabled(not running)
        self.change_btn.setEnabled(not running)
        self.add_btn.setEnabled(not running)
        self.rotate_btn.setEnabled(not running)
        self.save_btn.setEnabled(not running)
        self.progress.setVisible(running)

    def _auto_sort(self) -> None:
        """Roda o classificador (OCR) em background e reordena a grade."""
        if self.pages.count() == 0 or self._sort_running:
            return
        self._sort_gen += 1
        gen = self._sort_gen
        # Snapshot: o worker itera esta lista; a grade pode mudar, mas
        # os Document nao podem — por isso a UI fica travada no sort.
        self._sort_docs = list(self._docs)
        self._set_sort_ui(True)
        self.status.setText(
            "Identificando paginas... pode levar ~1 min por conta do OCR."
        )
        worker = Worker(auto_sort.suggest_order, self._sort_docs)
        worker.signals.finished.connect(
            lambda order: self._on_sorted(order, gen)
        )
        worker.signals.error.connect(
            lambda msg: self._on_sort_error(msg, gen)
        )
        QThreadPool.globalInstance().start(worker)

    def _on_sorted(self, order: list[tuple[int, int]], gen: int) -> None:
        self._set_sort_ui(False)
        if gen != self._sort_gen:
            return  # resultado de um sort antigo — a grade ja mudou
        items = {}
        while self.pages.count():
            item = self.pages.takeItem(0)
            items[item.data(Qt.ItemDataRole.UserRole)] = item
        for pos, key in enumerate(order):
            item = items.pop(key, None)
            if item is not None:
                self.pages.insertItem(pos, item)
        for item in items.values():  # seguranca: sobra nao pode sumir
            self.pages.addItem(item)
        msg = "Paginas ordenadas no padrao Ortopedia — revise antes de salvar."
        try:
            classes = auto_sort.classify_documents(self._sort_docs)
            anuladas = sum(1 for c in classes.values() if c == "anulado")
            if anuladas:
                msg = (
                    f"{anuladas} pagina(s) anulada(s) (risco X) "
                    "foram para o fim da grade — confira antes de salvar."
                )
        except Exception:  # noqa: BLE001 - aviso extra nao pode quebrar
            pass
        self.status.setText(msg)

    def _on_sort_error(self, message: str, gen: int) -> None:
        self._set_sort_ui(False)
        if gen != self._sort_gen:
            return
        self._update_status()
        QMessageBox.critical(
            self, self.tool.title, f"Erro na ordenacao automatica: {message}"
        )

    # -------------------------------------------------------------- salvar

    def _save(self) -> None:
        if self.pages.count() == 0:
            QMessageBox.warning(
                self, self.tool.title, "Nao ha paginas para salvar."
            )
            return

        output, _ = QFileDialog.getSaveFileName(
            self, "Salvar PDF",
            str(Path.home() / "Documents" / "organizado.pdf"),
            "Arquivos PDF (*.pdf)",
        )
        if not output:
            return

        order = self._order()
        try:
            with pymupdf.open() as out_doc:
                for doc_index, page_index in order:
                    out_doc.insert_pdf(
                        self._docs[doc_index],
                        from_page=page_index,
                        to_page=page_index,
                    )
                for pos, key in enumerate(order):
                    delta = self._rotations.get(key, 0)
                    if delta:
                        page = out_doc.load_page(pos)
                        page.set_rotation((page.rotation + delta) % 360)
                out_doc.save(output, garbage=4, deflate=True)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self, self.tool.title, f"Erro ao salvar: {exc}"
            )
            return

        self._output_path = output
        self.status.setText("Concluido: 1 arquivo(s) gerado(s).")
        self.open_btn.setVisible(True)

    def _open_output_folder(self) -> None:
        if self._output_path:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(Path(self._output_path).parent))
            )
