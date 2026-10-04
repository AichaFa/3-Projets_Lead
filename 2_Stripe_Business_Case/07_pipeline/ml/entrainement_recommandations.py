"""
Entraînement du modèle de recommandation de produits (personnalisation) - Stripe Business Case

Étapes
------
1. Lecture des achats réussis portant sur un produit du catalogue (base OLTP).
2. Choix d'une date de coupure :
   - première version : date laissant 80 % des achats avant elle ;
   - versions suivantes : fin de la période d'entraînement de la version active (les achats
     postérieurs n'ont été vus par aucun des deux modèles : pas de fuite de données).
3. Entraînement d'un modèle candidat sur les achats antérieurs à la coupure.
4. Évaluation : pour chaque client ayant acheté avant ET après la coupure, recommandation de cinq
   produits à partir de son historique antérieur ; réussite si l'un des produits achetés ensuite
   figure parmi ces cinq (taux de réussite à 5). Comparaison avec une référence naïve (les cinq
   produits les plus populaires) pour mesurer l'apport réel du modèle.
5. Champion / challenger : activation de la nouvelle version uniquement si elle fait mieux que la
   version active sur les mêmes clients.
6. Modèle final réentraîné sur tous les achats, enregistré dans MongoDB (GridFS et modeles_ml).

Option --initialiser : constitution, dans chaque profil client, de la liste des produits achetés,
des catégories préférées et des recommandations calculées avec le modèle actif.

Exécution : python entrainement_recommandations.py [--initialiser]
"""

import io
import logging
import sys
from datetime import datetime, timezone

import gridfs
import joblib
import numpy as np
import sklearn
from pymongo import UpdateOne

from entrainement import connexions
from personnalisation import (NB_RECOMMANDATIONS, SEUIL_SIMILARITE, entrainer_similarites,
                              mettre_a_jour_preferences, recommander)

NOM_MODELE = "recommandation_produits"
PART_ENTRAINEMENT = 0.8
NB_MIN_CLIENTS_EVALUATION = 30   # en dessous, la comparaison ne serait pas significative

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
journal = logging.getLogger("recommandations")

# Achats exploitables : paiements non échoués portant sur un produit du catalogue, avec la
# catégorie du marchand (préférences par catégorie), dans l'ordre chronologique
SQL_ACHATS = """
    SELECT t.client_id::text, t.produit_id::text, t.date_heure, m.categorie
    FROM transactions t
    JOIN marchands m ON m.marchand_id = t.marchand_id
    WHERE t.produit_id IS NOT NULL AND t.statut <> 'echouee'
    ORDER BY t.date_heure
"""


def evaluer(modele, achats_avant, achats_apres):
    """Taux de réussite à 5 d'un modèle et de la référence naïve sur les mêmes clients."""
    historiques, cibles = {}, {}
    for client, produit, _, _ in achats_avant:
        historiques.setdefault(client, [])
        if produit not in historiques[client]:
            historiques[client].append(produit)
    for client, produit, _, _ in achats_apres:
        if client in historiques and produit not in historiques[client]:
            cibles.setdefault(client, set()).add(produit)

    reussites_modele, reussites_reference, recommandes = 0, 0, set()
    for client, attendus in cibles.items():
        proposes = {r["produit_id"] for r in recommander(modele, historiques[client])}
        recommandes |= proposes
        reussites_modele += bool(proposes & attendus)
        reference = [p for p in modele["popularite"] if p not in historiques[client]][:NB_RECOMMANDATIONS]
        reussites_reference += bool(set(reference) & attendus)

    nb = len(cibles)
    return {
        "taux_reussite_top5": round(reussites_modele / nb, 4) if nb else 0.0,
        "taux_reussite_reference_popularite": round(reussites_reference / nb, 4) if nb else 0.0,
        "couverture_catalogue": round(len(recommandes) / max(1, len(modele["voisins"])), 4),
        "nb_clients_evalues": nb,
    }


def charger_modele_actif(mongo):
    fiche = mongo.modeles_ml.find_one({"nom": NOM_MODELE, "statut": "actif"})
    if not fiche:
        return None, None
    contenu = gridfs.GridFS(mongo, collection="modeles").get(fiche["fichier_gridfs_id"]).read()
    return fiche, joblib.load(io.BytesIO(contenu))


def entrainer(initialiser=False):
    """Entraîne une nouvelle version et retourne un résumé (statut, version, métriques)."""
    pg, mongo = connexions()
    with pg.cursor() as cur:
        cur.execute(SQL_ACHATS)
        achats = cur.fetchall()
    journal.info("%s achats de produits du catalogue lus", len(achats))

    fiche_active, modele_actif = charger_modele_actif(mongo)
    if fiche_active is None:
        coupure = achats[int(len(achats) * PART_ENTRAINEMENT)][2]
    else:
        coupure = fiche_active["periode"]["fin"]
    achats_avant = [a for a in achats if a[2] <= coupure]
    achats_apres = [a for a in achats if a[2] > coupure]

    candidat = entrainer_similarites((a[0], a[1]) for a in achats_avant)
    metriques = evaluer(candidat, achats_avant, achats_apres)
    journal.info("Évaluation du candidat (coupure au %s) : %s", coupure.date(), metriques)

    if fiche_active is not None and metriques["nb_clients_evalues"] < NB_MIN_CLIENTS_EVALUATION:
        journal.info("Seulement %s clients évaluables depuis la version active %s (minimum %s) : entraînement reporté",
                     metriques["nb_clients_evalues"], fiche_active["version"], NB_MIN_CLIENTS_EVALUATION)
        if initialiser:
            initialiser_profils(pg, mongo, modele_actif, achats, fiche_active["version"])
        pg.close()
        return {"modele": NOM_MODELE, "statut": "reporte", "version_active": fiche_active["version"],
                "nb_clients_evalues": metriques["nb_clients_evalues"], "minimum_requis": NB_MIN_CLIENTS_EVALUATION}

    activer = fiche_active is None
    if fiche_active is not None:
        reference = evaluer(modele_actif, achats_avant, achats_apres)
        activer = metriques["taux_reussite_top5"] > reference["taux_reussite_top5"]
        journal.info("Version active %s sur les mêmes clients : %s", fiche_active["version"], reference)

    # Modèle final sur l'ensemble des achats
    modele = entrainer_similarites((a[0], a[1]) for a in achats)
    tampon = io.BytesIO()
    joblib.dump(modele, tampon)
    derniere = mongo.modeles_ml.find_one({"nom": NOM_MODELE}, sort=[("version", -1)])
    version = (derniere["version"] + 1) if derniere else 1
    fichier_id = gridfs.GridFS(mongo, collection="modeles").put(
        tampon.getvalue(), filename=f"{NOM_MODELE}_v{version}.joblib", content_type="application/octet-stream")
    maintenant = datetime.now(timezone.utc)

    # Fiche du modèle ; seuil_decision : similarité minimale retenue entre deux produits
    mongo.modeles_ml.insert_one({
        "nom": NOM_MODELE,
        "version": version,
        "date_entrainement": maintenant,
        "statut": "candidat",
        "seuil_decision": SEUIL_SIMILARITE,
        "algorithme": "Filtrage collaboratif produit à produit (similarité cosinus)",
        "nb_recommandations": NB_RECOMMANDATIONS,
        "periode": {"debut": achats[0][2], "fin": achats[-1][2]},
        "metriques": {"evaluation": metriques},
        "nb_produits": len(modele["voisins"]),
        "fichier_gridfs_id": fichier_id,
        "versions_bibliotheques": {"scikit-learn": sklearn.__version__, "numpy": np.__version__},
    })
    if activer:
        mongo.modeles_ml.update_many({"nom": NOM_MODELE, "statut": "actif"}, {"$set": {"statut": "archive"}})
        mongo.modeles_ml.update_one({"nom": NOM_MODELE, "version": version}, {"$set": {"statut": "actif"}})
        journal.info("Version %s enregistrée et activée", version)
    else:
        journal.info("Version %s enregistrée comme candidate : pas d'amélioration, version active conservée", version)

    if initialiser:
        modele_service = modele if activer else modele_actif
        version_service = version if activer else fiche_active["version"]
        initialiser_profils(pg, mongo, modele_service, achats, version_service)
    pg.close()
    return {"modele": NOM_MODELE, "statut": "active" if activer else "candidate", "version": version,
            "metriques": metriques}


def initialiser_profils(pg, mongo, modele, achats, version):
    """Ajoute à chaque profil client ses produits achetés, ses catégories préférées et ses recommandations."""
    preferences = {}
    for client, produit, _, categorie in achats:
        mettre_a_jour_preferences(preferences.setdefault(client, {}), produit, categorie)

    maintenant = datetime.now(timezone.utc)
    operations = []
    for profil in mongo.profils_clients.find({}, {"_id": 1}):
        pref = preferences.get(profil["_id"], {"produits_achetes": [], "categories_preferees": {}})
        operations.append(UpdateOne({"_id": profil["_id"]}, {"$set": {
            "produits_achetes": pref["produits_achetes"],
            "categories_preferees": pref["categories_preferees"],
            "recommandations": recommander(modele, pref["produits_achetes"]),
            "recommandations_modele": {"nom": NOM_MODELE, "version": version, "date": maintenant},
        }}))
    if operations:
        mongo.profils_clients.bulk_write(operations, ordered=False)
    journal.info("Préférences et recommandations ajoutées à %s profils clients", len(operations))


if __name__ == "__main__":
    entrainer(initialiser="--initialiser" in sys.argv[1:])
