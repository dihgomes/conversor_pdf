"""Worker generico para rodar operacoes de PDF no QThreadPool."""
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Signal


class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(str)
    progress = Signal(object)


class Worker(QRunnable):
    """Executa uma funcao em background e emite sinais com o resultado.

    Com with_progress=True, a funcao recebe progress=<emitter> — chame
    progress(obj) dentro dela para reportar andamento para a UI.
    """

    def __init__(
        self,
        fn: Callable[..., Any],
        *args: Any,
        with_progress: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.with_progress = with_progress
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            if self.with_progress:
                self.kwargs["progress"] = self.signals.progress.emit
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001 - repassa qualquer falha para a UI
            self.signals.error.emit(str(exc))
        else:
            self.signals.finished.emit(result)
