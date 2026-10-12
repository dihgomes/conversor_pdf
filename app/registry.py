"""Registro das ferramentas disponiveis no app.

Cada Tool liga um card/tela da UI a uma funcao do app.core.
Adicionar uma ferramenta simples = funcao no core + item em TOOLS.
Ferramentas com tela propria (ex.: organize) ganham entrada em
PAGE_OVERRIDES na main_window.
"""
from dataclasses import dataclass
from typing import Callable

from app.core import converters, pdf_tools

PDF_FILTER = "Arquivos PDF (*.pdf)"
IMG_FILTER = "Imagens (*.png *.jpg *.jpeg *.bmp *.webp)"
HTML_FILTER = "Paginas HTML (*.html *.htm)"

# Ferramentas cujo "output" e um diretorio (em vez de um arquivo).
OUTPUT_IS_DIR = "dir"


# Categorias exibidas na sidebar e na tela inicial.
CAT_ORGANIZE = "ORGANIZAR PDF"
CAT_OPTIMIZE = "OTIMIZAR PDF"
CAT_TO_PDF = "CONVERTER EM PDF"
CAT_FROM_PDF = "CONVERTER DE PDF"


@dataclass(frozen=True)
class Tool:
    id: str
    title: str
    description: str
    icon: str
    handler: Callable | None
    multiple_files: bool
    file_filter: str
    category: str = CAT_ORGANIZE
    output_mode: str = "file"  # "file" | OUTPUT_IS_DIR
    output_suffix: str = ".pdf"
    page_range: bool = False       # exibe campo "Paginas: 1-3,5"
    run_on_main_thread: bool = False  # para handlers que usam classes de GUI


TOOLS: list[Tool] = [
    # ----------------------------------------------------- Organizar PDF
    Tool(
        id="merge",
        title="Juntar PDF",
        description="Combine varios PDFs em um so arquivo",
        icon="fa5s.object-group",
        handler=pdf_tools.merge_pdfs,
        multiple_files=True,
        file_filter=PDF_FILTER,
    ),
    Tool(
        id="split",
        title="Dividir PDF",
        description="Separe cada pagina em um arquivo",
        icon="fa5s.cut",
        handler=pdf_tools.split_pdf,
        multiple_files=False,
        file_filter=PDF_FILTER,
        output_mode=OUTPUT_IS_DIR,
    ),
    Tool(
        id="remove_pages",
        title="Remover paginas",
        description="Exclua paginas especificas do PDF",
        icon="fa5s.trash-alt",
        handler=pdf_tools.remove_pages,
        multiple_files=False,
        file_filter=PDF_FILTER,
        page_range=True,
    ),
    Tool(
        id="extract_pages",
        title="Extrair paginas",
        description="Salve paginas selecionadas em um novo PDF",
        icon="fa5s.file-export",
        handler=pdf_tools.extract_pages,
        multiple_files=False,
        file_filter=PDF_FILTER,
        page_range=True,
    ),
    Tool(
        id="organize",
        title="Organizar PDF",
        description="Reordene, gire e remova paginas visualmente",
        icon="fa5s.th-large",
        handler=None,
        multiple_files=False,
        file_filter=PDF_FILTER,
    ),
    Tool(
        id="lote_ortopedia",
        title="Organizar em Lote",
        description="Monte o dossie de ortopedia de cada paciente a partir de uma pasta raiz",
        icon="fa5s.sitemap",
        handler=None,
        multiple_files=False,
        file_filter=PDF_FILTER,
    ),
    # ----------------------------------------------------- Otimizar PDF
    Tool(
        id="compress",
        category=CAT_OPTIMIZE,
        title="Comprimir PDF",
        description="Reduza o tamanho do arquivo",
        icon="fa5s.compress-arrows-alt",
        handler=pdf_tools.compress_pdf,
        multiple_files=False,
        file_filter=PDF_FILTER,
    ),
    Tool(
        id="repair",
        category=CAT_OPTIMIZE,
        title="Reparar PDF",
        description="Tente recuperar um PDF corrompido",
        icon="fa5s.tools",
        handler=pdf_tools.repair_pdf,
        multiple_files=False,
        file_filter=PDF_FILTER,
    ),
    # -------------------------------------------------- Converter em PDF
    Tool(
        id="img2pdf",
        category=CAT_TO_PDF,
        title="Imagem para PDF",
        description="Converta JPG, PNG e outras imagens em PDF",
        icon="fa5s.file-image",
        handler=converters.images_to_pdf,
        multiple_files=True,
        file_filter=IMG_FILTER,
    ),
    Tool(
        id="html2pdf",
        category=CAT_TO_PDF,
        title="HTML para PDF",
        description="Converta uma pagina HTML em PDF",
        icon="fa5s.file-code",
        handler=converters.html_to_pdf,
        multiple_files=False,
        file_filter=HTML_FILTER,
    ),
    # -------------------------------------------------- Converter de PDF
    Tool(
        id="pdf2jpg",
        category=CAT_FROM_PDF,
        title="PDF para JPG",
        description="Exporte cada pagina como imagem JPG",
        icon="fa5s.images",
        handler=converters.pdf_to_jpg,
        multiple_files=False,
        file_filter=PDF_FILTER,
        output_mode=OUTPUT_IS_DIR,
    ),
    Tool(
        id="pdf2word",
        category=CAT_FROM_PDF,
        title="PDF para Word",
        description="Converta PDF em documento .docx editavel",
        icon="fa5s.file-word",
        handler=converters.pdf_to_word,
        multiple_files=False,
        file_filter=PDF_FILTER,
        output_suffix=".docx",
    ),
    Tool(
        id="pdf2ppt",
        category=CAT_FROM_PDF,
        title="PDF para PowerPoint",
        description="Cada pagina vira um slide em .pptx",
        icon="fa5s.file-powerpoint",
        handler=converters.pdf_to_pptx,
        multiple_files=False,
        file_filter=PDF_FILTER,
        output_suffix=".pptx",
    ),
    Tool(
        id="pdf2excel",
        category=CAT_FROM_PDF,
        title="PDF para Excel",
        description="Extraia tabelas do PDF para .xlsx",
        icon="fa5s.file-excel",
        handler=converters.pdf_to_excel,
        multiple_files=False,
        file_filter=PDF_FILTER,
        output_suffix=".xlsx",
    ),
]


def get_tool(tool_id: str) -> Tool:
    for tool in TOOLS:
        if tool.id == tool_id:
            return tool
    raise KeyError(f"Ferramenta desconhecida: {tool_id}")
