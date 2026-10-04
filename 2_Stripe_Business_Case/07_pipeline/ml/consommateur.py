"""
Consommateur temps réel - Stripe Business Case

Lit les événements de changement de la table des paiements publiés par Debezium dans Kafka
(sujet stripe.public.transactions) et applique, pour chaque nouveau paiement, les deux modèles
intégrés au système NoSQL : détection de fraude et personnalisation.

Traitement d'une création de paiement (op = "c")
------------------------------------------------
1. Conversion du montant en euros au taux du jour du paiement (référentiel de la base OLTP).
2. Lecture du profil du client dans MongoDB (création à partir de la base OLTP pour un nouveau client).
3. Calcul des indices (module indicateurs, identique à l'entraînement), score du modèle de fraude
   actif, décision (accepter, verifier, bloquer).
4. Enregistrement du paiement enrichi dans transactions_enrichies (écriture idempotente : _id égal
   à l'identifiant du paiement, aucun doublon en cas de relecture d'un message).
5. Mise à jour du profil : habitudes (fraude), produits achetés, catégories préférées et
   recommandations recalculées avec le modèle de recommandation actif (personnalisation).
6. Renvoi du score dans la base OLTP (colonne score_anomalie), d'où il rejoint l'entrepôt.

Traitement d'une modification (op = "u")
-----------------------------------------
Changement de statut (remboursement, litige) : ajout à l'historique des statuts du paiement enrichi.
La mise à jour du score par ce consommateur génère elle aussi un événement de modification, sans
changement de statut : il est ignoré, ce qui évite une boucle de traitement.

Garanties
---------
- Ordre : messages répartis par client dans Kafka (clé = client_id, réglage du connecteur), donc
  traités dans l'ordre pour un même client.
- Livraison « au moins une fois » : validation de la position de lecture (commit) après traitement
  seulement ; une relecture éventuelle est neutralisée par les écritures idempotentes et par la
  liste des derniers paiements intégrés à chaque profil.
- Échec persistant d'un message : consignation dans journaux_applicatifs (niveau ERREUR) puis
  poursuite du flux, pour ne pas bloquer les paiements suivants.

Suivi des modèles en production
-------------------------------
- Rechargement à chaud : la version active de chaque modèle est vérifiée toutes les 60 secondes ;
  une nouvelle version activée par un réentraînement est prise en compte sans arrêt du flux.
- Indicateurs de production (part de paiements bloqués et à vérifier, score moyen, latence,
  origine des recommandations) écrits tous les 50 paiements dans la fiche du modèle (modeles_ml),
  pour comparaison avec les indicateurs mesurés à l'entraînement (détection d'une dérive).
- Latence : médiane des 50 derniers paiements, insensible aux valeurs extrêmes (une moyenne serait
  faussée durablement par quelques messages restés en attente, par exemple après un arrêt).

Exécution : python consommateur.py
"""

import io
import json
import logging
import os
import signal
import statistics
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal

import gridfs
import joblib
import psycopg
from bson.decimal128 import Decimal128
from confluent_kafka import Consumer, KafkaException

from indicateurs import calculer_indices, decision, mettre_a_jour_profil, profil_vide, vecteur
from personnalisation import mettre_a_jour_preferences, recommander

MODELE_FRAUDE = "fraude_hgb"
MODELE_RECOMMANDATION = "recommandation_produits"
INTERVALLE_VERIFICATION_MODELES = 60   # secondes
FREQUENCE_SUIVI = 50                   # paiements entre deux écritures des indicateurs de production
NB_TENTATIVES = 3                      # tentatives de traitement d'un message avant consignation de l'échec
NB_DERNIERS_PAIEMENTS = 20             # paiements mémorisés par profil (protection contre la double prise en compte)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
journal = logging.getLogger("consommateur")


def lire_date(texte):
    """Date ISO 8601 transmise par Debezium (exemple : 2026-10-04T16:27:28.241665Z), avec fuseau horaire."""
    return datetime.fromisoformat(texte.replace("Z", "+00:00"))


class Consommateur:
    def __init__(self, pg, mongo):
        self.pg = pg
        self.mongo = mongo
        self.seau_modeles = gridfs.GridFS(mongo, collection="modeles")
        self.taux = {}          # cache (devise, jour) -> taux vers l'euro
        self.categories = {}    # cache produit -> catégorie du marchand
        self.fraude = {"fiche": None, "modele": None}
        self.reco = {"fiche": None, "modele": None}
        self.derniere_verification = 0.0
        self.suivi = self._suivi_vide()
        self.verifier_modeles(force=True)

    # Modèles

    def _charger(self, nom, emplacement):
        fiche = self.mongo.modeles_ml.find_one({"nom": nom, "statut": "actif"})
        if fiche is None:
            sys.exit(f"Aucune version active du modèle {nom} : exécuter d'abord l'entraînement")
        actuelle = emplacement["fiche"]
        if actuelle is None or actuelle["version"] != fiche["version"]:
            contenu = self.seau_modeles.get(fiche["fichier_gridfs_id"]).read()
            emplacement["modele"] = joblib.load(io.BytesIO(contenu))
            emplacement["fiche"] = fiche
            journal.info("Modèle %s version %s chargé", nom, fiche["version"])
            return True
        return False

    def verifier_modeles(self, force=False):
        """Recharge un modèle lorsque sa version active a changé (mise à jour sans interruption)."""
        if force or time.time() - self.derniere_verification >= INTERVALLE_VERIFICATION_MODELES:
            if self._charger(MODELE_FRAUDE, self.fraude):
                self.suivi = self._suivi_vide()
            self._charger(MODELE_RECOMMANDATION, self.reco)
            self.derniere_verification = time.time()

    # Référentiels lus dans la base OLTP

    def taux_vers_eur(self, devise, jour):
        cle = (devise, jour)
        if cle not in self.taux:
            with self.pg.cursor() as cur:
                cur.execute("""
                    SELECT taux_vers_eur FROM taux_change
                    WHERE code_devise = %s AND date_taux <= %s
                    ORDER BY date_taux DESC LIMIT 1
                """, (devise, jour))
                ligne = cur.fetchone()
            self.taux[cle] = ligne[0] if ligne else Decimal("1")
        return self.taux[cle]

    def categorie_produit(self, produit_id):
        if produit_id not in self.categories:
            with self.pg.cursor() as cur:
                cur.execute("""
                    SELECT m.categorie FROM produits p JOIN marchands m ON m.marchand_id = p.marchand_id
                    WHERE p.produit_id = %s
                """, (produit_id,))
                ligne = cur.fetchone()
            self.categories[produit_id] = ligne[0] if ligne else None
        return self.categories[produit_id]

    def profil_client(self, client_id):
        profil = self.mongo.profils_clients.find_one({"_id": client_id})
        if profil is None:
            with self.pg.cursor() as cur:
                cur.execute("SELECT code_pays, date_creation FROM clients WHERE client_id = %s", (client_id,))
                code_pays, date_creation = cur.fetchone()
            profil = profil_vide(client_id, code_pays, date_creation)
        profil.setdefault("produits_achetes", [])
        profil.setdefault("categories_preferees", {})
        profil.setdefault("derniers_paiements", [])
        return profil

    # Traitement des événements

    def traiter(self, evenement):
        operation = evenement.get("op")
        if operation == "c":
            self.traiter_creation(evenement["after"])
        elif operation == "u":
            self.traiter_modification(evenement["after"])

    def traiter_creation(self, apres):
        instant_reception = datetime.now(timezone.utc)
        transaction_id = apres["transaction_id"]
        date_heure = lire_date(apres["date_heure"])
        montant = Decimal(apres["montant"])
        montant_eur = (montant * self.taux_vers_eur(apres["code_devise"], date_heure.date())).quantize(Decimal("0.01"))
        paiement = {
            "transaction_id": transaction_id,
            "marchand_id": apres["marchand_id"],
            "statut": apres["statut"],
            "date_heure": date_heure,
            "pays_ip": apres.get("pays_ip"),
            "type_appareil": apres["type_appareil"],
            "montant_eur": montant_eur,
        }

        # Détection de fraude
        profil = self.profil_client(apres["client_id"])
        indices = calculer_indices(profil, paiement)
        fiche = self.fraude["fiche"]
        score = round(float(self.fraude["modele"].predict_proba([vecteur(indices)])[0, 1]), 4)
        choix = decision(score, fiche.get("seuil_verification", 0.5), fiche["seuil_decision"])
        latence_ms = int((datetime.now(timezone.utc) - date_heure).total_seconds() * 1000)

        self.mongo.transactions_enrichies.update_one(
            {"_id": transaction_id},
            {
                "$set": {
                    "client_id": apres["client_id"],
                    "marchand_id": apres["marchand_id"],
                    "montant": Decimal128(str(montant)),
                    "devise": apres["code_devise"],
                    "statut": apres["statut"],
                    "date_heure": date_heure,
                    "contexte": {"type_appareil": apres["type_appareil"], "pays_ip": apres.get("pays_ip"),
                                 "produit_id": apres.get("produit_id"), "abonnement_id": apres.get("abonnement_id"),
                                 "montant_eur": Decimal128(str(montant_eur))},
                    "indicateurs": indices,
                    "score": {"valeur": score, "modele": MODELE_FRAUDE, "version": fiche["version"], "decision": choix},
                    "latence_ms": latence_ms,
                    "date_traitement": instant_reception,
                },
                "$setOnInsert": {"historique_statuts": [{"statut": apres["statut"], "date": date_heure}]},
            },
            upsert=True,
        )

        # Profil : habitudes et personnalisation (une seule prise en compte par paiement)
        origine_recos = None
        if transaction_id not in profil["derniers_paiements"]:
            mettre_a_jour_profil(profil, paiement)
            if apres.get("produit_id") and apres["statut"] != "echouee":
                mettre_a_jour_preferences(profil, apres["produit_id"], self.categorie_produit(apres["produit_id"]))
                recommandations = recommander(self.reco["modele"], profil["produits_achetes"])
                profil["recommandations"] = recommandations
                profil["recommandations_modele"] = {"nom": MODELE_RECOMMANDATION,
                                                    "version": self.reco["fiche"]["version"], "date": instant_reception}
                origine_recos = [r["origine"] for r in recommandations]
            profil["derniers_paiements"] = (profil["derniers_paiements"] + [transaction_id])[-NB_DERNIERS_PAIEMENTS:]
            profil["date_maj"] = instant_reception
            self.mongo.profils_clients.replace_one({"_id": profil["_id"]}, profil, upsert=True)

        # Renvoi du score dans la base OLTP (condition IS NULL : un score déjà écrit n'est pas remplacé)
        with self.pg.cursor() as cur:
            cur.execute("UPDATE transactions SET score_anomalie = %s WHERE transaction_id = %s AND score_anomalie IS NULL",
                        (score, transaction_id))

        self.enregistrer_suivi(score, choix, latence_ms, origine_recos)
        journal.info("Paiement %s | %s %s | score %.4f | %s | latence %s ms%s",
                     transaction_id[:8], montant, apres["code_devise"], score, choix, latence_ms,
                     " | recommandations mises à jour" if origine_recos else "")

    def traiter_modification(self, apres):
        """Ajout d'un changement de statut à l'historique ; les modifications sans changement de
        statut (écriture du score) et les paiements antérieurs au flux sont ignorés."""
        transaction_id = apres["transaction_id"]
        resultat = self.mongo.transactions_enrichies.update_one(
            {"_id": transaction_id, "statut": {"$ne": apres["statut"]}},
            {"$set": {"statut": apres["statut"]},
             "$push": {"historique_statuts": {"statut": apres["statut"], "date": lire_date(apres["date_maj"])}}},
        )
        if resultat.modified_count:
            journal.info("Paiement %s | nouveau statut : %s", transaction_id[:8], apres["statut"])

    # Suivi en production

    @staticmethod
    def _suivi_vide():
        return {"nb": 0, "bloques": 0, "a_verifier": 0, "somme_scores": 0.0, "latences": [],
                "recos_similarite": 0, "recos_popularite": 0, "debut": datetime.now(timezone.utc)}

    def enregistrer_suivi(self, score, choix, latence_ms, origine_recos):
        s = self.suivi
        s["nb"] += 1
        s["bloques"] += choix == "bloquer"
        s["a_verifier"] += choix == "verifier"
        s["somme_scores"] += score
        s["latences"] = (s["latences"] + [latence_ms])[-FREQUENCE_SUIVI:]
        if origine_recos:
            s["recos_similarite"] += origine_recos.count("similarite")
            s["recos_popularite"] += origine_recos.count("popularite")
        if s["nb"] % FREQUENCE_SUIVI == 0:
            maintenant = datetime.now(timezone.utc)
            self.mongo.modeles_ml.update_one(
                {"nom": MODELE_FRAUDE, "version": self.fraude["fiche"]["version"]},
                {"$set": {"metriques.production": {
                    "nb_paiements": s["nb"], "part_bloquee": round(s["bloques"] / s["nb"], 4),
                    "part_a_verifier": round(s["a_verifier"] / s["nb"], 4),
                    "score_moyen": round(s["somme_scores"] / s["nb"], 4),
                    "latence_mediane_ms": round(statistics.median(s["latences"])),
                    "debut": s["debut"], "date_maj": maintenant}}})
            total_recos = s["recos_similarite"] + s["recos_popularite"]
            if total_recos:
                self.mongo.modeles_ml.update_one(
                    {"nom": MODELE_RECOMMANDATION, "version": self.reco["fiche"]["version"]},
                    {"$set": {"metriques.production": {
                        "nb_recommandations": total_recos,
                        "part_similarite": round(s["recos_similarite"] / total_recos, 4),
                        "debut": s["debut"], "date_maj": maintenant}}})
            journal.info("Suivi : %s paiements notés, %.1f %% bloqués, latence médiane %s ms",
                         s["nb"], 100 * s["bloques"] / s["nb"], round(statistics.median(s["latences"])))

    def consigner_echec(self, message, erreur):
        """Trace d'un message non traité dans les journaux applicatifs (surveillance du flux)."""
        self.mongo.journaux_applicatifs.insert_one({
            "horodatage": datetime.now(timezone.utc), "niveau": "ERREUR",
            "source": {"service": "consommateur-temps-reel", "hote": os.getenv("HOSTNAME", "inconnu")},
            "message": f"Message non traité ({type(erreur).__name__}) : {str(erreur)[:300]}",
            "kafka": {"partition": message.partition(), "position": message.offset()},
        })


def connexions():
    from pymongo import MongoClient
    pg = None
    for tentative in range(30):
        try:
            pg = psycopg.connect(host=os.getenv("OLTP_HOTE", "postgres-oltp"), dbname=os.getenv("OLTP_BASE", "stripe_oltp"),
                                 user=os.environ["OLTP_UTILISATEUR"], password=os.environ["OLTP_MOT_DE_PASSE"],
                                 sslmode=os.getenv("OLTP_SSLMODE", "prefer"), sslrootcert=os.getenv("OLTP_SSLROOTCERT"),
                                 autocommit=True)
            break
        except psycopg.OperationalError:
            journal.info("Base OLTP indisponible, nouvelle tentative (%s/30)", tentative + 1)
            time.sleep(2)
    if pg is None:
        sys.exit("Connexion à la base OLTP impossible")
    mongo = MongoClient(os.environ["MONGO_URL"], tz_aware=True, serverSelectionTimeoutMS=60000)["stripe_nosql"]
    return pg, mongo


def boucle():
    pg, mongo = connexions()
    consommateur = Consommateur(pg, mongo)
    kafka = Consumer({
        "bootstrap.servers": os.getenv("KAFKA_SERVEURS", "kafka:9092"),
        "group.id": os.getenv("KAFKA_GROUPE", "consommateur-temps-reel"),
        "auto.offset.reset": "earliest",      # premier démarrage : lecture depuis le début du sujet
        "enable.auto.commit": False,          # validation manuelle, après traitement
    })
    sujet = os.getenv("KAFKA_SUJET", "stripe.public.transactions")
    kafka.subscribe([sujet])
    journal.info("Écoute du sujet %s", sujet)

    arret = {"demande": False}
    signal.signal(signal.SIGTERM, lambda *_: arret.update(demande=True))
    signal.signal(signal.SIGINT, lambda *_: arret.update(demande=True))

    try:
        while not arret["demande"]:
            message = kafka.poll(1.0)
            consommateur.verifier_modeles()
            if message is None:
                continue
            if message.error():
                raise KafkaException(message.error())
            if message.value() is not None:
                evenement = json.loads(message.value())
                for tentative in range(1, NB_TENTATIVES + 1):
                    try:
                        consommateur.traiter(evenement)
                        break
                    except Exception as erreur:
                        journal.warning("Échec du traitement (tentative %s/%s) : %s", tentative, NB_TENTATIVES, erreur)
                        if tentative == NB_TENTATIVES:
                            consommateur.consigner_echec(message, erreur)
                        else:
                            time.sleep(2)
            kafka.commit(message=message, asynchronous=False)
    finally:
        kafka.close()
        pg.close()
        journal.info("Consommateur arrêté proprement")


if __name__ == "__main__":
    boucle()
