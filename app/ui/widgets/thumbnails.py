"""Geracao de miniaturas dos arquivos e paginas de PDF."""
from pathlib import Path

import pymupdf
import qtawesome as qta
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap

from app.ui import theme

THUMB_SIZE = QSize(120, 160)
PREVIEW_SIZE = QSize(1200, 1000)


def make_thumbnail(path: str) -> QIcon:
    """Primeira pagina renderizada (PDF) ou a propria imagem, como icone."""
    try:
        if Path(path).suffix.lower() == ".pdf":
            return _pdf_thumbnail(path)
        return _image_thumbnail(path)
    except Exception:
        return _fallback_icon(path)


def page_thumbnail(doc: "pymupdf.Document", index: int, rotation: int = 0) -> QIcon:
    """Renderiza uma pagina especifica do documento, com rotacao opcional."""
    page = doc.load_page(index)
    zoom = min(
        THUMB_SIZE.width() / page.rect.width,
        THUMB_SIZE.height() / page.rect.height,
    )
    matrix = pymupdf.Matrix(zoom, zoom).prerotate(rotation)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    return fitz_pixmap_to_icon(pix)


def fitz_pixmap_to_icon(pix: "pymupdf.Pixmap") -> QIcon:
    return QIcon(_bordered(fitz_pixmap_to_qpixmap(pix)))


def fitz_pixmap_to_qpixmap(pix: "pymupdf.Pixmap") -> QPixmap:
    image = QImage(
        pix.samples,
        pix.width,
        pix.height,
        pix.stride,
        QImage.Format.Format_RGB888,
    )
    return QPixmap.fromImage(image.copy())


def page_pixmap(
    doc: "pymupdf.Document", index: int, rotation: int = 0
) -> QPixmap:
    """Renderiza uma pagina em tamanho grande (para a lupa/preview)."""
    page = doc.load_page(index)
    zoom = min(
        PREVIEW_SIZE.width() / page.rect.width,
        PREVIEW_SIZE.height() / page.rect.height,
    )
    matrix = pymupdf.Matrix(zoom, zoom).prerotate(rotation)
    return fitz_pixmap_to_qpixmap(page.get_pixmap(matrix=matrix, alpha=False))


def file_preview(path: str) -> QPixmap:
    """Imagem grande para preview: 1a pagina do PDF ou a propria imagem."""
    if Path(path).suffix.lower() == ".pdf":
        with pymupdf.open(path) as doc:
            return page_pixmap(doc, 0)
    pixmap = QPixmap(path)
    if pixmap.isNull():
        raise ValueError(f"Imagem invalida: {path}")
    return pixmap.scaled(
        PREVIEW_SIZE,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _bordered(pixmap: QPixmap) -> QPixmap:
    """Desenha um contorno fino na miniatura (delimita a pagina)."""
    painter = QPainter(pixmap)
    painter.setPen(QPen(QColor(theme.THUMB_BORDER), 1))
    painter.drawRect(pixmap.rect().adjusted(0, 0, -1, -1))
    painter.end()
    return pixmap


def _pdf_thumbnail(path: str) -> QIcon:
    with pymupdf.open(path) as doc:
        return page_thumbnail(doc, 0)


def _image_thumbnail(path: str) -> QIcon:
    pixmap = QPixmap(path)
    if pixmap.isNull():
        raise ValueError(f"Imagem invalida: {path}")
    scaled = pixmap.scaled(
        THUMB_SIZE,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    return QIcon(_bordered(scaled))


def _fallback_icon(path: str) -> QIcon:
    if Path(path).suffix.lower() == ".pdf":
        return qta.icon("fa5s.file-pdf", color=theme.PRIMARY)
    return qta.icon("fa5s.file-image", color=theme.PRIMARY)
