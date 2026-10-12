"""Pagina de Configuracoes — preferencias persistentes do aplicativo.

As opcoes sao gravadas em QSettings (registro do Windows) e sobrevivem
entre execucoes. A troca de tema e aplicada na hora via theme_changed.
"""
import qtawesome as qta
from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# Chaves compartilhadas — o Organizar em Lote le o notify_on_finish
# daqui mesmo, sem depender de um widget na propria pagina.
QSETTINGS_ORG = "HRRB"
QSETTINGS_APP = "ConversorPDF"
KEY_NOTIFY = "notify_on_finish"
KEY_DARK = "dark_mode"


class SettingsPage(QWidget):
    back_requested = Signal()
    theme_changed = Signal(bool)  # True = tema escuro

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._settings = QSettings(QSETTINGS_ORG, QSETTINGS_APP)

        back_btn = QPushButton("  Voltar")
        back_btn.setIcon(qta.icon("fa5s.arrow-left", color="#333333"))
        back_btn.setObjectName("LinkButton")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(self.back_requested)

        title = QLabel("Configuracoes")
        title.setObjectName("PageTitle")
        desc = QLabel("Preferencias do aplicativo")
        desc.setObjectName("PageDesc")

        # ---------- notificacoes ----------
        sec_notif = QLabel("NOTIFICACOES")
        sec_notif.setObjectName("CategoryHeader")
        self.notify_chk = QCheckBox(
            "Notificar no Windows ao concluir a organizacao em lote"
        )
        self.notify_chk.setChecked(
            self._settings.value(KEY_NOTIFY, True, type=bool)
        )
        self.notify_chk.toggled.connect(
            lambda on: self._settings.setValue(KEY_NOTIFY, bool(on))
        )
        notif_hint = QLabel(
            "O aviso do Windows aparece mesmo com o app minimizado. "
            "O resumo dentro do app continua sendo exibido sempre."
        )
        notif_hint.setObjectName("PageDesc")
        notif_hint.setWordWrap(True)

        # ---------- aparencia ----------
        sec_apar = QLabel("APARENCIA")
        sec_apar.setObjectName("CategoryHeader")
        self.theme_btn = QPushButton()
        self.theme_btn.setObjectName("SecondaryButton")
        self.theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_btn.clicked.connect(self._toggle_theme)
        self._update_theme_btn()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 20, 28, 24)
        layout.addWidget(back_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addSpacing(18)
        layout.addWidget(sec_notif)
        layout.addSpacing(4)
        layout.addWidget(self.notify_chk)
        layout.addWidget(notif_hint)
        layout.addSpacing(18)
        layout.addWidget(sec_apar)
        layout.addSpacing(4)
        layout.addWidget(
            self.theme_btn, alignment=Qt.AlignmentFlag.AlignLeft
        )
        layout.addStretch()

    # ------------------------------------------------------------ tema

    def is_dark(self) -> bool:
        return self._settings.value(KEY_DARK, False, type=bool)

    def _toggle_theme(self) -> None:
        dark = not self.is_dark()
        self._settings.setValue(KEY_DARK, dark)
        self._update_theme_btn()
        self.theme_changed.emit(dark)

    def _update_theme_btn(self) -> None:
        if self.is_dark():
            self.theme_btn.setText("Mudar para tema claro")
            self.theme_btn.setIcon(qta.icon("fa5s.sun", color="#f59e0b"))
        else:
            self.theme_btn.setText("Mudar para tema escuro")
            self.theme_btn.setIcon(
                qta.icon("fa5s.moon", color="#334155")
            )
