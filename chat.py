
import calendar
import re
import unicodedata
from datetime import datetime

from fastembed import TextEmbedding
from qdrant_client import QdrantClient, models

QDRANT_URL = "http://localhost:6333"
QDRANT_API_KEY = None
COLLECTION = "invoices"
MODELE = "sentence-transformers/all-MiniLM-L6-v2"   # le même que dans ingestion.py

client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
modele = TextEmbedding(MODELE)

# Nom affiché de chaque métadonnée
LIBELLES = {
    "date": "Date", "bill_to": "Bill To", "ship_to": "Ship To", "ship_mode": "Ship Mode",
    "item": "Article", "quantity": "Quantité", "rate": "Prix unitaire", "amount": "Amount",
    "discount": "Discount", "shipping": "Shipping", "total": "Total",
}

# Mots de la question (sans accents) -> métadonnée demandée
MOTS_CLES = {
    "quantity": ["quantite", "quantity", "qty", "combien d'articles", "nombre d'articles"],
    "total": ["total"],
    "discount": ["discount", "remise", "reduction"],
    "shipping": ["shipping", "frais de port", "frais de livraison", "frais d'expedition"],
    "amount": ["amount", "montant"],
    "rate": ["prix unitaire", "rate", "unit price", "tarif"],
    "date": ["date", "quand"],
    "bill_to": ["bill to", "client", "facture a", "acheteur", "nom"],
    "ship_to": ["ship to", "adresse", "destination", "ville", "pays", "livre a"],
    "ship_mode": ["ship mode", "mode de livraison", "mode d'expedition", "mode"],
    "item": ["article", "produit", "item"],
}

MOIS = {"janvier": 1, "january": 1, "fevrier": 2, "february": 2, "mars": 3, "march": 3,
        "avril": 4, "april": 4, "mai": 5, "may": 5, "juin": 6, "june": 6,
        "juillet": 7, "july": 7, "aout": 8, "august": 8, "septembre": 9, "september": 9,
        "octobre": 10, "october": 10, "novembre": 11, "november": 11,
        "decembre": 12, "december": 12}


def normaliser(texte):
    """Minuscules et sans accents : 'Quantité' -> 'quantite'."""
    texte = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


def trouver_champs(question):
    """Quelles métadonnées la question demande-t-elle ? (liste vide = toutes)"""
    champs = []
    for champ, mots in MOTS_CLES.items():
        if any(re.search(r"\b" + mot + r"s?\b", question) for mot in mots):
            champs.append(champ)
    return champs


def trouver_dates(question):
    """Repère les dates de la question. Renvoie (debut, fin, question sans les dates)."""
    periodes = []          # liste de (premier jour, dernier jour)

    def jour(a, m, j):
        periodes.append((datetime(a, m, j), datetime(a, m, j)))

    def retirer(motif, action):
        nonlocal question
        for m in re.finditer(motif, question):
            action(m)
        question = re.sub(motif, " ", question)

    # 2012-03-06
    retirer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b",
            lambda m: jour(int(m[1]), int(m[2]), int(m[3])))
    # 06/03/2012  (jour/mois/année)
    retirer(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b",
            lambda m: jour(int(m[3]), int(m[2]), int(m[1])))

    # "6 mars 2012" ou "mars 2012"
    def mois_annee(m):
        annee, mois = int(m[3]), MOIS[m[2]]
        if m[1]:
            jour(annee, mois, int(m[1]))
        else:
            dernier = calendar.monthrange(annee, mois)[1]
            periodes.append((datetime(annee, mois, 1), datetime(annee, mois, dernier)))
    retirer(r"\b(?:(\d{1,2})\s+)?(" + "|".join(MOIS) + r")\s+(\d{4})\b", mois_annee)

    if not periodes:
        return None, None, question
    debut = min(p[0] for p in periodes)
    fin = max(p[1] for p in periodes)
    if len(periodes) == 1:
        if re.search(r"\b(avant|before|jusqu)", question):
            debut = None
        elif re.search(r"\b(apres|depuis|after|a partir)", question):
            fin = None
    return debut, fin, question


def chercher(question):
    """Renvoie (factures trouvées, message d'information)."""
    debut, fin, reste = trouver_dates(question)

    for nombre in re.findall(r"\d{2,}", reste):
        # a) Le nombre est un code facture ? -> on prend cette facture, rien d'autre
        points = client.retrieve(COLLECTION, ids=[int(nombre)])
        if points:
            return [points[0].payload], ""
        # b) Sinon, un nombre comme 2012 est une année
        if debut is None and fin is None and 1990 <= int(nombre) <= 2100:
            debut, fin = datetime(int(nombre), 1, 1), datetime(int(nombre), 12, 31)

    # c) Filtre sur la date, si la question en contient une
    filtre, info = None, ""
    if debut or fin:
        filtre = models.Filter(must=[
            models.FieldCondition(key="date", range=models.DatetimeRange(gte=debut, lte=fin)),
        ])
        nb = client.count(COLLECTION, count_filter=filtre, exact=True).count
        du = debut.strftime("%d/%m/%Y") if debut else "le début"
        au = fin.strftime("%d/%m/%Y") if fin else "la fin"
        info = f"{nb} facture(s) entre {du} et {au}. Les plus proches de votre question :"

    # d) Recherche sémantique (par le sens), limitée à la période si filtre
    vecteur = list(modele.embed([question]))[0].tolist()
    resultat = client.query_points(COLLECTION, query=vecteur, query_filter=filtre, limit=5)
    return [p.payload for p in resultat.points], info


def afficher(factures, champs):
    """Affiche seulement les champs demandés (ou tous si aucun n'est précisé)."""
    for f in factures:
        print(f"\nFacture #{f['invoice_code']}")
        for champ in (champs or LIBELLES):
            print(f"  {LIBELLES[champ]:<14}: {f[champ]}")


if __name__ == "__main__":
    print("Chat factures - tapez votre question (ou 'quit' pour sortir)")
    while True:
        question = normaliser(input("\nVous : ").strip())
        if question in ("quit", "exit", "q"):
            break
        if not question:
            continue
        factures, info = chercher(question)
        if info:
            print(info)
        if not factures:
            print("Aucune facture trouvée.")
        afficher(factures, trouver_champs(question))