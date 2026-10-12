"""Operacoes de PDF com PyMuPDF.

Todas as funcoes seguem a mesma assinatura:
    handler(files: list[str], output: str, options: dict | None = None)

- `files`: caminhos dos arquivos de entrada selecionados na UI.
- `output`: caminho do arquivo de saida ou diretorio de destino.
- `options`: parametros extras da tela (ex.: {"pages": "1-3,5"}).
- Retorna o(s) caminho(s) gerado(s).
"""
from pathlib import Path

import pymupdf as fitz


def parse_page_ranges(spec: str, page_count: int) -> list[int]:
    """Converte '1-3,5,8-10' em indices 0-based, validando contra page_count."""
    pages: set[int] = set()
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                start_s, end_s = part.split("-", 1)
                start, end = int(start_s), int(end_s)
                if start > end:
                    start, end = end, start
                pages.update(range(start - 1, end))
            else:
                pages.add(int(part) - 1)
        except ValueError:
            raise ValueError(f"Intervalo invalido: '{part}'.") from None

    result = sorted(pages)
    if not result:
        raise ValueError("Informe as paginas (ex.: 1-3, 5, 8-10).")
    if result[0] < 0 or result[-1] >= page_count:
        raise ValueError(f"Paginas fora do intervalo 1-{page_count}.")
    return result


def _require_pages(options: dict | None) -> str:
    spec = (options or {}).get("pages", "").strip()
    if not spec:
        raise ValueError("Informe as paginas (ex.: 1-3, 5, 8-10).")
    return spec


def merge_pdfs(files: list[str], output: str, options: dict | None = None) -> str:
    """Junta varios PDFs em um unico arquivo."""
    if len(files) < 2:
        raise ValueError("Selecione pelo menos 2 arquivos PDF para juntar.")
    doc = fitz.open()
    try:
        for path in files:
            with fitz.open(path) as src:
                doc.insert_pdf(src)
        doc.save(output, garbage=4, deflate=True)
    finally:
        doc.close()
    return output


def split_pdf(files: list[str], output_dir: str, options: dict | None = None) -> list[str]:
    """Divide um PDF em um arquivo por pagina."""
    outputs: list[str] = []
    stem = Path(files[0]).stem
    with fitz.open(files[0]) as src:
        for i in range(src.page_count):
            with fitz.open() as page_doc:
                page_doc.insert_pdf(src, from_page=i, to_page=i)
                out = str(Path(output_dir) / f"{stem}_pagina_{i + 1}.pdf")
                page_doc.save(out)
                outputs.append(out)
    return outputs


def remove_pages(files: list[str], output: str, options: dict | None = None) -> str:
    """Remove as paginas indicadas (ex.: '2-4,7') do PDF."""
    with fitz.open(files[0]) as doc:
        indices = parse_page_ranges(_require_pages(options), doc.page_count)
        doc.delete_pages(indices)
        doc.save(output, garbage=4, deflate=True)
    return output


def extract_pages(files: list[str], output: str, options: dict | None = None) -> str:
    """Gera um PDF novo contendo apenas as paginas indicadas."""
    with fitz.open(files[0]) as doc:
        indices = parse_page_ranges(_require_pages(options), doc.page_count)
        doc.select(indices)
        doc.save(output, garbage=4, deflate=True)
    return output


def compress_pdf(files: list[str], output: str, options: dict | None = None) -> str:
    """Reduz o tamanho do PDF: recomprime imagens e subconjeta fontes."""
    with fitz.open(files[0]) as doc:
        try:
            # Imagens acima de 150 dpi viram JPEG q70 em ~150 dpi.
            doc.rewrite_images(dpi_threshold=150, dpi_target=150, quality=70)
        except Exception:
            pass  # documentos sem imagens podem falhar — segue com o save
        try:
            doc.subset_fonts(fallback=True)
        except Exception:
            pass
        doc.save(output, garbage=4, deflate=True, clean=True)
    return output


def repair_pdf(files: list[str], output: str, options: dict | None = None) -> str:
    """Tenta reparar um PDF corrompido regravando a estrutura interna."""
    try:
        with fitz.open(files[0]) as doc:
            doc.save(output, garbage=4, deflate=True)
    except Exception as exc:
        raise ValueError(
            f"Nao foi possivel reparar o arquivo: {exc}"
        ) from exc
    return output
