#!/usr/bin/env python3
"""Release automatico do ConversorPDF.

Passos: bump de versao -> build PyInstaller -> commit/tag/push ->
release no GitHub com o exe anexado.

Uso:
    python release.py                # release da versao atual
    python release.py 0.5            # bumpara para 0.5 e releasea
    python release.py --no-build     # pula o PyInstaller (exe atual)
    python release.py --no-commit    # pula commit/push (codigo ja subiu)

Token do GitHub: variavel GITHUB_TOKEN ou a URL do remote origin
(https://<token>@github.com/...). Nunca e salvo em arquivo.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
INIT_FILE = ROOT / "app" / "__init__.py"
SPEC = ROOT / "ConversorPDF.spec"
EXE = ROOT / "dist" / "ConversorPDF.exe"
REPO = "dihgomes/conversor_pdf"
ASSET_NAME = "ConversorPDF.exe"


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(cmd)}")
    proc = subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    )
    if check and proc.returncode != 0:
        sys.exit(f"falhou: {cmd[0]} {cmd[1]}\n{proc.stdout}{proc.stderr}")
    return proc


def get_version() -> str:
    m = re.search(
        r'__version__\s*=\s*["\']([^"\']+)', INIT_FILE.read_text("utf-8")
    )
    if not m:
        sys.exit("__version__ nao encontrado em app/__init__.py")
    return m.group(1)


def bump_version(version: str) -> None:
    INIT_FILE.write_text(
        f'__version__ = "{version}"\n', encoding="utf-8"
    )


def get_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    url = run(
        ["git", "remote", "get-url", "origin"], check=True
    ).stdout.strip()
    m = re.search(r"https://([^@:]+)@github\.com/", url)
    if m:
        return m.group(1)
    sys.exit(
        "Token nao encontrado. Defina GITHUB_TOKEN ou use remote com "
        "https://<token>@github.com/dihgomes/conversor_pdf.git"
    )


def api(
    method: str, url: str, token: str,
    data: bytes | None = None, content_type: str = "application/json",
) -> dict:
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": content_type,
            "User-Agent": "ConversorPDF-release",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        sys.exit(f"GitHub {method} {url} -> {exc.code}\n{detail}")


def get_release_by_tag(tag: str, token: str) -> dict | None:
    url = f"https://api.github.com/repos/{REPO}/releases/tags/{tag}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "ConversorPDF-release",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def publish_release(version: str, token: str, notes: str) -> None:
    tag = f"v{version}"
    release = get_release_by_tag(tag, token)
    if release:
        print(f"release {tag} ja existe — reutilizando")
    else:
        release = api(
            "POST",
            f"https://api.github.com/repos/{REPO}/releases",
            token,
            data=json.dumps({
                "tag_name": tag,
                "target_commitish": "main",
                "name": f"V.{version}",
                "body": notes,
            }).encode("utf-8"),
        )
        print(f"release criada: {release['html_url']}")

    # Se o asset ja existe, apaga para re-upload (exe recompilado)
    assets = api(
        "GET",
        f"https://api.github.com/repos/{REPO}/releases/"
        f"{release['id']}/assets?per_page=100",
        token,
    )
    for asset in assets:
        if asset["name"] == ASSET_NAME:
            api(
                "DELETE",
                f"https://api.github.com/repos/{REPO}/releases/"
                f"assets/{asset['id']}",
                token,
            )
            print("asset antigo removido")

    print(f"enviando {ASSET_NAME} ({EXE.stat().st_size // 1048576} MB)...")
    upload_url = release["upload_url"].split("{")[0]
    api(
        "POST",
        f"{upload_url}?name={ASSET_NAME}",
        token,
        data=EXE.read_bytes(),
        content_type="application/octet-stream",
    )
    print(f"download: https://github.com/{REPO}/releases/tag/{tag}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", nargs="?", help="nova versao (ex.: 0.5)")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--no-commit", action="store_true")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    version = args.version or get_version()
    if not re.fullmatch(r"\d+(\.\d+)*", version):
        sys.exit(f"versao invalida: {version!r} (use numeros, ex.: 0.5)")
    if args.version:
        bump_version(version)
        print(f"versao bumpara para {version}")

    token = get_token()

    if not args.no_build:
        run([
            sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm",
        ])
    if not EXE.exists():
        sys.exit(f"{EXE} nao existe — rode o build ou ajuste o spec")

    if not args.no_commit:
        run(["git", "add", "-A"])
        diff = run(["git", "diff", "--cached", "--quiet"], check=False)
        if diff.returncode != 0:
            run(["git", "commit", "-m", f"release V.{version}"])
        run(["git", "push", "origin", "main"])

    publish_release(version, token, args.notes)
    print(f"\nPronto — V.{version} publicada.")


if __name__ == "__main__":
    main()
