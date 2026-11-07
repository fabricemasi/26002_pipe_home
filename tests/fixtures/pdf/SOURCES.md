# Documents de test du module PDF (provenance)

Tous publics et légitimement disponibles ; utilisés seulement par les tests (`tests/test_pdf_*.py`).

| Fichier | Nature | Source |
|---|---|---|
| `simple_xfa.pdf` | XFA minimal | Corpus de tests de PDFium : `testing/resources/simple_xfa.pdf` (pdfium.googlesource.com, licence BSD) |
| `xfa_issue14315.pdf` | XFA dessin | Corpus de tests de pdf.js : `test/pdfs/xfa_issue14315.pdf` (github.com/mozilla/pdf.js, Apache-2.0) |
| `xfa_filled_imm1344e.pdf` | XFA DYNAMIQUE réel, rempli (IRCC, IMM 1344, « Please wait… » ailleurs) | Corpus de pdf.js : `test/pdfs/xfa_filled_imm1344e.pdf` |
| `xfa_fish_licence.pdf` | XFA DYNAMIQUE réel, CHIFFRÉ AES-128, droits d'usage /Perms (ACIA, licence d'exportation de poisson) | Lien du corpus de pdf.js `xfa_fish_licence.pdf.link` -> archive web.archive.org du formulaire c5704 de l'ACIA |
| `xfa_hsbc_closure.pdf` | XFA réel (HSBC France, clôture de compte) | Lien du corpus de pdf.js `xfa_hsbc_closure.pdf.link` -> archive web.archive.org |

Autres formulaires XFA réels référencés par pdf.js (non téléchargés : limite de débit de web.archive.org au
moment de la mission) : `xfa_imm5257e.pdf.link`, `xfa_imm1295e.pdf.link`, `xfa_annual_expense_report.pdf.link`,
`xfa_dhl_shipment.pdf.link`, `xfa_candidate_petitions.pdf.link`, `xfa_annual_voting_survey.pdf.link`.
