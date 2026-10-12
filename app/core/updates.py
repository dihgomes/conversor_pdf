"""Verificacao de atualizacao no GitHub.

Compara a versao local (app.__version__) com o __init__.py publicado no
branch main do repositorio. Funciona so com o repo PUBLICO — o raw do
GitHub nao pede autenticacao nesse caso. Qualquer falha (sem internet,
repo privado, parse) devolve None em silencio: o app nunca deve atrapalhar
o usuario por causa da checagem.
"""
import re
import urllib.request

from app import __version__

REPO_OWNER = "dihgomes"
REPO_NAME = "conversor_pdf"
RAW_VERSION_URL = (
    f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}"
    "/main/app/__init__.py"
)
RELEASES_URL = (
    f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases"
)


def _parse_version(text: str) -> tuple[int, ...] | None:
    """Extrai a tupla de versao de '__version__ = "0.4"' -> (0, 4)."""
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    if not m:
        return None
    parts = re.findall(r"\d+", m.group(1))
    return tuple(int(p) for p in parts) if parts else None


def check_for_update(timeout: int = 10) -> str | None:
    """Retorna a versao remota se for mais nova que a local; senao None.

    Roda em thread de background (Worker) — urlopen e bloqueante.
    """
    try:
        req = urllib.request.Request(
            RAW_VERSION_URL, headers={"User-Agent": "ConversorPDF"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            remote = _parse_version(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - offline/repo privado: sem aviso
        return None
    local = _parse_version(f'__version__ = "{__version__}"')
    if remote and local and remote > local:
        return ".".join(map(str, remote))
    return None
