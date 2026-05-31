# pdf_reader.py

import base64
import io
from pypdf import PdfReader


def extract_text_from_pdf_b64(pdf_b64: str) -> str:
    """Recebe um PDF em base64, retorna o texto extraído."""
    pdf_bytes = base64.b64decode(pdf_b64)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages).strip()


def extract_text_from_multiple_pdfs(pdfs_b64: list[str]) -> str:
    """Recebe uma lista de PDFs em base64, retorna o texto de todos concatenado."""
    texts = []
    for i, pdf_b64 in enumerate(pdfs_b64, 1):
        text = extract_text_from_pdf_b64(pdf_b64)
        texts.append(f"--- Holerite {i} ---\n{text}")
    return "\n\n".join(texts)