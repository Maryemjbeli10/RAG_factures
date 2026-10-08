from fastembed import TextEmbedding
from qdrant_client import QdrantClient, models

from metadata_extractor import extraire_dossier

QDRANT_URL = "http://localhost:6333"      
QDRANT_API_KEY = None                    
COLLECTION = "invoices"
MODELE = "sentence-transformers/all-MiniLM-L6-v2"   


factures = extraire_dossier()
print(len(factures), "factures lues")

client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=60)
if not client.collection_exists(COLLECTION):
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE),
    )

# Index sur la date : permet de filtrer par période (avant / après / entre deux dates)
client.create_payload_index(
    collection_name=COLLECTION,
    field_name="date",
    field_schema=models.PayloadSchemaType.DATETIME,
)

# 3) Transformer le texte de chaque facture en vecteur
print("Calcul des vecteurs (1 à 2 minutes)...")
modele = TextEmbedding(MODELE)
vecteurs = list(modele.embed([texte for texte, _ in factures]))

# 4) Construire les points
points = []
for (texte, meta), vecteur in zip(factures, vecteurs):
    points.append(models.PointStruct(
        id=int(meta["invoice_code"]),
        vector=vecteur.tolist(),
        payload={**meta, "text": texte},
    ))

# 5) Envoyer par lots de 100 (upsert : remplace les points existants, pas de doublons)
for i in range(0, len(points), 100):
    client.upsert(collection_name=COLLECTION, points=points[i:i + 100])
    print(f"  {min(i + 100, len(points))}/{len(points)} envoyés")

print("Points dans la collection :", client.count(COLLECTION, exact=True).count)