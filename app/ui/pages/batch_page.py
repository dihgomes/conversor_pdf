"""Pagina Organizar em Lote (Ortopedia).

O usuario escolhe uma pasta raiz que contem uma subpasta por paciente;
o app junta os PDFs de cada subpasta, ordena as paginas no padrao do
dossie de ortopedia (OCR) e salva o resultado dentro da propria pasta
do paciente, um por um, sem intervenção manual.
"""
from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import QSettings, QSize, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices
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
from app.registry import Tool
from app.ui import theme
from app.ui.pages.settings_page import (
    KEY_NOTIFY,
    QSETTINGS_APP,
    QSETTINGS_ORG,
)
from app.workers.worker import Worker

_ICONS = {
    "pending": ("fa5s.circle", theme.TEXT_FAINT),
    "start": ("fa5s.sync-alt", theme.PRIMARY),
    "ok": ("fa5s.check-circle", theme.PRIMARY),
    "alerta": ("fa5s.exclamation-triangle", "#d97706"),
    "skip": ("fa5s.minus-circle", theme.TEXT_MUTED),
    "error": ("fa5s.exclamation-circle", "#c0392b"),
}


class BatchPage(QWidget):
    back_requested = Signal()
    # (caminho do dossie, posicoes suspeitas) — a MainWindow ouve e
    # abre o arquivo na aba Organizar com as paginas marcadas
    review_requested = Signal(str, list)

    def __init__(self, tool: Tool, parent=None) -> None:
        super().__init__(parent)
        self.tool = tool
        self._root: Path | None = None
        self._folders: dict[str, Path] = {}
        self._cancelled = False

        back_btn = QPushButton("  Voltar")
        back_btn.setIcon(qta.icon("fa5s.arrow-left", color="#333333"))
        back_btn.setObjectName("LinkButton")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(self.back_requested)

        title = QLabel(tool.title)
        title.setObjectName("PageTitle")
        desc = QLabel(tool.description)
        desc.setObjectName("PageDesc")

        self.root_label = QLabel("Nenhuma pasta selecionada")
        self.root_label.setObjectName("PageDesc")

        pick_btn = QPushButton("Selecionar pasta raiz")
        pick_btn.setObjectName("SecondaryButton")
        pick_btn.clicked.connect(self._pick_root)

        clear_btn = QPushButton("Limpar")
        clear_btn.setObjectName("SecondaryButton")
        clear_btn.clicked.connect(self._clear)

        self.run_btn = QPushButton("Organizar todas")
        self.run_btn.setObjectName("PrimaryButton")
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self._run)

        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setObjectName("SecondaryButton")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._cancel)

        top_row = QHBoxLayout()
        top_row.addWidget(pick_btn)
        top_row.addWidget(clear_btn)
        top_row.addWidget(self.root_label, 1)
        top_row.addWidget(self.cancel_btn)
        top_row.addWidget(self.run_btn)

        # Uma linha por pasta de paciente; o icone mostra o status.
        self.folder_list = QListWidget()
        self.folder_list.setObjectName("FileList")
        self.folder_list.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection
        )

        self.progress = QProgressBar()
        self.progress.setVisible(False)

        self.status = QLabel("")
        self.status.setObjectName("StatusLabel")

        self.open_btn = QPushButton("Abrir pasta raiz")
        self.open_btn.setObjectName("SecondaryButton")
        self.open_btn.setVisible(False)
        self.open_btn.clicked.connect(self._open_root)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 20, 28, 24)
        layout.addWidget(back_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addSpacing(10)
        layout.addLayout(top_row)
        layout.addWidget(self.folder_list, 1)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addWidget(self.open_btn, alignment=Qt.AlignmentFlag.AlignRight)

    # ------------------------------------------------------------- pasta

    def _pick_root(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Selecionar a pasta raiz (ex.: SEMANA 04)"
        )
        if path:
            self._scan(Path(path))

    def _scan(self, root: Path) -> None:
        self._root = root
        self.folder_list.clear()
        self._rows: dict[str, QListWidgetItem] = {}
        folders = auto_sort.list_patient_folders(root)
        for folder, pdfs in folders:
            item = QListWidgetItem(
                f"{folder.name} — {len(pdfs)} arquivo(s)"
            )
            item.setIcon(self._icon("pending"))
            item.setToolTip(str(folder))
            self.folder_list.addItem(item)
            self._rows[folder.name] = item
            self._folders[folder.name] = folder

        self.root_label.setText(str(root))
        self.open_btn.setVisible(False)
        if folders:
            self.status.setText(f"{len(folders)} pasta(s) de paciente(s) encontrada(s).")
            self.run_btn.setEnabled(True)
        else:
            self.status.setText("Nenhuma subpasta com PDFs encontrada.")
            self.run_btn.setEnabled(False)

    def _clear(self) -> None:
        """Limpa a pagina: esquece a raiz, a lista e o progresso."""
        self._root = None
        self._rows = {}
        self._folders = {}
        self.folder_list.clear()
        self.progress.setVisible(False)
        self.progress.setValue(0)
        self.root_label.setText("Nenhuma pasta selecionada")
        self.status.setText("")
        self.run_btn.setEnabled(False)
        self.open_btn.setVisible(False)

    def _icon(self, status: str):
        name, color = _ICONS[status]
        return qta.icon(name, color=color)

    # ------------------------------------------------------ processamento

    def _run(self) -> None:
        if self._root is None or self.folder_list.count() == 0:
            return
        self._cancelled = False
        self.run_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, self.folder_list.count())
        self.progress.setValue(0)
        self.open_btn.setVisible(False)
        self.status.setText("Processando...")

        worker = Worker(
            auto_sort.organize_batch,
            self._root,
            cancel=lambda: self._cancelled,
            with_progress=True,
        )
        worker.signals.progress.connect(self._on_progress)
        worker.signals.finished.connect(self._on_finished)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _cancel(self) -> None:
        self._cancelled = True
        self.cancel_btn.setEnabled(False)
        self.status.setText("Cancelando... (termina a pasta atual)")

    def _on_progress(self, entry: dict) -> None:
        item = self._rows.get(entry["folder"])
        if item is None:
            return
        status = entry["status"]
        item.setIcon(self._icon(status))
        if status == "start":
            self.status.setText(
                f"Processando {entry['index']}/{entry['total']}: "
                f"{entry['folder']} ({entry['files']} arquivo(s))"
            )
            item.setText(f"{entry['folder']} — processando...")
        elif status == "ok":
            self.progress.setValue(entry["index"])
            suspects = entry.get("suspects") or []
            excluded = entry.get("excluded") or []
            # tipo de processo detectado (retirada etc.) — ortopedia,
            # o caso comum, nao ganha etiqueta
            tag = ""
            if entry.get("kind") and entry["kind"] != "ortopedia":
                tag = f" [{entry.get('kind_label', '').upper()}]"
            parts = [
                f"{entry['folder']}{tag} — {entry['pages']} paginas → "
                f"{entry['output']}"
            ]
            if excluded:
                refs = ", ".join(
                    f"{e['file']} p.{e['page']}" for e in excluded
                )
                parts.append(
                    f"{len(excluded)} anulada(s) ignorada(s): {refs}"
                )
            skipped = entry.get("skipped") or []
            missing = entry.get("missing") or []
            if missing:
                parts.append("FALTA: " + ", ".join(missing))
            divergence = entry.get("proc_divergence")
            if divergence:
                refs = "; ".join(
                    f"{tipo}: {', '.join(pags[:4])}"
                    for tipo, pags in divergence.items()
                )
                parts.append(f"PROCEDIMENTO DIVERGENTE — {refs}")
            if skipped:
                parts.append(
                    f"ATENCAO: {len(skipped)} arquivo(s) ilegivel(is): "
                    + ", ".join(skipped)
                )
            if suspects or skipped or missing or divergence:
                item.setIcon(self._icon("alerta"))
            if suspects:
                pags = ", ".join(str(s["pos"]) for s in suspects)
                parts.append(f"pag. {pags} de outro paciente?")
                self._attach_review_button(item, entry, " — ".join(parts))
            else:
                item.setText(" — ".join(parts))
        elif status == "skip":
            self.progress.setValue(entry["index"])
            item.setText(f"{entry['folder']} — {entry['detail']}")
        elif status == "error":
            self.progress.setValue(entry["index"])
            item.setText(f"{entry['folder']} — ERRO: {entry['detail']}")

    def _attach_review_button(
        self, item: QListWidgetItem, entry: dict, text: str
    ) -> None:
        """Troca o texto da linha por um widget com o resumo + botao
        Revisar, que abre o dossie na aba Organizar com as paginas
        suspeitas destacadas."""
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(6, 2, 6, 2)
        row.setSpacing(8)
        label = QLabel(text)
        label.setWordWrap(True)
        review_btn = QPushButton("Revisar")
        review_btn.setObjectName("SecondaryButton")
        review_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        review_btn.clicked.connect(
            lambda: self._request_review(entry)
        )
        row.addWidget(label, 1)
        row.addWidget(review_btn)
        # sizeHint antes do show pode vir achatado; garante altura minima
        # para a linha nao colapsar dentro do QListWidget.
        item.setSizeHint(QSize(-1, max(holder.sizeHint().height(), 40)))
        self.folder_list.setItemWidget(item, holder)

    def _request_review(self, entry: dict) -> None:
        # a pasta pode ter sido renomeada com a anotacao " (falta ...)"
        # — usa o caminho real retornado pelo processamento
        folder = entry.get("folder_path") or self._folders.get(
            entry["folder"]
        )
        positions = [s["pos"] for s in entry.get("suspects") or ()]
        if folder and positions:
            self.review_requested.emit(
                str(Path(folder) / entry["output"]), positions
            )

    def _on_finished(self, results: list) -> None:
        ok = sum(1 for r in results if r["status"] == "ok")
        skip = sum(1 for r in results if r["status"] == "skip")
        err = sum(1 for r in results if r["status"] == "error")
        anul = sum(len(r.get("excluded") or ()) for r in results)
        self.run_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.setEnabled(True)
        self.open_btn.setVisible(True)
        prefix = "Cancelado. " if self._cancelled else "Concluido: "
        resumo = (
            f"{ok} pasta(s) organizada(s), {skip} pulada(s), "
            f"{err} erro(s), {anul} pagina(s) anulada(s) ignorada(s)."
        )
        self.status.setText(prefix + resumo)

        # Alerta DENTRO do app: divergencias/erros ficam registrados
        # aqui — se o usuario perder o toast do Windows, encontra o
        # aviso ao voltar para a janela.
        linhas_alerta = []
        for r in results:
            for s in r.get("suspects") or ():
                nome = (
                    f" (encontrado: {s['found'][0]})"
                    if s.get("found") else ""
                )
                linhas_alerta.append(
                    f"• {r['folder']} — pag. {s['pos']} ({s['cls']}){nome}"
                )
        erros = [
            f"• {r['folder']} — {r['detail']}"
            for r in results if r["status"] == "error"
        ]
        faltas = [
            f"• {r['folder']} — falta {', '.join(r['missing'])}"
            for r in results if r.get("missing")
        ]
        divergentes = []
        for r in results:
            div = r.get("proc_divergence")
            if div:
                tipos = " x ".join(div.keys())
                divergentes.append(
                    f"• {r['folder']} — procedimento divergente: {tipos}"
                )
        if linhas_alerta or erros or faltas or divergentes:
            corpo = resumo + "\n\n"
            if divergentes:
                corpo += (
                    "Documentos com procedimentos divergentes:\n"
                    + "\n".join(divergentes) + "\n\n"
                )
            if linhas_alerta:
                corpo += (
                    "Paginas que podem pertencer a outro paciente:\n"
                    + "\n".join(linhas_alerta) + "\n\n"
                )
            if faltas:
                corpo += (
                    "Documentos obrigatorios ausentes:\n"
                    + "\n".join(faltas) + "\n\n"
                )
            if erros:
                corpo += "Pastas com erro:\n" + "\n".join(erros) + "\n\n"
            corpo += "Revise os arquivos gerados antes de enviar."
            QMessageBox.warning(self, "Lote concluido", corpo)

        # Notificacao do Windows (toast): o usuario pode estar com o
        # app minimizado — controlada pela opcao em Configuracoes.
        if not QSettings(QSETTINGS_ORG, QSETTINGS_APP).value(
            KEY_NOTIFY, True, type=bool
        ):
            return
        linhas = (
            [resumo] + divergentes + linhas_alerta + faltas + erros
        )
        if len(linhas) > 9:
            linhas = linhas[:9] + ["... — veja a lista completa no app"]
        window = self.window()
        if hasattr(window, "notify"):
            window.notify("Lote concluido", "\n".join(linhas))

    def _on_error(self, message: str) -> None:
        self.run_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setVisible(False)
        QMessageBox.critical(self, self.tool.title, f"Erro: {message}")

    def _open_root(self) -> None:
        if self._root:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._root)))
