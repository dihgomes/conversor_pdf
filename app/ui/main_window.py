"""Janela principal: sidebar retratil + paginas empilhadas."""
import qtawesome as qta
from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QSettings,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
)
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.core import updates
from app.registry import TOOLS
from app.ui import theme
from app.ui.pages.batch_page import BatchPage
from app.ui.pages.home_page import HomePage
from app.ui.pages.organize_page import OrganizePage
from app.ui.pages.settings_page import (
    KEY_DARK,
    QSETTINGS_APP,
    QSETTINGS_ORG,
    SettingsPage,
)
from app.ui.pages.tool_page import ToolPage
from app.workers.worker import Worker

# Ferramentas com tela propria (fora do modelo generico ToolPage).
PAGE_OVERRIDES = {"organize": OrganizePage, "lote_ortopedia": BatchPage}

SIDEBAR_WIDTH = 220
RAIL_WIDTH = 60
APP_TITLE = "Conversor de arquivos PDF"

def build_style() -> str:
    """Monta a folha de estilo com a paleta ativa — refeita a cada
    troca de tema claro/escuro."""
    return f"""
QMainWindow, QWidget {{ background: {theme.APP_BG}; color: {theme.TEXT};
    font-family: 'Segoe UI'; }}
QLabel {{ background: transparent; }}
#SidebarWrap {{ background: {theme.SIDEBAR_BG}; }}
#SidebarWrap > QWidget {{ background: transparent; }}
QListWidget#Sidebar {{ background: transparent; color: {theme.SIDEBAR_TEXT};
    border: none; font-size: 13px; outline: none; }}
QListWidget#Sidebar::item {{ padding: 8px 12px; margin: 1px 8px; }}
QListWidget#Sidebar::item:selected {{ background: {theme.PRIMARY};
    border-radius: 6px; }}
QListWidget#Sidebar::item:hover:!selected {{ background: {theme.SIDEBAR_HOVER};
    border-radius: 6px; }}
#SidebarLogo {{ color: #ffffff; font-size: 13px; font-weight: 700; }}
#SidebarFooter {{ color: {theme.SIDEBAR_SECTION}; font-size: 10px;
    padding: 8px; }}
QToolButton {{ background: transparent; border: none; border-radius: 6px; }}
QToolButton:hover {{ background: {theme.SIDEBAR_HOVER}; }}
QToolButton:checked {{ background: {theme.PRIMARY}; }}
#HomeHeader {{ font-size: 26px; font-weight: 700; color: {theme.TEXT}; }}
#HomeSubtitle {{ font-size: 14px; color: {theme.TEXT_MUTED}; }}
#CategoryHeader {{ color: {theme.TEXT_MUTED}; font-size: 12px;
    font-weight: 700; letter-spacing: 1px; }}
#PageTitle {{ font-size: 20px; font-weight: 700; color: {theme.TEXT}; }}
#PageDesc {{ font-size: 13px; color: {theme.TEXT_MUTED}; }}
#ToolCard {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER};
    border-radius: 10px; }}
#ToolCard:hover {{ border: 1px solid {theme.PRIMARY}; }}
#ToolCardTitle {{ font-size: 14px; font-weight: 600; color: {theme.TEXT}; }}
#ToolCardDesc {{ font-size: 11px; color: {theme.TEXT_FAINT}; }}
#DropZone {{ background: {theme.SURFACE}; border: 2px dashed {theme.THUMB_BORDER};
    border-radius: 10px; }}
#DropZoneLabel {{ color: {theme.TEXT_FAINT}; font-size: 13px; }}
#FileList {{ background: {theme.SURFACE}; color: {theme.TEXT};
    border: 1px solid {theme.BORDER}; border-radius: 8px; font-size: 12px; }}
#RangeInput {{ background: {theme.SURFACE}; color: {theme.TEXT};
    border: 1px solid {theme.BORDER}; border-radius: 6px;
    padding: 8px 10px; font-size: 12px; }}
#PrimaryButton {{ background: {theme.PRIMARY}; color: #ffffff; border: none;
    border-radius: 6px; padding: 9px 22px; font-size: 13px; font-weight: 600; }}
#PrimaryButton:hover {{ background: {theme.PRIMARY_HOVER}; }}
#PrimaryButton:disabled {{ background: {theme.PRIMARY_DISABLED}; }}
#SecondaryButton {{ background: {theme.SURFACE}; color: {theme.TEXT};
    border: 1px solid {theme.BORDER}; border-radius: 6px;
    padding: 8px 16px; font-size: 12px; }}
#SecondaryButton:hover {{ border-color: {theme.PRIMARY}; color: {theme.PRIMARY}; }}
#LinkButton {{ background: transparent; border: none; color: {theme.TEXT_MUTED};
    padding: 6px; font-size: 12px; }}
#LinkButton:hover {{ color: {theme.PRIMARY}; }}
#StatusLabel {{ color: {theme.STATUS_OK}; font-size: 12px; }}
QProgressBar {{ border: none; background: {theme.BORDER}; border-radius: 4px;
    height: 8px; }}
QProgressBar::chunk {{ background: {theme.PRIMARY}; border-radius: 4px; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px;
    margin: 6px 3px 6px 0px; }}
QScrollBar::handle:vertical {{ background: {theme.THUMB_BORDER};
    border-radius: 5px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: {theme.PRIMARY}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px;
    margin: 0px 3px 6px 0px; }}
QScrollBar::handle:horizontal {{ background: {theme.THUMB_BORDER};
    border-radius: 5px; min-width: 32px; }}
QScrollBar::handle:horizontal:hover {{ background: {theme.PRIMARY}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent; }}
#Sidebar QScrollBar::handle:vertical {{
    background: {theme.SIDEBAR_SCROLL}; }}
#Sidebar QScrollBar::handle:vertical:hover {{
    background: {theme.SIDEBAR_SCROLL_HOVER}; }}
QToolTip {{ background: {theme.SIDEBAR_BG}; color: #ffffff;
    border: 1px solid {theme.SIDEBAR_HOVER}; padding: 4px 8px; }}
"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1060, 660)
        self._settings = QSettings(QSETTINGS_ORG, QSETTINGS_APP)
        # Tema salvo precisa ser aplicado ANTES de montar a folha de
        # estilo e as paginas (a grade do Organizar le theme.* na criacao).
        if self._settings.value(KEY_DARK, False, type=bool):
            theme.set_mode("dark")
        self.setStyleSheet(build_style())

        # ---------- paginas ----------
        self.stack = QStackedWidget()
        self.home = HomePage()
        self.stack.addWidget(self.home)

        self._page_index: dict[str, int] = {}
        self._tool_pages: dict[str, QWidget] = {}
        for tool in TOOLS:
            page = PAGE_OVERRIDES.get(tool.id, ToolPage)(tool)
            page.back_requested.connect(self._go_home)
            if isinstance(page, BatchPage):
                page.review_requested.connect(self._open_review)
            self._tool_pages[tool.id] = page
            self._page_index[tool.id] = self.stack.addWidget(page)

        self.settings_page = SettingsPage()
        self.settings_page.back_requested.connect(self._go_home)
        self.settings_page.theme_changed.connect(self._apply_theme)
        self._tool_pages["settings"] = self.settings_page
        self._page_index["settings"] = self.stack.addWidget(
            self.settings_page
        )

        # ---------- sidebar: nome do hospital + lista completa ----------
        logo_text = QLabel("Hospital Regional de Ruy Barbosa")
        logo_text.setObjectName("SidebarLogo")
        logo_text.setWordWrap(True)  # quebra em 2 linhas na largura fixa

        collapse_btn = self._icon_button("fa5s.bars", "Recolher menu")
        collapse_btn.clicked.connect(self._toggle_sidebar)

        self.brand = QWidget()
        brand_row = QHBoxLayout(self.brand)
        brand_row.setContentsMargins(16, 12, 10, 12)
        brand_row.setSpacing(10)
        brand_row.addWidget(logo_text, 1)
        brand_row.addWidget(collapse_btn)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setIconSize(QSize(14, 14))
        self.sidebar.setSpacing(1)
        # Impede que itens arrastados de outras telas "entrem" na sidebar
        # (drop de InternalMove apagaria o item da origem).
        self.sidebar.setDragDropMode(QListWidget.DragDropMode.NoDragDrop)
        self.sidebar.viewport().setAcceptDrops(False)

        self._row_to_stack: dict[int, int] = {}
        self._tool_row: dict[str, int] = {}
        # Secoes colapsaveis: cada categoria vira um cabecalho clicavel
        # que abre/fecha suas ferramentas (efeito acordeao — abrir uma
        # fecha as outras).
        self._sections: list[dict] = []
        self._header_section: dict[int, int] = {}  # linha do header -> secao
        self._row_section: dict[int, int] = {}     # linha do tool -> secao
        self._expanded = -1

        home_item = QListWidgetItem(
            qta.icon("fa5s.home", color=theme.SIDEBAR_TEXT), "Inicio"
        )
        self.sidebar.addItem(home_item)
        self._row_to_stack[0] = 0

        current_cat = None
        for tool in TOOLS:
            if tool.category != current_cat:
                current_cat = tool.category
                header = QListWidgetItem(current_cat)
                # ItemIsEnabled (sem Selectable): o clique chega via
                # itemClicked sem roubar a selecao do item atual.
                header.setFlags(Qt.ItemFlag.ItemIsEnabled)
                header.setForeground(QColor(theme.SIDEBAR_SECTION))
                header.setIcon(
                    qta.icon("fa5s.chevron-right",
                             color=theme.SIDEBAR_SECTION)
                )
                font = header.font()
                font.setPointSize(8)
                font.setBold(True)
                header.setFont(font)
                header.setSizeHint(QSize(0, 32))
                self.sidebar.addItem(header)
                self._header_section[self.sidebar.count() - 1] = len(
                    self._sections
                )
                self._sections.append({"header": header, "rows": []})

            item = QListWidgetItem(
                qta.icon(tool.icon, color=theme.SIDEBAR_TEXT), tool.title
            )
            self.sidebar.addItem(item)
            row = self.sidebar.count() - 1
            self._row_to_stack[row] = self._page_index[tool.id]
            self._tool_row[tool.id] = row
            self._row_section[row] = len(self._sections) - 1
            self._sections[-1]["rows"].append(row)

        # Espaco + "Configuracoes" no rodape da lista — item solto,
        # sempre visivel, fora das secoes colapsaveis.
        spacer = QListWidgetItem()
        spacer.setFlags(Qt.ItemFlag.NoItemFlags)
        spacer.setSizeHint(QSize(0, 14))
        self.sidebar.addItem(spacer)

        settings_item = QListWidgetItem(
            qta.icon("fa5s.cog", color=theme.SIDEBAR_TEXT), "Configuracoes"
        )
        self.sidebar.addItem(settings_item)
        self._row_to_stack[self.sidebar.count() - 1] = self._page_index[
            "settings"
        ]

        self._stack_to_row = {v: k for k, v in self._row_to_stack.items()}
        self._expand_section(0)  # primeira secao comeca aberta

        # ---------- rail de icones (sidebar recolhida) ----------
        self.rail = QWidget()
        rail_layout = QVBoxLayout(self.rail)
        rail_layout.setContentsMargins(0, 16, 0, 8)
        rail_layout.setSpacing(4)
        rail_layout.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
        )

        expand_btn = self._icon_button("fa5s.bars", "Expandir menu")
        expand_btn.clicked.connect(self._toggle_sidebar)
        rail_layout.addWidget(expand_btn)
        rail_layout.addSpacing(10)

        self._rail_group = QButtonGroup(self.rail)
        self._rail_group.setExclusive(True)
        self._rail_btns: dict[int, QToolButton] = {}

        rail_nav = [(qta.icon("fa5s.home", color=theme.SIDEBAR_TEXT), "Inicio", 0)]
        prev_cat = None
        for tool in TOOLS:
            if tool.category != prev_cat:
                prev_cat = tool.category
                rail_nav.append("SPACER")
            rail_nav.append(
                (
                    qta.icon(tool.icon, color=theme.SIDEBAR_TEXT),
                    tool.title,
                    self._page_index[tool.id],
                )
            )

        rail_nav.append("SPACER")
        rail_nav.append(
            (
                qta.icon("fa5s.cog", color=theme.SIDEBAR_TEXT),
                "Configuracoes",
                self._page_index["settings"],
            )
        )

        for entry in rail_nav:
            if entry == "SPACER":
                rail_layout.addSpacing(8)
                continue
            icon, tip, stack_index = entry
            btn = self._icon_button(None, tip)
            btn.setIcon(icon)
            btn.setCheckable(True)
            btn.setFixedSize(40, 38)
            btn.setIconSize(QSize(17, 17))
            btn.clicked.connect(
                lambda checked=False, i=stack_index: self._go_to(i)
            )
            self._rail_group.addButton(btn)
            self._rail_btns[stack_index] = btn
            rail_layout.addWidget(btn)

        self.rail.setVisible(False)

        # ---------- monta a sidebar ----------
        sidebar_wrap = QWidget()
        sidebar_wrap.setObjectName("SidebarWrap")
        sidebar_wrap.setMinimumWidth(RAIL_WIDTH)
        sidebar_wrap.setMaximumWidth(SIDEBAR_WIDTH)
        side_layout = QVBoxLayout(sidebar_wrap)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(0)
        side_layout.addWidget(self.brand)
        side_layout.addWidget(self.sidebar, 1)
        side_layout.addWidget(self.rail, 1)

        self.footer = QLabel(
            f"Desenvolvido por Diego Gomes\nV.{__version__}"
        )
        self.footer.setObjectName("SidebarFooter")
        self.footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side_layout.addWidget(self.footer)

        self._sidebar_wrap = sidebar_wrap
        self._collapsed = False

        self.home.tool_selected.connect(self._open_tool)
        self.sidebar.currentRowChanged.connect(self._on_nav)
        self.sidebar.itemClicked.connect(self._on_sidebar_click)

        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(sidebar_wrap)
        row.addWidget(self.stack, 1)

        self.setCentralWidget(central)
        self.sidebar.setCurrentRow(0)

        # Icone de bandeja — necessario para showMessage (toast do
        # Windows, exibido mesmo com a janela minimizada).
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(
            qta.icon("fa5s.file-pdf", color=theme.PRIMARY)
        )
        self._tray.setToolTip(APP_TITLE)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray.show()

        # Checagem de atualizacao em background, depois da janela abrir
        QTimer.singleShot(3000, self._check_updates)

    def notify(self, title: str, message: str) -> None:
        """Notificacao do Windows (toast); se a bandeja nao estiver
        disponivel, cai num popup NAO-modal (um QMessageBox modal
        travaria a thread ate o usuario clicar)."""
        if self._tray.isVisible():
            self._tray.showMessage(
                title, message,
                QSystemTrayIcon.MessageIcon.Information, 10000,
            )
        else:
            box = QMessageBox(self)
            box.setWindowTitle(title)
            box.setText(message)
            box.setIcon(QMessageBox.Icon.Information)
            box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            box.show()

    # ----------------------------------------------------- atualizacao

    def _check_updates(self) -> None:
        """Consulta o GitHub em background; nunca trava a UI nem mostra
        erro — sem internet/repo privado simplesmente nao avisa."""
        worker = Worker(updates.check_for_update)
        worker.signals.finished.connect(self._on_update_check)
        QThreadPool.globalInstance().start(worker)

    def _on_update_check(self, remote: str | None) -> None:
        """Versao mais nova no GitHub: toast do Windows + popup
        nao-modal com botao para a pagina de releases."""
        if not remote:
            return
        msg = (
            f"Versao V.{remote} disponivel "
            f"(voce esta na V.{__version__})."
        )
        self.notify("Atualizacao disponivel", msg)
        box = QMessageBox(self)
        box.setWindowTitle("Atualizacao disponivel")
        box.setText(
            msg + "\n\nBaixe a versao mais recente na pagina do projeto."
        )
        box.setIcon(QMessageBox.Icon.Information)
        open_btn = box.addButton(
            "Abrir pagina", QMessageBox.ButtonRole.AcceptRole
        )
        box.addButton(QMessageBox.StandardButton.Ok)
        open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(updates.RELEASES_URL))
        )
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.show()  # nao-modal: nao bloqueia o app

    # -------------------------------------------------------- navegacao

    def _icon_button(self, icon_name: str | None, tooltip: str) -> QToolButton:
        btn = QToolButton()
        if icon_name:
            btn.setIcon(qta.icon(icon_name, color=theme.SIDEBAR_TEXT))
        btn.setIconSize(QSize(16, 16))
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def _go_to(self, stack_index: int) -> None:
        self.stack.setCurrentIndex(stack_index)
        row = self._stack_to_row.get(stack_index, 0)
        # Garante que a secao da ferramenta esteja aberta antes de
        # selecionar a linha (uma linha escondida nao pode ser atual).
        sec = self._row_section.get(row)
        if sec is not None and sec != self._expanded:
            self._expand_section(sec)
        self.sidebar.blockSignals(True)
        self.sidebar.setCurrentRow(row)
        self.sidebar.blockSignals(False)
        btn = self._rail_btns.get(stack_index)
        if btn is not None:
            btn.setChecked(True)

    def _open_tool(self, tool_id: str) -> None:
        self._go_to(self._page_index[tool_id])

    def _open_review(self, pdf_path: str, positions: list) -> None:
        """Vem do Organizar em Lote: abre o dossie divergente na aba
        Organizar, com as paginas suspeitas marcadas em vermelho."""
        organize = self._tool_pages.get("organize")
        if isinstance(organize, OrganizePage):
            organize.load_for_review(pdf_path, positions)
        self._go_to(self._page_index["organize"])

    def _go_home(self) -> None:
        self._go_to(0)

    def _apply_theme(self, dark: bool) -> None:
        """Vem de Configuracoes: troca a paleta e remonta os estilos
        em runtime (a folha global cobre quase tudo; a grade do
        Organizar tem folha propria e se atualiza em refresh_theme)."""
        theme.set_mode("dark" if dark else "light")
        self.setStyleSheet(build_style())
        for page in self._tool_pages.values():
            refresh = getattr(page, "refresh_theme", None)
            if refresh:
                refresh()

    def _on_nav(self, row: int) -> None:
        if row in self._row_to_stack:
            self._go_to(self._row_to_stack[row])

    def _on_sidebar_click(self, item: QListWidgetItem) -> None:
        """Clique num cabecalho de categoria abre/fecha a secao."""
        sec = self._header_section.get(self.sidebar.row(item))
        if sec is not None:
            self._expand_section(sec)

    def _expand_section(self, sec: int) -> None:
        """Acordeao: abre a secao pedida e esconde as demais."""
        self._expanded = sec
        for i, data in enumerate(self._sections):
            open_ = i == sec
            for row in data["rows"]:
                self.sidebar.item(row).setHidden(not open_)
            data["header"].setIcon(
                qta.icon(
                    "fa5s.chevron-down" if open_ else "fa5s.chevron-right",
                    color=theme.SIDEBAR_SECTION,
                )
            )

    # -------------------------------------------------------- retratil

    def _toggle_sidebar(self) -> None:
        self._collapsed = not self._collapsed
        target = RAIL_WIDTH if self._collapsed else SIDEBAR_WIDTH

        self.brand.setVisible(not self._collapsed)
        self.sidebar.setVisible(not self._collapsed)
        self.rail.setVisible(self._collapsed)
        self.footer.setVisible(not self._collapsed)

        self._anim = QPropertyAnimation(
            self._sidebar_wrap, b"maximumWidth", self
        )
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._anim.setStartValue(self._sidebar_wrap.width())
        self._anim.setEndValue(target)
        self._anim.start()
