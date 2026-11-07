"""Mise à jour INCRÉMENTALE d'un PDF (sans Qt) : remplacer des flux existants en AJOUTANT une section en fin de
fichier, sans toucher un seul octet d'origine (les signatures et les droits d'usage « Reader Extensions », qui
couvrent les octets déjà écrits, restent valides).

Lecture de la structure par pikepdf (qpdf) ; écriture à la main : objets + table de références (classique si la
dernière section l'est, sinon flux de références) + `/Prev`.

Fichiers CHIFFRÉS (fréquent pour les formulaires officiels : mot de passe utilisateur vide, droits restreints) :
chaque flux ajouté est chiffré avec la clé du document que qpdf a calculée (`pdf.encryption.encryption_key`),
selon ISO 32000 § 7.6.2 : RC4 (clé d'objet = MD5(clé + n° + génération)), AES-128 « AESV2 » (même dérivation +
« sAlT »), AES-256 « AESV3 » (clé du document telle quelle) ; vecteur d'initialisation aléatoire en tête, bourrage
PKCS#7. Autre gestionnaire (non /Standard, filtre de chiffrement inconnu) : `NeedsFullRewrite`.
"""
from __future__ import annotations

import io
import re
import zlib


class NeedsFullRewrite(RuntimeError):
    """La mise à jour incrémentale n'est pas possible (fichier chiffré, structure inattendue)."""


def _last_startxref(data: bytes) -> int:
    tail = data[-4096:]
    found = list(re.finditer(rb"startxref\s+(\d+)", tail))
    if not found:
        raise NeedsFullRewrite("startxref introuvable")
    return int(found[-1].group(1))


def _is_xref_stream(data: bytes, offset: int) -> bool:
    head = data[offset:offset + 64].lstrip()
    if head.startswith(b"xref"):
        return False
    if re.match(rb"\d+\s+\d+\s+obj", head):
        return True
    raise NeedsFullRewrite("section de références illisible à %d" % offset)


def repair_xref_stream_type(data: bytes) -> tuple[bytes, bool]:
    """DÉFAUT DE PDFium (chromium/8076) : sa sauvegarde INCRÉMENTALE d'un fichier à flux de références écrit le
    dernier flux SANS « /Type /XRef » (obligatoire, ISO 32000-1 § 7.5.8.2) ; qpdf le refuse (« xref not found »).
    Insérer « /Type/XRef » juste après « << » ne déplace ni le début de cet objet (cible de startxref) ni aucun
    objet qu'il référence (tous AVANT lui) : seuls ses propres octets suivants glissent. Renvoie (octets, corrigé ?)."""
    try:
        offset = _last_startxref(data)
    except NeedsFullRewrite:
        return data, False
    m = re.match(rb"(\s*\d+\s+\d+\s+obj\s*<<)", data[offset:offset + 64])
    if not m:
        return data, False
    head_end = offset + m.end()
    dict_end = data.find(b"stream", head_end)
    if dict_end < 0 or b"/Type" in data[head_end:dict_end] or b"/W" not in data[head_end:dict_end]:
        return data, False
    return data[:head_end] + b"/Type/XRef" + data[head_end:], True


def _rc4(key: bytes, data: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) & 0xFF
        s[i], s[j] = s[j], s[i]
    out = bytearray(len(data))
    i = j = 0
    for k, byte in enumerate(data):
        i = (i + 1) & 0xFF
        j = (j + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
        out[k] = byte ^ s[(s[i] + s[j]) & 0xFF]
    return bytes(out)


def _aes_cbc(key: bytes, data: bytes) -> bytes:
    import os
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    iv = os.urandom(16)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return iv + enc.update(padded) + enc.finalize()


def stream_encryptor(pdf):
    """Fonction (num, gen, octets) -> octets chiffrés pour ce document, ou None s'il n'est pas chiffré."""
    import hashlib
    if not pdf.is_encrypted:
        return None
    enc = pdf.encryption
    encrypt = pdf.trailer.get("/Encrypt")
    if encrypt is None or str(encrypt.get("/Filter")) != "/Standard":
        raise NeedsFullRewrite("gestionnaire de sécurité non standard")
    key = bytes(enc.encryption_key)
    method = str(enc.stream_method).rsplit(".", 1)[-1].lower()
    if method == "none":
        return lambda num, gen, data: data
    if method == "aesv3" or (method == "aes" and enc.R >= 5):
        return lambda num, gen, data: _aes_cbc(key, data)

    def object_key(num, gen, salt=b""):
        raw = key + num.to_bytes(4, "little")[:3] + gen.to_bytes(2, "little") + salt
        return hashlib.md5(raw).digest()[: min(len(key) + 5, 16)]
    if method == "aes":
        return lambda num, gen, data: _aes_cbc(object_key(num, gen, b"sAlT"), data)
    if method == "rc4":
        return lambda num, gen, data: _rc4(object_key(num, gen), data)
    raise NeedsFullRewrite("méthode de chiffrement inconnue : %s" % method)


def _ref(obj) -> bytes:
    num, gen = obj.objgen
    return b"%d %d R" % (num, gen)


def _hexstr(b: bytes) -> bytes:
    return b"<" + b.hex().upper().encode() + b">"


def replace_streams(data: bytes, replacements: dict[tuple[int, int], bytes]) -> bytes:
    """Renvoie `data` + une section qui redéfinit chaque objet (num, gen) comme un flux Flate de ce contenu."""
    import pikepdf

    if not replacements:
        return data
    with pikepdf.open(io.BytesIO(data)) as pdf:
        crypt = stream_encryptor(pdf)
        trailer = pdf.trailer
        encrypt_ref = None
        if crypt is not None:                          # /Encrypt indirect (cas courant) ou en ligne (jamais chiffré)
            encrypt_ref = _ref(trailer.Encrypt) if trailer.Encrypt.is_indirect else trailer.Encrypt.unparse()
        size = int(trailer.Size)
        root = _ref(trailer.Root)
        info = _ref(trailer.Info) if "/Info" in trailer and trailer.Info.is_indirect else None
        ids = [bytes(x) for x in trailer.ID] if "/ID" in trailer else None
    prev = _last_startxref(data)
    xref_stream = _is_xref_stream(data, prev)

    out = bytearray(data)
    if not out.endswith(b"\n"):
        out += b"\n"
    offsets: dict[int, tuple[int, int]] = {}
    for (num, gen), content in sorted(replacements.items()):
        packed = zlib.compress(content, 6)
        if crypt is not None:
            packed = crypt(num, gen, packed)
        offsets[num] = (len(out), gen)
        out += b"%d %d obj\n<< /Length %d /Filter /FlateDecode >>\nstream\n" % (num, gen, len(packed))
        out += packed + b"\nendstream\nendobj\n"

    def trailer_keys(new_size: int) -> bytes:
        keys = b"/Size %d /Root %s" % (new_size, root)
        if info:
            keys += b" /Info " + info
        if ids:
            keys += b" /ID [" + b"".join(_hexstr(x) for x in ids) + b"]"
        if encrypt_ref:
            keys += b" /Encrypt " + encrypt_ref
        return keys + b" /Prev %d" % prev

    if not xref_stream:
        start = len(out)
        out += b"xref\n"
        for num in sorted(offsets):
            off, gen = offsets[num]
            out += b"%d 1\n%010d %05d n \n" % (num, off, gen)
        out += b"trailer\n<< " + trailer_keys(size) + b" >>\nstartxref\n%d\n%%%%EOF\n" % start
    else:
        xnum = size                                   # nouvel objet : le flux de références lui-même
        start = len(out)
        offsets[xnum] = (start, 0)
        rows = bytearray()
        index = []
        for num in sorted(offsets):
            off, gen = offsets[num]
            rows += bytes([1]) + off.to_bytes(4, "big") + gen.to_bytes(2, "big")
            index += [num, 1]
        packed = zlib.compress(bytes(rows))
        out += (b"%d 0 obj\n<< /Type /XRef /W [1 4 2] /Index [%s] %s /Length %d /Filter /FlateDecode >>\nstream\n"
                % (xnum, b" ".join(b"%d" % v for v in index), trailer_keys(size + 1), len(packed)))
        out += packed + b"\nendstream\nendobj\nstartxref\n%d\n%%%%EOF\n" % start
    return bytes(out)
