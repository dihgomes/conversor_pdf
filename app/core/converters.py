"""Conversoes entre PDF e outros formatos.

Mesma assinatura de app.core.pdf_tools:
    handler(files: list[str], output: str, options: dict | None = None)
"""
import tempfile
from pathlib import Path

import pymupdf as fitz

# Fator de zoom para renderizar paginas como imagem (~144 dpi).
RENDER_ZOOM = 2.0


def images_to_pdf(files: list[str], output: str, options: dict | None = None) -> str:
    """Converte imagens (png, jpg, bmp, webp) em um PDF, uma por pagina."""
    doc = fitz.open()
    try:
        for path in files:
            with fitz.open(path) as img:
                pdf_bytes = img.convert_to_pdf()
            with fitz.open("pdf", pdf_bytes) as img_pdf:
                doc.insert_pdf(img_pdf)
        doc.save(output)
    finally:
        doc.close()
    return output


def pdf_to_jpg(files: list[str], output_dir: str, options: dict | None = None) -> list[str]:
    """Renderiza cada pagina do PDF como imagem JPG na pasta de destino."""
    outputs: list[str] = []
    stem = Path(files[0]).stem
    matrix = fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM)
    with fitz.open(files[0]) as doc:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            out = str(Path(output_dir) / f"{stem}_pagina_{i + 1}.jpg")
            pix.save(out)
            outputs.append(out)
    return outputs


def pdf_to_word(files: list[str], output: str, options: dict | None = None) -> str:
    """Converte PDF em documento Word (.docx) via pdf2docx."""
    from pdf2docx import Converter

    converter = Converter(files[0])
    try:
        converter.convert(output)
    finally:
        converter.close()
    return output


def pdf_to_pptx(files: list[str], output: str, options: dict | None = None) -> str:
    """Gera um .pptx com cada pagina do PDF como um slide (imagem)."""
    from pptx import Presentation
    from pptx.util import Emu

    prs = Presentation()
    blank_layout = prs.slide_layouts[6]
    matrix = fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM)

    with fitz.open(files[0]) as doc, tempfile.TemporaryDirectory() as tmp:
        # 1 ponto PDF = 12700 EMU
        prs.slide_width = Emu(int(doc[0].rect.width * 12700))
        prs.slide_height = Emu(int(doc[0].rect.height * 12700))
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img_path = str(Path(tmp) / f"pagina_{i + 1}.png")
            pix.save(img_path)
            slide = prs.slides.add_slide(blank_layout)
            slide.shapes.add_picture(
                img_path, 0, 0,
                width=prs.slide_width, height=prs.slide_height,
            )
    prs.save(output)
    return output


def html_to_pdf(files: list[str], output: str, options: dict | None = None) -> str:
    """Converte um arquivo .html em PDF via xhtml2pdf (suporta CSS).

    `path` permite resolver recursos relativos (imagens, css) do HTML.
    """
    from xhtml2pdf import pisa

    html = Path(files[0]).read_text(encoding="utf-8")
    with open(output, "wb") as pdf_file:
        result = pisa.CreatePDF(html, dest=pdf_file, path=files[0])
    if result.err:
        raise ValueError(f"Nao foi possivel converter o HTML ({result.err} erro(s)).")
    return output


def pdf_to_excel(files: list[str], output: str, options: dict | None = None) -> str:
    """Extrai tabelas do PDF para uma planilha .xlsx (uma aba por pagina).

    Tenta primeiro o detector do PyMuPDF (`find_tables`), que cobre
    tabelas com e sem bordas; se nao achar nada, cai para o pdfplumber.
    Paginas sem tabela recebem o texto (colunas separadas por 2+ espacos).
    """
    import re

    import pdfplumber
    from openpyxl import Workbook

    workbook = Workbook()
    with fitz.open(files[0]) as doc, pdfplumber.open(files[0]) as pdf:
        for i in range(doc.page_count):
            sheet = workbook.active if i == 0 else workbook.create_sheet()
            sheet.title = f"Pagina {i + 1}"

            tables = [t.extract() for t in doc[i].find_tables()]
            if not tables:
                tables = pdf.pages[i].extract_tables()

            row = 1
            if not tables:
                for line in (doc[i].get_text() or "").splitlines():
                    cols = [c for c in re.split(r"\s{2,}", line.strip()) if c]
                    for col, value in enumerate(cols or [""], start=1):
                        sheet.cell(row=row, column=col, value=value)
                    row += 1
            else:
                for table in tables:
                    for table_row in table:
                        for col, value in enumerate(table_row, start=1):
                            if value is not None:
                                sheet.cell(row=row, column=col, value=str(value))
                        row += 1
                    row += 1
    workbook.save(output)
    return output
