"""Module PDF de PIPE FMZ : lecture, remplissage (AcroForm ET XFA), conception de formulaires, annotations,
pages, OCR, signatures, protection, export. Carte : docs/agents/fm_pdf.md ; suivi : PDF_MODULE_PROGRESS.md.

Ce fichier reste MINIMAL (aucun import lourd) : il est lu par la fenêtre principale à chaque clic de sélection."""
from pathlib import Path

EXTENSIONS = (".pdf",)


def is_pdf_file(path) -> bool:
    return Path(path).suffix.lower() in EXTENSIONS
