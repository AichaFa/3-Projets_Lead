"""
Entraînement du modèle de détection de fraude - Stripe Business Case

Apprentissage supervisé : le modèle apprend à distinguer les paiements frauduleux des paiements
normaux à partir d'exemples dont l'issue est connue.

Étapes
------
1. Lecture de l'historique des paiements de la base OLTP, montants convertis en euros au taux
   du jour du paiement.
2. Rejeu chronologique des paiements pour calculer les indices de chacun (module indicateurs),
   exactement comme le fera le consommateur temps réel.
3. Étiquette : un paiement est considéré comme frauduleux s'il a fait l'objet d'un litige pour
   motif « fraude ». Limite connue : une partie des fraudes n'est jamais contestée et reste
   étiquetée comme normale (étiquettes incomplètes), ce qui sous-estime la précision mesurée.
4. Exclusion des 30 derniers jours : un litige est ouvert plusieurs jours ou semaines après le
   paiement ; sur la période récente, des fraudes ne sont pas encore connues et fausseraient
   l'apprentissage (maturité des étiquettes).
5. Première version : découpage temporel 80 / 20 et évaluation sur la période la plus récente.
6. Versions suivantes : évaluation de la candidate et de la version active sur les seuls paiements
   postérieurs à l'entraînement de la version active (aucun des deux modèles ne les a vus : pas de
   fuite de données) ; entraînement reporté si ces nouveaux paiements comptent trop peu de fraudes.
7. Enregistrement du modèle dans MongoDB (fichier dans GridFS, fiche dans modeles_ml) et activation
   uniquement en cas d'amélioration (principe champion / challenger).

Option --initialiser (première mise en service uniquement, avant le branchement du connecteur CDC) :
attribution d'un score à l'historique des paiements dans la base OLTP et constitution des profils
clients dans MongoDB, point de départ du consommateur temps réel.

Exécution : python entrainement.py [--initialiser]
"""

import io
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import gridfs
import joblib
import numpy as np
import psycopg
import sklearn
from pymongo import MongoClient, ReplaceOne
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, precision_score, recall_score, roc_auc_score

from indicateurs import NOMS_INDICES, calculer_indices, mettre_a_jour_profil, profil_vide, vecteur

# Paramètres du modèle et de la politique de décision
NOM_MODELE = "fraude_hgb"            # hgb : HistGradientBoosting
SEUIL_VERIFICATION = 0.5             # à partir de ce score : vérification complémentaire
SEUIL_BLOCAGE = 0.8                  # à partir de ce score : paiement bloqué
JOURS_MATURITE = 30                  # délai laissé à l'ouverture des litiges
PART_ENTRAINEMENT = 0.8              # première version : 80 % anciens pour apprendre, 20 % récents pour évaluer
NB_MIN_FRAUDES_EVALUATION = 10       # en dessous, une comparaison de versions ne serait pas significative
GRAINE = 42                          # résultats reproductibles d'une exécution à l'autre

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
journal = logging.getLogger("entrainement")

# Lecture de l'historique, trié chronologiquement (indispensable au rejeu des profils).
# Conversion en euros : taux du jour du paiement ou, à défaut, dernier taux connu avant cette date
# (jointure LATERAL) ; si aucun taux antérieur n'existe, premier taux disponible de la devise.
# Étiquette : présence d'un litige pour motif « fraude » (au plus un litige par paiement).
SQL_HISTORIQUE = """
    SELECT t.transaction_id, t.client_id, t.marchand_id, t.statut, t.date_heure, t.pays_ip, t.type_appareil,
           round(t.montant * COALESCE(tc.taux_vers_eur,
                 (SELECT taux_vers_eur FROM taux_change WHERE code_devise = t.code_devise ORDER BY date_taux LIMIT 1)), 2) AS montant_eur,
           c.code_pays, c.date_creation,
           COALESCE(l.motif = 'fraude', false) AS est_fraude
    FROM transactions t
    JOIN clients c ON c.client_id = t.client_id
    LEFT JOIN LATERAL (
        SELECT taux_vers_eur FROM taux_change
        WHERE code_devise = t.code_devise AND date_taux <= t.date_heure::date
        ORDER BY date_taux DESC LIMIT 1
    ) tc ON true
    LEFT JOIN litiges l ON l.transaction_id = t.transaction_id
    ORDER BY t.date_heure, t.transaction_id
"""


def connexions():
    """Ouvre les connexions à la base OLTP et à MongoDB.

    Nouvelles tentatives pendant une minute : au démarrage de l'ensemble des conteneurs, la base
    peut ne pas être encore prête. Chiffrement TLS de la connexion à la base OLTP selon les
    variables OLTP_SSLMODE et OLTP_SSLROOTCERT. tz_aware=True : MongoDB restitue des dates avec fuseau horaire,
    comparables à celles de PostgreSQL.
    """
    pg = None
    for tentative in range(30):
        try:
            pg = psycopg.connect(host=os.getenv("OLTP_HOTE", "postgres-oltp"), dbname=os.getenv("OLTP_BASE", "stripe_oltp"),
                                 user=os.environ["OLTP_UTILISATEUR"], password=os.environ["OLTP_MOT_DE_PASSE"],
                                 sslmode=os.getenv("OLTP_SSLMODE", "prefer"), sslrootcert=os.getenv("OLTP_SSLROOTCERT"))
            break
        except psycopg.OperationalError:
            journal.info("Base OLTP indisponible, nouvelle tentative (%s/30)", tentative + 1)
            time.sleep(2)
    if pg is None:
        sys.exit("Connexion à la base OLTP impossible")
    mongo = MongoClient(os.environ["MONGO_URL"], tz_aware=True, serverSelectionTimeoutMS=60000)["stripe_nosql"]
    return pg, mongo


def rejouer_historique(pg):
    """Calcule les indices de chaque paiement dans l'ordre chronologique.

    Pour chaque paiement : indices calculés avec le profil du client AVANT ce paiement, puis mise
    à jour du profil. Retourne la matrice des indices (X), les étiquettes (y), les dates, les
    identifiants des paiements et les profils finaux de tous les clients.
    """
    with pg.cursor() as cur:
        cur.execute(SQL_HISTORIQUE)
        colonnes = [d.name for d in cur.description]
        lignes = [dict(zip(colonnes, r)) for r in cur.fetchall()]
    profils, X, y, dates, identifiants = {}, [], [], [], []
    for p in lignes:
        cle = str(p["client_id"])
        if cle not in profils:
            profils[cle] = profil_vide(p["client_id"], p["code_pays"], p["date_creation"])
        X.append(vecteur(calculer_indices(profils[cle], p)))
        y.append(int(p["est_fraude"]))
        dates.append(p["date_heure"])
        identifiants.append(p["transaction_id"])
        mettre_a_jour_profil(profils[cle], p)
    return np.array(X), np.array(y), np.array(dates), identifiants, profils


def mesurer(y_vrai, scores):
    """Indicateurs de performance d'un modèle sur un ensemble de paiements.

    - auc_roc : probabilité qu'une fraude reçoive un score supérieur à un paiement normal
      (1 = classement parfait, 0,5 = hasard) ;
    - precision_moyenne : aire sous la courbe précision-rappel, plus exigeante que l'AUC quand
      les fraudes sont rares (critère retenu pour comparer deux versions) ;
    - precision_seuil_blocage : part de fraudes connues parmi les paiements bloqués ;
    - rappel_seuil_blocage : part des fraudes connues effectivement bloquées ;
    - part_a_verifier, part_bloquee : impact opérationnel (volume de vérifications et de refus).
    """
    return {
        "auc_roc": round(float(roc_auc_score(y_vrai, scores)), 4),
        "precision_moyenne": round(float(average_precision_score(y_vrai, scores)), 4),
        "precision_seuil_blocage": round(float(precision_score(y_vrai, scores >= SEUIL_BLOCAGE, zero_division=0)), 4),
        "rappel_seuil_blocage": round(float(recall_score(y_vrai, scores >= SEUIL_BLOCAGE, zero_division=0)), 4),
        "part_a_verifier": round(float(np.mean((scores >= SEUIL_VERIFICATION) & (scores < SEUIL_BLOCAGE))), 4),
        "part_bloquee": round(float(np.mean(scores >= SEUIL_BLOCAGE)), 4),
        "nb_exemples": int(len(y_vrai)),
        "nb_fraudes": int(y_vrai.sum()),
    }


def charger_modele_actif(mongo):
    """Retourne la fiche et le modèle de la version active, ou (None, None) si aucune n'existe.
    Le fichier du modèle est lu dans GridFS (seau « modeles ») à partir de la référence de la fiche."""
    fiche = mongo.modeles_ml.find_one({"nom": NOM_MODELE, "statut": "actif"})
    if not fiche:
        return None, None
    contenu = gridfs.GridFS(mongo, collection="modeles").get(fiche["fichier_gridfs_id"]).read()
    return fiche, joblib.load(io.BytesIO(contenu))


def entrainer(initialiser=False):
    """Entraîne une nouvelle version et retourne un résumé (statut, version, métriques)."""
    pg, mongo = connexions()
    X, y, dates, identifiants, profils = rejouer_historique(pg)

    # Paiements « matures » : antérieurs à la période de maturité des étiquettes
    maintenant = datetime.now(timezone.utc)
    matures = dates < maintenant - timedelta(days=JOURS_MATURITE)
    X_m, y_m, dates_m = X[matures], y[matures], dates[matures]
    journal.info("%s paiements rejoués, %s exploitables (hors %s derniers jours), dont %s fraudes étiquetées",
                 len(X), len(X_m), JOURS_MATURITE, int(y_m.sum()))

    # Choix de la période d'évaluation (masque booléen : True = paiement réservé à l'évaluation)
    fiche_active, modele_actif = charger_modele_actif(mongo)
    if fiche_active is None:
        # Première version : les 20 % de paiements les plus récents
        evaluation = np.arange(len(X_m)) >= int(len(X_m) * PART_ENTRAINEMENT)
    else:
        # Versions suivantes : uniquement les paiements postérieurs à la fin d'entraînement de la
        # version active, jamais vus par aucun des deux modèles (comparaison équitable)
        evaluation = np.array([d > fiche_active["periode"]["fin"] for d in dates_m], dtype=bool)
        nb_fraudes_nouvelles = int(y_m[evaluation].sum())
        if nb_fraudes_nouvelles < NB_MIN_FRAUDES_EVALUATION:
            journal.info("Seulement %s fraudes étiquetées depuis l'entraînement de la version active %s "
                         "(minimum %s) : entraînement reporté", nb_fraudes_nouvelles, fiche_active["version"],
                         NB_MIN_FRAUDES_EVALUATION)
            if initialiser:
                initialiser_historique(pg, mongo, modele_actif, X, identifiants, profils)
            pg.close()
            return {"modele": NOM_MODELE, "statut": "reporte", "version_active": fiche_active["version"],
                    "nb_fraudes_nouvelles": nb_fraudes_nouvelles, "minimum_requis": NB_MIN_FRAUDES_EVALUATION}

    # HistGradientBoosting : ensemble d'arbres de décision construits successivement, chacun
    # corrigeant les erreurs des précédents ; rapide et adapté aux indices de natures différentes.
    # class_weight="balanced" : les fraudes, très minoritaires, pèsent autant au total que les
    # paiements normaux, sans quoi le modèle apprendrait à toujours répondre « normal ».
    modele = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.1, class_weight="balanced", random_state=GRAINE)
    modele.fit(X_m[~evaluation], y_m[~evaluation])
    metriques = mesurer(y_m[evaluation], modele.predict_proba(X_m[evaluation])[:, 1])
    journal.info("Évaluation sur %s paiements jamais vus : %s", int(evaluation.sum()), metriques)

    # Champion / challenger : la candidate ne remplace la version active que si elle fait mieux
    # sur les mêmes paiements, selon la précision moyenne
    activer = fiche_active is None
    if fiche_active is not None:
        reference = mesurer(y_m[evaluation], modele_actif.predict_proba(X_m[evaluation])[:, 1])
        activer = metriques["precision_moyenne"] > reference["precision_moyenne"]
        journal.info("Version active %s sur les mêmes paiements : %s", fiche_active["version"], reference)

    # Modèle final réentraîné sur toute la période exploitable : l'évaluation a validé la méthode,
    # le modèle mis en service profite de toutes les données disponibles
    modele.fit(X_m, y_m)

    # Sérialisation du modèle en mémoire (joblib) puis stockage du fichier dans GridFS
    tampon = io.BytesIO()
    joblib.dump(modele, tampon)
    derniere = mongo.modeles_ml.find_one({"nom": NOM_MODELE}, sort=[("version", -1)])
    version = (derniere["version"] + 1) if derniere else 1
    fichier_id = gridfs.GridFS(mongo, collection="modeles").put(
        tampon.getvalue(), filename=f"{NOM_MODELE}_v{version}.joblib", content_type="application/octet-stream")

    # Fiche du modèle : traçabilité complète (algorithme, indices, période d'apprentissage,
    # performances, versions des bibliothèques nécessaires pour recharger le fichier)
    mongo.modeles_ml.insert_one({
        "nom": NOM_MODELE,
        "version": version,
        "date_entrainement": maintenant,
        "statut": "candidat",
        "seuil_decision": SEUIL_BLOCAGE,
        "seuil_verification": SEUIL_VERIFICATION,
        "algorithme": "HistGradientBoostingClassifier",
        "indices": NOMS_INDICES,
        "periode": {"debut": dates_m[0], "fin": dates_m[-1]},
        "metriques": {"evaluation": metriques},
        "fichier_gridfs_id": fichier_id,
        "versions_bibliotheques": {"scikit-learn": sklearn.__version__, "numpy": np.__version__},
    })

    # Activation : archivage de l'ancienne version active AVANT activation de la nouvelle
    # (l'index unique partiel de modeles_ml interdit deux versions actives simultanées)
    if activer:
        mongo.modeles_ml.update_many({"nom": NOM_MODELE, "statut": "actif"}, {"$set": {"statut": "archive"}})
        mongo.modeles_ml.update_one({"nom": NOM_MODELE, "version": version}, {"$set": {"statut": "actif"}})
        journal.info("Version %s enregistrée et activée", version)
    else:
        journal.info("Version %s enregistrée comme candidate : pas d'amélioration, version active conservée", version)

    if initialiser:
        initialiser_historique(pg, mongo, modele, X, identifiants, profils)
    pg.close()
    return {"modele": NOM_MODELE, "statut": "active" if activer else "candidate", "version": version,
            "metriques": metriques}


def initialiser_historique(pg, mongo, modele, X, identifiants, profils):
    """Première mise en service : score de l'historique dans la base OLTP et profils clients dans MongoDB.

    À exécuter avant la création du connecteur CDC : sinon, chaque mise à jour de score serait
    transmise à Kafka et retraitée par le consommateur.
    """
    # Scores arrondis à 4 décimales, format de la colonne transactions.score_anomalie NUMERIC(5,4)
    scores = np.round(modele.predict_proba(X)[:, 1], 4)
    with pg, pg.cursor() as cur:
        cur.executemany("UPDATE transactions SET score_anomalie = %s WHERE transaction_id = %s",
                        [(float(s), i) for s, i in zip(scores, identifiants)])
    journal.info("Score attribué à %s paiements historiques", len(identifiants))

    # Profils écrits en une seule opération groupée ; ReplaceOne avec upsert : remplacement si le
    # profil existe, création sinon (exécution répétable sans doublon)
    maintenant = datetime.now(timezone.utc)
    operations = []
    for profil in profils.values():
        document = dict(profil, date_maj=maintenant)
        operations.append(ReplaceOne({"_id": profil["_id"]}, document, upsert=True))
    if operations:
        mongo.profils_clients.bulk_write(operations, ordered=False)
    journal.info("%s profils clients constitués dans MongoDB", len(operations))


if __name__ == "__main__":
    entrainer(initialiser="--initialiser" in sys.argv[1:])
