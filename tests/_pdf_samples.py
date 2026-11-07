"""Documents de test du module PDF : fabriqués par le module lui-même (concepteur AcroForm, PyMuPDF) ou pris dans
`tests/fixtures/pdf/` (corpus publics : tests de PDFium et de pdf.js, voir tests/fixtures/pdf/SOURCES.md)."""
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pdf"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def has_fixture(name: str) -> bool:
    return (FIXTURES / name).is_file()


def sample_specs():
    from fm_pdf.acroform import FieldSpec as S
    return [S("text", "nom", 0, (72, 72, 300, 92), tooltip="Votre nom", required=True),
            S("number", "qte", 0, (72, 110, 160, 130), decimals=2, min_value=0, max_value=1000),
            S("number", "prix", 0, (180, 110, 270, 130), decimals=2),
            S("number", "total", 0, (290, 110, 380, 130), readonly=True, calc_op="PRD", calc_fields=["qte", "prix"]),
            S("date", "date", 0, (72, 150, 200, 170)),
            S("multiline", "notes", 0, (72, 190, 400, 260)),
            S("checkbox", "accord", 0, (72, 280, 86, 294), export_value="Oui"),
            S("radio", "taille", 0, (72, 310, 86, 324), export_value="S"),
            S("radio", "taille", 0, (100, 310, 114, 324), export_value="M"),
            S("radio", "taille", 0, (128, 310, 142, 324), export_value="L"),
            S("combo", "pays", 0, (72, 340, 250, 360), choices=["France", "Belgique", "Suisse"], value="France"),
            S("list", "langues", 0, (72, 380, 250, 440), choices=["Français", "English", "Deutsch"],
              multiselect=True)]


def sample_form() -> bytes:
    """Formulaire AcroForm de démonstration : texte obligatoire, nombres avec calcul, date, multiligne, case, groupe
    radio, liste déroulante, liste multiple."""
    from fm_pdf import acroform
    data, _ = acroform.add_fields(acroform.new_blank_document(), sample_specs())
    return data


def text_pdf(pages: int = 3, words: str = "Bonjour le monde") -> bytes:
    """PDF texte simple (une ligne par page + numéro) pour la lecture, la recherche, les pages."""
    import io
    import pymupdf
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), f"{words} page {i + 1}", fontsize=14)
        page.insert_text((72, 140), "Ligne de contrôle numéro %d : éléphant" % (i + 1), fontsize=11)
    out = io.BytesIO()
    doc.save(out)
    doc.close()
    return out.getvalue()


def center(rect):
    x0, y0, x1, y1 = rect
    return (x0 + x1) / 2, (y0 + y1) / 2
