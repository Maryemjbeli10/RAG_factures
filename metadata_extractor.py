
import re
from pathlib import Path

import pdfplumber

DOSSIER_PDF = "1000+ PDF_Invoice_Folder"
MOIS = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
        "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def montant(texte, motif):
    """Cherche un montant ($1,234.56) dans le texte ; renvoie 0.0 s'il est absent."""
    m = re.search(motif, texte)
    return float(m.group(1).replace(",", "")) if m else 0.0


def extraire_facture(chemin_pdf):
    """Renvoie (texte, metadonnees) pour un PDF, ou None si la facture est vide."""
    with pdfplumber.open(chemin_pdf) as pdf:
        page = pdf.pages[0]
        texte = page.extract_text()

        code = re.search(r"#\s*(\d+)", texte)
        if not code:                  # 15 PDF du dataset sont des factures vides
            return None

        # "Bill To" et "Ship To" sont deux colonnes côte à côte :
        # on découpe la page en deux zones pour ne pas mélanger les textes.
        haut = 136                    # juste sous les titres "Bill To:" / "Ship To:"
        bas = [m["top"] for m in page.extract_words() if m["text"] == "Item"][0] - 5
        bill_to = page.crop((0, haut, 175, bas)).extract_text()
        ship_to = page.crop((175, haut, 385, bas)).extract_text()

    # Date : "Mar 06 2012" -> "2012-03-06" (format que Qdrant sait filtrer)
    d = re.search(r"Date:\s*(\w{3}) (\d{1,2}) (\d{4})", texte)
    date = f"{d.group(3)}-{MOIS[d.group(1)]:02d}-{int(d.group(2)):02d}"

    # Ligne d'article : "... description   quantité  $prix  $montant"
    bloc = re.search(r"Rate Amount\n(.*?)\nSubtotal:", texte, re.S).group(1)
    ligne = re.search(r"\s(\d+)\s+\$([\d,.]+)\s+\$([\d,.]+)", bloc)
    lignes = bloc.replace(ligne.group(0), "").split("\n")
    article = " ".join(lignes[:-1])          # la dernière ligne = catégorie + référence

    metadonnees = {
        "invoice_code": code.group(1),
        "date": date,
        "bill_to": bill_to.replace("\n", " "),
        "ship_to": ship_to.replace("-\n", "-").replace("\n", " "),
        "ship_mode": re.search(r"Ship Mode:\s*(.+)", texte).group(1).strip(),
        "item": article,
        "quantity": int(ligne.group(1)),
        "rate": float(ligne.group(2).replace(",", "")),              # prix unitaire
        "amount": float(ligne.group(3).replace(",", "")),            # colonne Amount
        "discount": montant(texte, r"Discount.*?:\s*\$([\d,.]+)"),   # 0.0 si pas de remise
        "shipping": montant(texte, r"Shipping:\s*\$([\d,.]+)"),
        "total": montant(texte, r"\nTotal:\s*\$([\d,.]+)"),
    }
    return texte, metadonnees


def extraire_dossier(dossier=DOSSIER_PDF):
    """Lit tous les PDF du dossier. Renvoie une liste de (texte, metadonnees)."""
    factures = []
    for chemin in sorted(Path(dossier).glob("*.pdf")):
        resultat = extraire_facture(chemin)
        if resultat:
            factures.append(resultat)
    return factures


if __name__ == "__main__":
    factures = extraire_dossier()
    print(len(factures), "factures lues\n")
    texte, meta = factures[0]
    print("--- Texte de la première facture\n" + texte)
    print("\n--- Métadonnées")
    for cle, valeur in meta.items():
        print(f"  {cle:<13}: {valeur}")