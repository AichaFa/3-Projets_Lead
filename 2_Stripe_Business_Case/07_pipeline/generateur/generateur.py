"""
Générateur de données fictives - Stripe Business Case

Deux modes d'exécution :
- historique : alimentation initiale (marchands, clients, moyens de paiement, produits, abonnements,
  paiements sur une période glissante, remboursements, litiges) dans la base OLTP, et données
  semi-structurées associées (sessions, avis, journaux, documents externes) dans MongoDB ;
- direct : production continue de paiements, dont une part frauduleuse, pour alimenter le flux CDC.

Les données sont entièrement synthétiques (adresses e-mail sur domaines réservés aux exemples).
La fraude simulée suit des motifs réalistes : pays d'adresse IP inhabituel, appareil inhabituel,
montant élevé, horaire nocturne, rafale de paiements rapprochés.

Choix de conception
-------------------
- Graine aléatoire fixe : deux exécutions produisent les mêmes données (reproductibilité).
- Habitudes stables par client (appareil, marchands favoris) déduites de son identifiant :
  comportement identique dans les deux modes, condition pour que le modèle apprenne des habitudes.
- Insertions dans la base OLTP soumises à toutes ses règles (clés étrangères, contraintes,
  déclencheurs) : les remboursements et litiges passent par les déclencheurs qui contrôlent les
  montants et mettent à jour le statut des paiements.
- Aucune étiquette de fraude n'est écrite en base : comme dans la réalité, la fraude n'est connue
  qu'à travers les litiges ouverts ultérieurement (pour 65 % des fraudes réussies).

Exécution : python generateur.py historique | direct
"""

import hashlib
import logging
import os
import random
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import gridfs
import psycopg
from faker import Faker
from pymongo import MongoClient

# Paramètres, modifiables par variables d'environnement sans changer le code

GRAINE = int(os.getenv("GRAINE", "42"))
NB_MARCHANDS = int(os.getenv("NB_MARCHANDS", "50"))
NB_CLIENTS = int(os.getenv("NB_CLIENTS", "2000"))
NB_PAIEMENTS = int(os.getenv("NB_PAIEMENTS", "40000"))
NB_JOURS = int(os.getenv("NB_JOURS", "395"))
TAUX_FRAUDE_HISTORIQUE = float(os.getenv("TAUX_FRAUDE_HISTORIQUE", "0.006"))
TAUX_FRAUDE_DIRECT = float(os.getenv("TAUX_FRAUDE_DIRECT", "0.05"))
INTERVALLE_SECONDES = float(os.getenv("INTERVALLE_SECONDES", "2"))
# Clé de chiffrement symétrique des adresses e-mail, transmise à la fonction pgp_sym_encrypt
# de PostgreSQL (extension pgcrypto) ; jamais écrite dans le code ni dans le dépôt Git
CLE_CHIFFREMENT = os.getenv("CLE_CHIFFREMENT_EMAIL", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
journal = logging.getLogger("generateur")

# Référentiels
# Répartition des pays (poids relatifs) : majorité européenne, puis Amérique du Nord

PAYS_POIDS = {
    "FR": 30, "DE": 12, "GB": 10, "US": 12, "ES": 8, "IT": 7, "NL": 4, "BE": 4, "CH": 3,
    "IE": 2, "CA": 3, "BR": 2, "MX": 1, "JP": 1, "IN": 1, "AU": 0.5, "SG": 0.5,
}
# Devise de facturation des marchands selon leur pays
DEVISE_PAYS = {
    "FR": "EUR", "DE": "EUR", "ES": "EUR", "IT": "EUR", "NL": "EUR", "BE": "EUR", "IE": "EUR",
    "CH": "CHF", "GB": "GBP", "US": "USD", "CA": "CAD", "MX": "MXN", "BR": "BRL",
    "JP": "JPY", "SG": "SGD", "AU": "AUD", "IN": "INR",
}
# Langue de la bibliothèque Faker selon le pays : noms d'entreprises et adresses e-mail cohérents
LANGUE_PAYS = {
    "FR": "fr_FR", "DE": "de_DE", "ES": "es_ES", "IT": "it_IT", "NL": "nl_NL", "BE": "fr_BE",
    "IE": "en_IE", "CH": "fr_CH", "GB": "en_GB", "US": "en_US", "CA": "en_CA", "MX": "es_MX",
    "BR": "pt_BR", "JP": "ja_JP", "SG": "en_US", "AU": "en_AU", "IN": "en_IN",
}
# Valeur d'une unité de devise en euros, identique aux cours de base du script 04_referentiels.sql ;
# sert à fixer des prix cohérents quelle que soit la devise
COURS_BASE_EUR = {
    "EUR": 1.0, "USD": 0.90, "GBP": 1.17, "CHF": 1.05, "CAD": 0.66, "MXN": 0.05,
    "BRL": 0.17, "JPY": 0.0061, "SGD": 0.68, "AUD": 0.60, "INR": 0.011,
}
# Catégories de marchands : noms de produits, prix minimal et maximal en euros
CATEGORIES = {
    "mode": (["Baskets", "Veste en jean", "Robe d'été", "Sac à main", "Écharpe en laine"], 20, 150),
    "electronique": (["Écouteurs sans fil", "Chargeur rapide", "Montre connectée", "Enceinte portable", "Clavier mécanique"], 25, 400),
    "alimentation": (["Panier bio", "Coffret de thés", "Café en grains", "Épicerie fine", "Box apéritif"], 10, 80),
    "voyage": (["Billet de train", "Nuit d'hôtel", "Location de voiture", "Excursion guidée"], 40, 600),
    "logiciel": (["Abonnement mensuel", "Licence annuelle", "Stockage en ligne", "Antivirus"], 5, 120),
    "jeux_video": (["Jeu en téléchargement", "Pass saison", "Monnaie virtuelle", "Abonnement jeux"], 5, 70),
    "beaute": (["Crème hydratante", "Parfum", "Coffret maquillage", "Sérum visage"], 10, 120),
    "sport": (["Chaussures de course", "Tapis de yoga", "Haltères", "Maillot de club"], 15, 200),
    "maison": (["Lampe de bureau", "Plaid", "Service de table", "Plante d'intérieur"], 15, 250),
    "services_en_ligne": (["Abonnement streaming", "Cours en ligne", "Abonnement presse", "Coaching sportif"], 5, 60),
}
# Catégories proposant des abonnements mensuels
CATEGORIES_ABONNEMENT = {"logiciel", "jeux_video", "services_en_ligne"}
# Catégories privilégiées par les fraudeurs : biens revendables ou consommés immédiatement
CATEGORIES_CIBLES_FRAUDE = {"electronique", "voyage", "jeux_video"}
APPAREILS = ["mobile", "ordinateur", "tablette"]
# Répartition des paiements par heure (0 h à 23 h) : creux nocturne, pic en soirée
POIDS_HEURES = [1, 1, 1, 1, 1, 2, 3, 5, 7, 8, 9, 10, 11, 10, 9, 9, 10, 11, 12, 13, 13, 11, 7, 3]
MARQUES_CARTE = (["visa", "mastercard", "cb", "amex"], [45, 35, 15, 5])
COMMENTAIRES = {
    5: ["Livraison rapide, produit conforme, je recommande", "Excellent service, paiement simple et sécurisé",
        "Très satisfaite de mon achat, chaussures parfaites"],
    4: ["Bon produit, livraison un peu longue", "Paiement fluide, emballage soigné", "Conforme à la description"],
    3: ["Correct sans plus", "Produit moyen, service client réactif", "Délai de livraison à améliorer"],
    2: ["Produit décevant par rapport aux photos", "Livraison en retard sans prévenir"],
    1: ["Article jamais reçu, remboursement demandé", "Débit en double sur ma carte, très mécontent"],
}
QUESTIONS_ENQUETE = [
    ("Recommanderiez-vous ce site ?", ["Oui", "Non", "Peut-être"]),
    ("Le paiement a-t-il été simple ?", ["Très simple", "Simple", "Compliqué"]),
    ("Comment nous avez-vous connus ?", ["Réseaux sociaux", "Moteur de recherche", "Bouche à oreille"]),
]
SERVICES = ["api-paiements", "passerelle-cartes", "service-remboursements", "authentification"]
MESSAGES_JOURNAL = {
    "INFO": ["Paiement autorisé", "Requête traitée", "Jeton de carte validé", "Connexion réussie"],
    "AVERTISSEMENT": ["Temps de réponse élevé de la banque émettrice", "Tentative de connexion refusée",
                      "Nombre de requêtes proche du quota"],
    "ERREUR": ["Délai dépassé avec le réseau de cartes", "Signature de requête invalide",
               "Échec d'écriture dans la file de messages"],
    "CRITIQUE": ["Indisponibilité du service d'autorisation"],
}

# Générateurs pseudo-aléatoires initialisés avec la graine (reproductibilité)
aleatoire = random.Random(GRAINE)
Faker.seed(GRAINE)
fakers = {}  # une instance Faker par langue, créée à la première utilisation


def faker_pour(pays):
    langue = LANGUE_PAYS[pays]
    if langue not in fakers:
        fakers[langue] = Faker(langue)
    return fakers[langue]


def arrondi(valeur):
    """Montant monétaire arrondi au centime (type Decimal, exact, contrairement aux nombres à virgule flottante)."""
    return Decimal(str(valeur)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def tirer_pays():
    return aleatoire.choices(list(PAYS_POIDS), weights=list(PAYS_POIDS.values()))[0]


def preferences_client(client_id, pays_client, marchands):
    """Habitudes stables d'un client, déterminées par son identifiant (identiques dans les deux modes).

    Un générateur aléatoire dédié, initialisé avec l'empreinte SHA-256 de l'identifiant, produit
    toujours les mêmes choix pour un même client. La liste des marchands est triée au préalable :
    son ordre de lecture diffère entre les deux modes et changerait sinon les favoris.
    Favoris : deux marchands du pays du client (achats de proximité) et un marchand quelconque.
    """
    rng = random.Random(int(hashlib.sha256(str(client_id).encode()).hexdigest(), 16))
    marchands = sorted(marchands, key=lambda m: str(m["marchand_id"]))
    appareil = rng.choices(APPAREILS, weights=[55, 35, 10])[0]
    locaux = [m for m in marchands if m["code_pays"] == pays_client] or marchands
    favoris = rng.sample(locaux, k=min(2, len(locaux))) + [rng.choice(marchands)]
    return appareil, favoris


def adresse_ip():
    """Adresse IPv4 fictive ; le pays associé est porté séparément par pays_ip (géolocalisation)."""
    return f"{aleatoire.randint(11, 223)}.{aleatoire.randint(0, 255)}.{aleatoire.randint(0, 255)}.{aleatoire.randint(1, 254)}"


def connexion_postgres():
    """Connexion à la base OLTP, avec nouvelles tentatives pendant une minute au démarrage.

    Chiffrement TLS : mode (verify-full en production : chiffrement, vérification de l'autorité de
    certification et du nom du serveur) et certificat de l'autorité fournis par variables d'environnement.
    """
    parametres = dict(
        host=os.getenv("OLTP_HOTE", "postgres-oltp"),
        dbname=os.getenv("OLTP_BASE", "stripe_oltp"),
        user=os.environ["OLTP_UTILISATEUR"],
        password=os.environ["OLTP_MOT_DE_PASSE"],
        sslmode=os.getenv("OLTP_SSLMODE", "prefer"),
        sslrootcert=os.getenv("OLTP_SSLROOTCERT"),
    )
    for tentative in range(30):
        try:
            return psycopg.connect(**parametres)
        except psycopg.OperationalError:
            journal.info("Base OLTP indisponible, nouvelle tentative (%s/30)", tentative + 1)
            time.sleep(2)
    sys.exit("Connexion à la base OLTP impossible")


def connexion_mongo():
    """Connexion à MongoDB ; la commande ping vérifie immédiatement l'authentification."""
    client = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=60000)
    client.admin.command("ping")
    return client["stripe_nosql"]


def completer_taux_change(curseur):
    """Ajoute les taux manquants jusqu'à aujourd'hui en reprenant le dernier taux connu de chaque devise."""
    curseur.execute("""
        INSERT INTO taux_change (code_devise, date_taux, taux_vers_eur)
        SELECT d.code_devise, j::date, t.taux_vers_eur
        FROM devises d
        CROSS JOIN generate_series((SELECT max(date_taux) + 1 FROM taux_change), current_date, interval '1 day') AS j
        CROSS JOIN LATERAL (
            SELECT taux_vers_eur FROM taux_change tc
            WHERE tc.code_devise = d.code_devise ORDER BY tc.date_taux DESC LIMIT 1
        ) AS t
        ON CONFLICT DO NOTHING
    """)
    return curseur.rowcount


# Construction d'un paiement

def construire_paiement(client, marchands_favoris, tous_marchands, produits_par_marchand, date_heure, fraude):
    """Retourne le dictionnaire d'un paiement, normal ou frauduleux.

    Paiement normal : marchand favori dans 80 % des cas, pays de l'adresse IP égal au pays du
    client dans 97 % des cas (voyages), appareil habituel dans 90 % des cas, produit du catalogue
    dans 90 % des cas (sinon montant libre), échec dans 3 % des cas.
    Paiement frauduleux : marchand d'une catégorie ciblée, pays étranger dans 90 % des cas,
    appareil inhabituel dans 60 % des cas, horaire nocturne dans 50 % des cas, montant de deux à
    six fois le produit le plus cher du marchand, échec dans 30 % des cas (refus bancaires).
    La clé « fraude » sert uniquement à la simulation et n'est jamais écrite en base.
    """
    appareil_habituel = client["appareil"]
    if fraude:
        cibles = [m for m in tous_marchands if m["categorie"] in CATEGORIES_CIBLES_FRAUDE] or tous_marchands
        marchand = aleatoire.choice(cibles)
        autres_pays = [p for p in PAYS_POIDS if p != client["code_pays"]]
        pays_ip = aleatoire.choice(autres_pays) if aleatoire.random() < 0.9 else client["code_pays"]
        appareil = aleatoire.choice([a for a in APPAREILS if a != appareil_habituel]) if aleatoire.random() < 0.6 else appareil_habituel
        if aleatoire.random() < 0.5:
            date_heure = date_heure.replace(hour=aleatoire.randint(0, 5))
    else:
        marchand = aleatoire.choice(marchands_favoris) if aleatoire.random() < 0.8 else aleatoire.choice(tous_marchands)
        pays_ip = client["code_pays"] if aleatoire.random() < 0.97 else tirer_pays()
        appareil = appareil_habituel if aleatoire.random() < 0.9 else aleatoire.choice(APPAREILS)

    produits = produits_par_marchand[marchand["marchand_id"]]
    if fraude:
        produit = max(produits, key=lambda p: p["prix"])
        montant = arrondi(float(produit["prix"]) * aleatoire.uniform(2, 6))
        produit_id = None
    elif aleatoire.random() < 0.9:
        produit = aleatoire.choice(produits)
        montant = produit["prix"]
        produit_id = produit["produit_id"]
    else:
        produit = aleatoire.choice(produits)
        montant = arrondi(float(produit["prix"]) * aleatoire.uniform(0.5, 1.5))
        produit_id = None

    taux_echec = 0.30 if fraude else 0.03
    return {
        "transaction_id": uuid.uuid4(),
        "marchand_id": marchand["marchand_id"],
        "client_id": client["client_id"],
        "moyen_paiement_id": aleatoire.choice(client["moyens"]),
        "produit_id": produit_id,
        "abonnement_id": None,
        "montant": montant,
        "code_devise": produit["code_devise"],
        "statut": "echouee" if aleatoire.random() < taux_echec else "reussie",
        "date_heure": date_heure,
        "adresse_ip": adresse_ip(),
        "pays_ip": pays_ip,
        "type_appareil": appareil,
        "fraude": fraude,
    }


# Requêtes d'insertion paramétrées (paramètres %s ou %(nom)s) : les valeurs sont transmises
# séparément du texte SQL, ce qui protège contre l'injection SQL
SQL_PAIEMENT = """
    INSERT INTO transactions (transaction_id, marchand_id, client_id, moyen_paiement_id, produit_id,
                              abonnement_id, montant, code_devise, statut, date_heure, adresse_ip,
                              pays_ip, type_appareil)
    VALUES (%(transaction_id)s, %(marchand_id)s, %(client_id)s, %(moyen_paiement_id)s, %(produit_id)s,
            %(abonnement_id)s, %(montant)s, %(code_devise)s, %(statut)s, %(date_heure)s, %(adresse_ip)s,
            %(pays_ip)s, %(type_appareil)s)
"""
SQL_REMBOURSEMENT = """
    INSERT INTO remboursements (transaction_id, montant, motif, date_remboursement)
    VALUES (%s, %s, %s, %s)
"""
SQL_LITIGE = """
    INSERT INTO litiges (litige_id, transaction_id, motif, statut, date_ouverture)
    VALUES (%s, %s, %s, %s, %s)
"""


# Documents MongoDB

def document_session(paiement, debut):
    """Session de navigation ; un paiement frauduleux suit un parcours très court, direct vers le paiement."""
    if paiement and paiement["fraude"]:
        nb_evenements = aleatoire.randint(1, 2)
    else:
        nb_evenements = aleatoire.randint(3, 14)
    evenements = []
    instant = debut
    pages = ["/accueil", "/produits", "/produit", "/recherche", "/panier"]
    for _ in range(nb_evenements):
        instant += timedelta(seconds=aleatoire.randint(5, 90))
        type_evenement = aleatoire.choices(["page_vue", "recherche", "clic", "ajout_panier"], weights=[50, 15, 25, 10])[0]
        evenements.append({"type": type_evenement, "horodatage": instant, "page": aleatoire.choice(pages)})
    document = {
        "_id": f"ses_{uuid.uuid4().hex}",
        "debut": debut,
        "appareil": {"type": paiement["type_appareil"] if paiement else aleatoire.choice(APPAREILS)},
    }
    if paiement:
        # Parcours d'achat cohérent : consultation du produit et ajout au panier avant le paiement
        if not any(e["type"] == "page_vue" for e in evenements):
            instant += timedelta(seconds=aleatoire.randint(5, 30))
            evenements.append({"type": "page_vue", "horodatage": instant, "page": "/produit"})
        instant += timedelta(seconds=aleatoire.randint(5, 30))
        evenements.append({"type": "ajout_panier", "horodatage": instant, "page": "/produit"})
        instant += timedelta(seconds=aleatoire.randint(10, 60))
        evenements.append({"type": "paiement", "horodatage": instant, "page": "/paiement"})
        document["client_id"] = str(paiement["client_id"])
        document["marchand_id"] = str(paiement["marchand_id"])
        document["transaction_id"] = str(paiement["transaction_id"])
    else:
        document["client_id"] = None
    document["evenements"] = evenements
    document["fin"] = instant
    return document


def document_avis(paiement, date_avis):
    if aleatoire.random() < 0.8:
        note = aleatoire.choices([5, 4, 3, 2, 1], weights=[45, 30, 12, 7, 6])[0]
        return {"type": "avis", "client_id": str(paiement["client_id"]), "marchand_id": str(paiement["marchand_id"]),
                "date": date_avis, "note": note, "commentaire": aleatoire.choice(COMMENTAIRES[note])}
    return {"type": "enquete", "client_id": str(paiement["client_id"]), "marchand_id": str(paiement["marchand_id"]),
            "date": date_avis,
            "reponses": [{"question": q, "reponse": aleatoire.choice(r)} for q, r in QUESTIONS_ENQUETE]}


def document_journal(horodatage):
    niveau = aleatoire.choices(list(MESSAGES_JOURNAL), weights=[85, 10, 4.5, 0.5])[0]
    code_http = {"INFO": 200, "AVERTISSEMENT": aleatoire.choice([200, 429]),
                 "ERREUR": aleatoire.choice([500, 502, 504]), "CRITIQUE": 503}[niveau]
    return {"horodatage": horodatage, "niveau": niveau,
            "source": {"service": aleatoire.choice(SERVICES), "hote": f"srv-{aleatoire.randint(1, 8):02d}"},
            "message": aleatoire.choice(MESSAGES_JOURNAL[niveau]), "code_http": code_http,
            "duree_ms": aleatoire.randint(20, 400) if niveau == "INFO" else aleatoire.randint(400, 30000),
            "adresse_ip": adresse_ip()}


def documents_litige(litige_id, paiement, date_ouverture, motif, seau_fichiers):
    """Notification bancaire au format XML et, pour une partie des litiges, justificatif PDF stocké dans GridFS.

    Le XML est conservé tel que reçu (contenu_brut) et ses informations utiles sont extraites en
    JSON (champs_extraits) pour être interrogeables. Le PDF est un document minimal valide ; GridFS
    découpe les fichiers en morceaux, ce qui lève la limite de 16 Mo d'un document MongoDB.
    """
    xml = (f'<NotificationLitige><Reference>{litige_id}</Reference>'
           f'<Transaction>{paiement["transaction_id"]}</Transaction>'
           f'<Montant devise="{paiement["code_devise"]}">{paiement["montant"]}</Montant>'
           f'<Motif>{motif}</Motif><Date>{date_ouverture.date().isoformat()}</Date></NotificationLitige>')
    documents = [{
        "type": "message_bancaire", "format": "xml", "date_reception": date_ouverture,
        "references": {"transaction_id": str(paiement["transaction_id"]), "litige_id": str(litige_id)},
        "contenu_brut": xml,
        "champs_extraits": {"montant": float(paiement["montant"]), "devise": paiement["code_devise"], "motif": motif},
    }]
    if aleatoire.random() < 0.4:
        contenu = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                   b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")
        identifiant = seau_fichiers.put(contenu, filename=f"justificatif_{litige_id}.pdf", content_type="application/pdf")
        documents.append({
            "type": "piece_justificative", "format": "pdf",
            "date_reception": date_ouverture + timedelta(days=aleatoire.randint(1, 5)),
            "references": {"transaction_id": str(paiement["transaction_id"]), "litige_id": str(litige_id)},
            "fichier_gridfs_id": identifiant, "taille_octets": len(contenu),
        })
    return documents


# Mode historique

def generer_historique():
    """Alimentation initiale complète ; refus d'exécution si des marchands existent déjà (pas de doublon)."""
    if not CLE_CHIFFREMENT:
        sys.exit("Variable CLE_CHIFFREMENT_EMAIL absente")
    connexion = connexion_postgres()
    base_mongo = connexion_mongo()
    seau_fichiers = gridfs.GridFS(base_mongo, collection="fichiers")
    maintenant = datetime.now(timezone.utc).replace(microsecond=0)
    debut = maintenant - timedelta(days=NB_JOURS)

    with connexion, connexion.cursor() as cur:
        cur.execute("SELECT count(*) FROM marchands")
        if cur.fetchone()[0] > 0:
            sys.exit("Historique déjà présent dans la base OLTP : génération interrompue")
        journal.info("Taux de change complétés : %s lignes", completer_taux_change(cur))

        # Marchands et produits
        categories = list(CATEGORIES)
        marchands, produits_par_marchand, lignes_produits = [], {}, []
        for _ in range(NB_MARCHANDS):
            pays = tirer_pays()
            marchand = {"marchand_id": uuid.uuid4(), "raison_sociale": faker_pour(pays).company(),
                        "code_pays": pays, "categorie": aleatoire.choice(categories),
                        "date_creation": debut - timedelta(days=aleatoire.randint(30, 900))}
            marchands.append(marchand)
            noms, prix_min, prix_max = CATEGORIES[marchand["categorie"]]
            devise = DEVISE_PAYS[pays]
            produits_par_marchand[marchand["marchand_id"]] = []
            for nom in aleatoire.sample(noms, k=min(len(noms), aleatoire.randint(3, 5))):
                produit = {"produit_id": uuid.uuid4(), "marchand_id": marchand["marchand_id"], "nom": nom,
                           "prix": arrondi(aleatoire.uniform(prix_min, prix_max) / COURS_BASE_EUR[devise]),
                           "code_devise": devise, "categorie": marchand["categorie"]}
                produits_par_marchand[marchand["marchand_id"]].append(produit)
                lignes_produits.append(produit)
        cur.executemany(
            "INSERT INTO marchands (marchand_id, raison_sociale, code_pays, categorie, date_creation) "
            "VALUES (%(marchand_id)s, %(raison_sociale)s, %(code_pays)s, %(categorie)s, %(date_creation)s)", marchands)
        cur.executemany(
            "INSERT INTO produits (produit_id, marchand_id, nom, prix, code_devise) "
            "VALUES (%(produit_id)s, %(marchand_id)s, %(nom)s, %(prix)s, %(code_devise)s)", lignes_produits)
        journal.info("%s marchands et %s produits insérés", len(marchands), len(lignes_produits))

        # Clients et moyens de paiement
        # Activité de chaque client tirée selon une loi log-normale : beaucoup de clients occasionnels,
        # quelques très gros acheteurs, comme dans la réalité.
        # E-mail chiffré par PostgreSQL au moment de l'insertion (pgp_sym_encrypt) : il ne transite
        # jamais en clair dans une table. Moyens de paiement tokenisés : seuls un jeton et les quatre
        # derniers chiffres sont conservés (PCI-DSS).
        clients, lignes_clients, lignes_moyens = [], [], []
        for _ in range(NB_CLIENTS):
            pays = tirer_pays()
            client_id = uuid.uuid4()
            inscription = debut - timedelta(days=200) + timedelta(seconds=aleatoire.randint(0, (NB_JOURS + 150) * 86400))
            appareil, favoris = preferences_client(client_id, pays, marchands)
            client = {"client_id": client_id, "code_pays": pays, "inscription": min(inscription, maintenant - timedelta(days=5)),
                      "appareil": appareil, "favoris": favoris, "moyens": [],
                      "activite": aleatoire.lognormvariate(0, 1)}
            lignes_clients.append((client_id, faker_pour(pays).unique.email(), CLE_CHIFFREMENT, pays, client["inscription"]))
            for _ in range(aleatoire.choices([1, 2], weights=[75, 25])[0]):
                moyen_id = uuid.uuid4()
                type_moyen = aleatoire.choices(["carte", "prelevement", "portefeuille"], weights=[80, 10, 10])[0]
                marque = (aleatoire.choices(*MARQUES_CARTE)[0] if type_moyen == "carte"
                          else aleatoire.choice(["apple_pay", "google_pay"]) if type_moyen == "portefeuille" else None)
                quatre = f"{aleatoire.randint(0, 9999):04d}" if type_moyen in ("carte", "prelevement") else None
                lignes_moyens.append((moyen_id, client_id, type_moyen, marque, quatre, f"tok_{uuid.uuid4().hex}"))
                client["moyens"].append(moyen_id)
            clients.append(client)
        cur.executemany(
            "INSERT INTO clients (client_id, email_chiffre, code_pays, date_creation) "
            "VALUES (%s, pgp_sym_encrypt(%s, %s), %s, %s)", lignes_clients)
        cur.executemany(
            "INSERT INTO moyens_paiement (moyen_paiement_id, client_id, type, marque, quatre_derniers, jeton) "
            "VALUES (%s, %s, %s, %s, %s, %s)", lignes_moyens)
        journal.info("%s clients et %s moyens de paiement insérés", len(clients), len(lignes_moyens))

        # Paiements ponctuels, normaux et frauduleux (avec rafales)
        # Une fraude est suivie de une à trois tentatives rapprochées (deux minutes d'écart) avec
        # la même carte : comportement typique d'un fraudeur qui exploite une carte avant son blocage.
        paiements = []
        poids_clients = [c["activite"] for c in clients]
        while len(paiements) < NB_PAIEMENTS:
            client = aleatoire.choices(clients, weights=poids_clients)[0]
            depart = max(client["inscription"], debut)
            jour = depart + timedelta(seconds=aleatoire.randint(0, max(1, int((maintenant - depart).total_seconds()) - 3600)))
            date_heure = jour.replace(hour=aleatoire.choices(range(24), weights=POIDS_HEURES)[0],
                                      minute=aleatoire.randint(0, 59), second=aleatoire.randint(0, 59))
            date_heure = min(date_heure, maintenant - timedelta(minutes=5))
            fraude = aleatoire.random() < TAUX_FRAUDE_HISTORIQUE
            paiement = construire_paiement(client, client["favoris"], marchands, produits_par_marchand, date_heure, fraude)
            paiements.append(paiement)
            if fraude:
                for rang in range(aleatoire.randint(1, 3)):
                    suite = dict(paiement, transaction_id=uuid.uuid4(),
                                 date_heure=min(paiement["date_heure"] + timedelta(minutes=2 * (rang + 1)), maintenant - timedelta(minutes=1)),
                                 montant=arrondi(float(paiement["montant"]) * aleatoire.uniform(0.6, 1.1)),
                                 statut="echouee" if aleatoire.random() < 0.3 else "reussie")
                    paiements.append(suite)

        # Abonnements et prélèvements mensuels
        # 15 % des clients souscrivent ; 20 % des abonnements sont résiliés. Prélèvements tous les
        # 30 jours, la nuit, sans adresse IP (paiement initié par le marchand et non par le client).
        produits_abonnement = [p for p in lignes_produits if p["categorie"] in CATEGORIES_ABONNEMENT]
        lignes_abonnements = []
        for client in aleatoire.sample(clients, k=int(len(clients) * 0.15)):
            if not produits_abonnement:
                break
            produit = aleatoire.choice(produits_abonnement)
            date_debut = max(client["inscription"], debut) + timedelta(days=aleatoire.randint(0, 60))
            if date_debut >= maintenant - timedelta(days=1):
                continue
            resilie = aleatoire.random() < 0.2
            date_fin = date_debut + timedelta(days=aleatoire.randint(60, 300)) if resilie else None
            if date_fin and date_fin > maintenant:
                date_fin, resilie = None, False
            abonnement_id = uuid.uuid4()
            lignes_abonnements.append((abonnement_id, client["client_id"], produit["produit_id"],
                                       "resilie" if resilie else "actif", date_debut.date(),
                                       date_fin.date() if date_fin else None))
            echeance = date_debut
            while echeance < (date_fin or maintenant):
                paiements.append({
                    "transaction_id": uuid.uuid4(), "marchand_id": produit["marchand_id"],
                    "client_id": client["client_id"], "moyen_paiement_id": client["moyens"][0],
                    "produit_id": produit["produit_id"], "abonnement_id": abonnement_id,
                    "montant": produit["prix"], "code_devise": produit["code_devise"],
                    "statut": "echouee" if aleatoire.random() < 0.02 else "reussie",
                    "date_heure": echeance.replace(hour=aleatoire.randint(1, 5)), "adresse_ip": None,
                    "pays_ip": None, "type_appareil": "ordinateur", "fraude": False,
                })
                echeance += timedelta(days=30)
        cur.executemany(
            "INSERT INTO abonnements (abonnement_id, client_id, produit_id, statut, date_debut, date_fin) "
            "VALUES (%s, %s, %s, %s, %s, %s)", lignes_abonnements)

        # Insertion dans l'ordre chronologique, comme dans un système réel
        paiements.sort(key=lambda p: p["date_heure"])
        cur.executemany(SQL_PAIEMENT, paiements)
        journal.info("%s abonnements et %s paiements insérés (%s frauduleux simulés)",
                     len(lignes_abonnements), len(paiements), sum(p["fraude"] for p in paiements))

        # Remboursements et litiges (déclencheurs : contrôle du cumul et mise à jour du statut)
        # Fraude réussie : litige pour motif « fraude » dans 65 % des cas, ouvert 5 à 40 jours après.
        # Paiement normal : remboursement dans 3 % des cas (60 % total, 40 % partiel), litige
        # commercial dans 0,3 % des cas. Un litige récent (moins de 45 jours) reste « ouvert ».
        lignes_remboursements, lignes_litiges, litiges_crees = [], [], []
        for paiement in paiements:
            if paiement["statut"] != "reussie":
                continue
            marge = (maintenant - paiement["date_heure"]).days
            if paiement["fraude"] and aleatoire.random() < 0.65 and marge > 6:
                date_ouverture = paiement["date_heure"] + timedelta(days=aleatoire.randint(5, min(40, marge - 1)))
                litige_id = uuid.uuid4()
                statut_litige = "ouvert" if marge < 45 else aleatoire.choices(["gagne", "perdu"], weights=[30, 70])[0]
                lignes_litiges.append((litige_id, paiement["transaction_id"], "fraude", statut_litige, date_ouverture))
                litiges_crees.append((litige_id, paiement, date_ouverture, "fraude"))
            elif not paiement["fraude"] and aleatoire.random() < 0.03 and marge > 2:
                date_remb = paiement["date_heure"] + timedelta(days=aleatoire.randint(1, min(20, marge - 1)))
                total = aleatoire.random() < 0.6
                montant = paiement["montant"] if total else arrondi(float(paiement["montant"]) * aleatoire.uniform(0.2, 0.7))
                motif = aleatoire.choice(["demande_client", "doublon", "produit_non_conforme"])
                lignes_remboursements.append((paiement["transaction_id"], montant, motif, date_remb))
            elif not paiement["fraude"] and aleatoire.random() < 0.003 and marge > 6:
                date_ouverture = paiement["date_heure"] + timedelta(days=aleatoire.randint(5, min(40, marge - 1)))
                litige_id = uuid.uuid4()
                motif = aleatoire.choice(["produit_non_recu", "produit_non_conforme", "debit_duplique", "autre"])
                statut_litige = "ouvert" if marge < 45 else aleatoire.choices(["gagne", "perdu"], weights=[60, 40])[0]
                lignes_litiges.append((litige_id, paiement["transaction_id"], motif, statut_litige, date_ouverture))
                litiges_crees.append((litige_id, paiement, date_ouverture, motif))
        cur.executemany(SQL_REMBOURSEMENT, lignes_remboursements)
        cur.executemany(SQL_LITIGE, lignes_litiges)
        journal.info("%s remboursements et %s litiges insérés", len(lignes_remboursements), len(lignes_litiges))

    # Données semi-structurées dans MongoDB
    # Sessions : uniquement sur les 90 derniers jours (volume maîtrisé), plus 50 % de visites sans
    # achat dont une partie anonyme. Avis : 4 % des paiements réussis. Journaux : 60 derniers jours,
    # en deçà de la durée de conservation de 90 jours. insert_many(ordered=False) : insertion groupée
    # qui poursuit en cas d'erreur sur un document isolé.
    limite_sessions = maintenant - timedelta(days=90)
    recents = [p for p in paiements if p["date_heure"] >= limite_sessions and p["adresse_ip"]]
    sessions = [document_session(p, p["date_heure"] - timedelta(minutes=aleatoire.randint(2, 20))) for p in recents]
    sessions += [document_session(None, limite_sessions + timedelta(seconds=aleatoire.randint(0, 90 * 86400)))
                 for _ in range(len(recents) // 2)]
    if sessions:
        base_mongo.sessions_navigation.insert_many(sessions, ordered=False)

    reussis = [p for p in paiements if p["statut"] == "reussie" and not p["fraude"]]
    avis = [document_avis(p, p["date_heure"] + timedelta(days=aleatoire.randint(2, 15)))
            for p in aleatoire.sample(reussis, k=min(len(reussis), int(len(reussis) * 0.04)))]
    avis = [a for a in avis if a["date"] <= maintenant]
    if avis:
        base_mongo.avis_clients.insert_many(avis, ordered=False)

    journaux = [document_journal(maintenant - timedelta(seconds=aleatoire.randint(0, 60 * 86400))) for _ in range(3000)]
    base_mongo.journaux_applicatifs.insert_many(journaux, ordered=False)

    documents = []
    for litige_id, paiement, date_ouverture, motif in litiges_crees:
        documents += documents_litige(litige_id, paiement, date_ouverture, motif, seau_fichiers)
    if documents:
        base_mongo.documents_externes.insert_many(documents, ordered=False)
    journal.info("MongoDB : %s sessions, %s avis ou enquêtes, %s journaux, %s documents externes",
                 len(sessions), len(avis), len(journaux), len(documents))
    journal.info("Génération de l'historique terminée")


# Mode direct

def charger_contexte(cur):
    """Relit dans la base OLTP les marchands, produits et clients nécessaires au mode direct."""
    cur.execute("SELECT marchand_id, code_pays, categorie FROM marchands")
    marchands = [{"marchand_id": r[0], "code_pays": r[1], "categorie": r[2]} for r in cur.fetchall()]
    cur.execute("SELECT produit_id, marchand_id, prix, code_devise FROM produits")
    produits_par_marchand = {}
    for r in cur.fetchall():
        produits_par_marchand.setdefault(r[1], []).append({"produit_id": r[0], "prix": r[2], "code_devise": r[3]})
    cur.execute("""
        SELECT c.client_id, c.code_pays, array_agg(m.moyen_paiement_id)
        FROM clients c JOIN moyens_paiement m ON m.client_id = c.client_id
        GROUP BY c.client_id, c.code_pays
    """)
    clients = []
    for client_id, pays, moyens in cur.fetchall():
        appareil, favoris = preferences_client(client_id, pays, marchands)
        clients.append({"client_id": client_id, "code_pays": pays, "moyens": moyens,
                        "appareil": appareil, "favoris": favoris})
    return marchands, produits_par_marchand, clients


def generer_en_direct():
    """Production continue : un paiement toutes les INTERVALLE_SECONDES, avec un taux de fraude
    plus élevé qu'en historique pour rendre la détection visible lors des démonstrations.

    Mode autocommit : chaque paiement est validé immédiatement et devient aussitôt visible par la
    capture des changements (CDC). Événements différés : un remboursement tous les 25 paiements,
    un litige tous les 40, un avis tous les 15, sur des paiements récents réussis.
    """
    # Graine tirée de l'heure de démarrage : chaque lancement produit une suite de paiements
    # différente (la graine fixe ne sert qu'à la reproductibilité de l'historique)
    aleatoire.seed(time.time_ns())
    connexion = connexion_postgres()
    connexion.autocommit = True
    base_mongo = connexion_mongo()
    seau_fichiers = gridfs.GridFS(base_mongo, collection="fichiers")
    cur = connexion.cursor()
    cur.execute("SELECT count(*) FROM marchands")
    if cur.fetchone()[0] == 0:
        sys.exit("Base OLTP vide : exécuter d'abord le mode historique")
    completer_taux_change(cur)
    marchands, produits_par_marchand, clients = charger_contexte(cur)
    journal.info("Mode direct : un paiement toutes les %s secondes, taux de fraude simulée %s",
                 INTERVALLE_SECONDES, TAUX_FRAUDE_DIRECT)
    recents, jour_courant, compteur, rafale = [], datetime.now(timezone.utc).date(), 0, []

    while True:
        maintenant = datetime.now(timezone.utc)
        # Changement de jour : ajout du taux de change du nouveau jour
        if maintenant.date() != jour_courant:
            completer_taux_change(cur)
            jour_courant = maintenant.date()
        # Rafale en cours : tentatives suivantes du même fraudeur, à chaque itération
        if rafale:
            paiement = rafale.pop(0)
            paiement["date_heure"] = maintenant
        else:
            fraude = aleatoire.random() < TAUX_FRAUDE_DIRECT
            client = aleatoire.choice(clients)
            paiement = construire_paiement(client, client["favoris"], marchands, produits_par_marchand, maintenant, fraude)
            paiement["date_heure"] = maintenant
            if fraude:
                rafale = [dict(paiement, transaction_id=uuid.uuid4(),
                               montant=arrondi(float(paiement["montant"]) * aleatoire.uniform(0.6, 1.1)))
                          for _ in range(aleatoire.randint(1, 3))]
        try:
            cur.execute(SQL_PAIEMENT, paiement)
        except psycopg.Error as erreur:
            journal.warning("Paiement rejeté par la base : %s", erreur)
            time.sleep(INTERVALLE_SECONDES)
            continue
        compteur += 1
        journal.info("Paiement %s | %s %s | IP %s | %s | %s",
                     str(paiement["transaction_id"])[:8], paiement["montant"], paiement["code_devise"],
                     paiement["pays_ip"], paiement["type_appareil"], paiement["statut"])

        base_mongo.sessions_navigation.insert_one(document_session(paiement, maintenant - timedelta(minutes=aleatoire.randint(2, 15))))
        base_mongo.journaux_applicatifs.insert_one(document_journal(maintenant))
        if paiement["statut"] == "reussie":
            recents.append(paiement)
            recents = recents[-200:]

        # Événements différés sur des paiements récents (conservés en mémoire, 200 au maximum)
        if compteur % 25 == 0 and recents:
            cible = aleatoire.choice([p for p in recents if not p["fraude"]] or recents)
            try:
                cur.execute(SQL_REMBOURSEMENT, (cible["transaction_id"], cible["montant"], "demande_client", maintenant))
                recents.remove(cible)
                journal.info("Remboursement total du paiement %s", str(cible["transaction_id"])[:8])
            except psycopg.Error as erreur:
                journal.warning("Remboursement rejeté : %s", erreur)
        if compteur % 40 == 0 and recents:
            cibles = [p for p in recents if p["fraude"]] or recents
            cible = aleatoire.choice(cibles)
            motif = "fraude" if cible["fraude"] else "produit_non_recu"
            litige_id = uuid.uuid4()
            try:
                cur.execute(SQL_LITIGE, (litige_id, cible["transaction_id"], motif, "ouvert", maintenant))
                base_mongo.documents_externes.insert_many(documents_litige(litige_id, cible, maintenant, motif, seau_fichiers))
                recents.remove(cible)
                journal.info("Litige ouvert sur le paiement %s (motif : %s)", str(cible["transaction_id"])[:8], motif)
            except psycopg.Error as erreur:
                journal.warning("Litige rejeté : %s", erreur)
        if compteur % 15 == 0 and recents:
            base_mongo.avis_clients.insert_one(document_avis(aleatoire.choice(recents), maintenant))

        time.sleep(INTERVALLE_SECONDES)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "direct"
    if mode == "historique":
        generer_historique()
    elif mode == "direct":
        generer_en_direct()
    else:
        sys.exit(f"Mode inconnu : {mode} (modes disponibles : historique, direct)")
