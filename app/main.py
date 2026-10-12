"""Ponto de entrada do aplicativo.

Executar a partir da raiz do projeto:
    python -m app.main
"""
import shutil
import sys
import tempfile
import time
from pathlib import Path

import qtawesome as qta
from PySide6.QtWidgets import QApplication

from app.ui import theme
from app.ui.main_window import MainWindow


def _cleanup_stale_mei() -> None:
    """Remove extracoes _MEI* orfas deixadas por execucoes encerradas
    abruptamente (queda de energia, kill).

    Cada pasta ocupa ~200 MB em %TEMP%; acumuladas podem encher o
    volume ou levar o Windows/antivirus a apagar partes da extracao
    em uso — sintoma observado: "no module named cv2". So apaga
    pastas criadas ANTES do ultimo boot: nenhum processo sobrevive a
    um reboot, entao elas sao certamente orfas.
    """
    try:
        import ctypes
        uptime_ms = ctypes.windll.kernel32.GetTickCount64()
        boot_time = time.time() - uptime_ms / 1000
    except Exception:  # noqa: BLE001
        return
    for d in Path(tempfile.gettempdir()).glob("_MEI*"):
        try:
            if d.is_dir() and d.stat().st_ctime < boot_time:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def main() -> int:
    _cleanup_stale_mei()
    app = QApplication(sys.argv)
    app.setApplicationName("Conversor de arquivos PDF")
    app.setOrganizationName("HRRB")
    app.setWindowIcon(qta.icon("fa5s.file-pdf", color=theme.PRIMARY))

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
