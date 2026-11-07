"""Protection et signatures (sans Qt).

- CAVIARDAGE RÉEL (PyMuPDF `apply_redactions`) : le texte, les pixels d'image et les tracés sous les zones sont
  SUPPRIMÉS du contenu (pas un rectangle noir posé dessus) ; `verify_redaction` relit la page et vérifie qu'aucun
  caractère ne reste dans les zones, et que les textes caviardés n'apparaissent plus nulle part dans la page.
- Chiffrement AES-256 (mot de passe d'ouverture et / ou du propriétaire, permissions), retrait du chiffrement,
  retrait des métadonnées (Info + XMP).
- Signature VISUELLE : une image posée dans le contenu de la page. Elle n'apporte AUCUNE garantie
  cryptographique (dit tel quel dans l'interface).
- Signature NUMÉRIQUE (pyHanko) : certificat PKCS#12, champ de signature, mise à jour incrémentale (PAdES de base).
  Vérification : intégrité du condensat, couverture du document, modifications après signature, chaîne de
  confiance vers les autorités du magasin Windows « Racines de confiance » ; révocation NON vérifiée (aucun accès
  réseau par défaut).
"""
from __future__ import annotations

import io


class SecurityError(ValueError):
    pass


def _open(data: bytes, password: str | None = None):
    import pymupdf
    doc = pymupdf.open(stream=data, filetype="pdf")
    if doc.needs_pass:
        if not password or not doc.authenticate(password):
            doc.close()
            raise SecurityError("mot de passe requis")
    return doc


def _save(doc, **kw) -> bytes:
    out = io.BytesIO()
    doc.save(out, garbage=kw.pop("garbage", 1), deflate=True, **kw)
    doc.close()
    return out.getvalue()


def _rect(page, r):
    import pymupdf
    rect = pymupdf.Rect(r) * page.derotation_matrix
    rect.normalize()
    return rect


# -- caviardage --

def redact(data: bytes, items: list[tuple[int, tuple]], fill=(0, 0, 0), password: str | None = None) -> tuple[bytes, dict]:
    """Supprime le contenu sous les zones [(page, rect en points affichés)] ; renvoie (octets, rapport)."""
    import pymupdf
    doc = _open(data, password)
    removed: dict[int, list[str]] = {}
    for page_index in sorted({p for p, _ in items}):
        page = doc[page_index]
        rects = [_rect(page, r) for p, r in items if p == page_index]
        removed[page_index] = [page.get_textbox(r).strip() for r in rects]
        for r in rects:
            page.add_redact_annot(r, fill=fill)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                              graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                              text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    out = _save(doc, garbage=3, clean=True)
    report = verify_redaction(out, items, removed)
    if not report["ok"]:
        raise SecurityError("vérification du caviardage ÉCHOUÉE : " + "; ".join(report["problems"]))
    return out, report


def verify_redaction(data: bytes, items, removed=None) -> dict:
    """Relit le document caviardé : aucun caractère dans les zones, textes retirés introuvables dans la page."""
    import pymupdf
    doc = pymupdf.open(stream=data, filetype="pdf")
    problems = []
    try:
        for page_index, r in items:
            page = doc[page_index]
            left = page.get_textbox(_rect(page, r)).strip()
            if left:
                problems.append("page %d : texte encore présent (« %s »)" % (page_index + 1, left[:40]))
        for page_index, texts in (removed or {}).items():
            whole = doc[page_index].get_text("text")
            for text in texts:
                for word in (w for w in text.split() if len(w) >= 4):
                    if word in whole:
                        problems.append("page %d : « %s » toujours lisible" % (page_index + 1, word))
    finally:
        doc.close()
    return {"ok": not problems, "problems": problems, "zones": len(items)}


# -- chiffrement, métadonnées --

PERMISSIONS = {"print": "impression", "modify": "modification", "copy": "copie", "annotate": "commentaires",
               "fill": "remplissage des formulaires", "assemble": "assemblage des pages", "print_hq": "impression HD"}


def encrypt(data: bytes, user_pw: str, owner_pw: str, allowed=("print", "fill", "annotate", "print_hq"),
            password: str | None = None) -> bytes:
    import pymupdf
    if not (user_pw or owner_pw):
        raise SecurityError("au moins un mot de passe")
    bits = {"print": pymupdf.PDF_PERM_PRINT, "modify": pymupdf.PDF_PERM_MODIFY, "copy": pymupdf.PDF_PERM_COPY,
            "annotate": pymupdf.PDF_PERM_ANNOTATE, "fill": pymupdf.PDF_PERM_FORM,
            "assemble": pymupdf.PDF_PERM_ASSEMBLE, "print_hq": pymupdf.PDF_PERM_PRINT_HQ}
    perms = pymupdf.PDF_PERM_ACCESSIBILITY
    for name in allowed:
        perms |= bits.get(name, 0)
    doc = _open(data, password)
    return _save(doc, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=user_pw or "", owner_pw=owner_pw or user_pw,
                 permissions=perms)


def decrypt(data: bytes, password: str | None = None) -> bytes:
    import pymupdf
    doc = _open(data, password)
    return _save(doc, encryption=pymupdf.PDF_ENCRYPT_NONE)


def strip_metadata(data: bytes, password: str | None = None) -> bytes:
    doc = _open(data, password)
    doc.set_metadata({})
    try:
        doc.del_xml_metadata()
    except Exception:                                       # noqa: BLE001 - pas de XMP
        pass
    return _save(doc)


def metadata(data: bytes) -> dict:
    import pymupdf
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        meta = dict(doc.metadata or {})
        meta["xmp"] = bool(doc.get_xml_metadata())
        return meta
    finally:
        doc.close()


# -- signatures --

def insert_image(data: bytes, page_index: int, rect, image: bytes, password: str | None = None) -> bytes:
    """Signature VISUELLE : image posée dans le contenu (aucune valeur cryptographique)."""
    doc = _open(data, password)
    page = doc[page_index]
    page.insert_image(_rect(page, rect), stream=image, keep_proportion=True, overlay=True)
    return _save(doc)


def _pdf_box(data: bytes, page_index: int, rect):
    """Rectangle (points affichés, origine en haut) -> repère PDF de la page (origine en bas à gauche)."""
    import pymupdf
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        page = doc[page_index]
        r = _rect(page, rect) * ~page.transformation_matrix
        r.normalize()
        return (r.x0, r.y0, r.x1, r.y1)
    finally:
        doc.close()


def sign(data: bytes, pkcs12: bytes, passphrase: str, *, field: str = "Signature1", page_index: int = 0,
         rect=None, reason: str = "", location: str = "", name: str = "") -> bytes:
    """Signature NUMÉRIQUE (pyHanko) : ajoute (si besoin) un champ de signature et signe en mise à jour
    incrémentale. Le document ne doit pas être chiffré."""
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import fields, signers
    try:
        signer = signers.SimpleSigner.load_pkcs12_data(pkcs12, other_certs=[],
                                                       passphrase=passphrase.encode("utf-8") if passphrase else None)
    except AttributeError:                                  # anciennes versions : par fichier
        import tempfile, os
        with tempfile.NamedTemporaryFile(delete=False, suffix=".p12") as tmp:
            tmp.write(pkcs12)
        try:
            signer = signers.SimpleSigner.load_pkcs12(tmp.name, passphrase.encode("utf-8") if passphrase else None)
        finally:
            os.unlink(tmp.name)
    if signer is None:
        raise SecurityError("certificat ou phrase de passe incorrects")
    writer = IncrementalPdfFileWriter(io.BytesIO(data), strict=False)
    if writer.security_handler is not None:
        raise SecurityError("document chiffré : retirez le chiffrement avant de signer")
    existing = {name for name, _, _ in fields.enumerate_sig_fields(writer)}
    if field not in existing:
        box = _pdf_box(data, page_index, rect) if rect is not None else None
        fields.append_signature_field(writer, fields.SigFieldSpec(sig_field_name=field, on_page=page_index,
                                                                  box=box))
    meta = signers.PdfSignatureMetadata(field_name=field, reason=reason or None, location=location or None,
                                        name=name or None)
    out = signers.sign_pdf(writer, meta, signer=signer)
    return out.getvalue()


def windows_trust_roots() -> list:
    """Certificats racines du magasin Windows (ssl.enum_certificates), pour la chaîne de confiance."""
    import ssl
    from asn1crypto import x509
    roots = []
    for store in ("ROOT", "CA"):
        try:
            for der, encoding, _trust in ssl.enum_certificates(store):
                if encoding == "x509_asn":
                    try:
                        roots.append(x509.Certificate.load(der))
                    except Exception:                       # noqa: BLE001
                        pass
        except (AttributeError, OSError):
            pass
    return roots


def verify(data: bytes, extra_roots=()) -> list[dict]:
    """État de chaque signature : intacte (condensat), valide (cryptographie), approuvée (chaîne de confiance),
    couverture, modifications après signature, signataire, date déclarée."""
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext
    reader = PdfFileReader(io.BytesIO(data), strict=False)
    roots = windows_trust_roots() + list(extra_roots)
    out = []
    for sig in reader.embedded_signatures:
        item = {"field": sig.field_name}
        try:
            ctx = ValidationContext(trust_roots=roots, allow_fetching=False)
            status = validate_pdf_signature(sig, ctx)
            item.update({"intact": bool(status.intact), "valid": bool(status.valid),
                         "trusted": bool(status.trusted), "coverage": str(status.coverage).rsplit(".", 1)[-1],
                         "modification": str(getattr(status, "modification_level", "")).rsplit(".", 1)[-1],
                         "signer": status.signing_cert.subject.human_friendly if status.signing_cert else "",
                         "time": str(status.signer_reported_dt or ""), "summary": status.summary()})
        except Exception as exc:                            # noqa: BLE001
            item.update({"intact": False, "valid": False, "trusted": False, "error": str(exc)})
        out.append(item)
    return out


def self_signed_pkcs12(common_name: str, passphrase: str) -> bytes:
    """Certificat AUTO-SIGNÉ (essais, signatures personnelles : non approuvé par les lecteurs tiers)."""
    import datetime as dt
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = cx509.Name([cx509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (cx509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(cx509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=3650))
            .add_extension(cx509.KeyUsage(digital_signature=True, content_commitment=True, key_encipherment=False,
                                          data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                          crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(cx509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
            .add_extension(cx509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    enc = serialization.BestAvailableEncryption(passphrase.encode("utf-8")) if passphrase else \
        serialization.NoEncryption()
    return pkcs12.serialize_key_and_certificates(common_name.encode("utf-8"), key, cert, None, enc)
