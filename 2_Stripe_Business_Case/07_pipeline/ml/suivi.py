"""
Suivi du modèle de détection de fraude en production - Stripe Business Case

Deux contrôles complémentaires :

1. Dérive du comportement : comparaison des indicateurs de production (écrits par le consommateur
   temps réel dans la fiche du modèle) avec ceux mesurés à l'évaluation. Une part de paiements
   bloqués très différente signale que les paiements ne ressemblent plus à ceux de l'entraînement
   (évolution des comportements, nouvelle forme de fraude, problème de données en amont).

2. Performance réelle provisoire : confrontation des décisions prises en direct aux litiges pour
   fraude connus à ce jour dans la base OLTP. Mesure provisoire, car les litiges arrivent avec
   plusieurs semaines de retard : elle se consolide avec le temps.

Résultats écrits dans la fiche du modèle (metriques.suivi) ; en cas de dérive au-delà du seuil,
alerte de niveau AVERTISSEMENT dans les journaux applicatifs, exploitable par la supervision.
"""

from datetime import datetime, timezone

from entrainement import NOM_MODELE, SEUIL_BLOCAGE, connexions

# Rapport maximal toléré entre la part bloquée en production et la part bloquée à l'évaluation
# (dans un sens ou dans l'autre) avant de signaler une dérive
RAPPORT_ALERTE_DERIVE = 2.0
NB_MIN_PAIEMENTS_PRODUCTION = 100   # en dessous, les indicateurs de production ne sont pas significatifs


def pourcentage(part):
    """Part (entre 0 et 1) écrite en pourcentage au format français, par exemple 0.1825 -> 18,3 %."""
    return f"{part * 100:.1f} %".replace(".", ",")


def suivre_fraude():
    pg, mongo = connexions()
    fiche = mongo.modeles_ml.find_one({"nom": NOM_MODELE, "statut": "actif"})
    if fiche is None:
        pg.close()
        return {"modele": NOM_MODELE, "statut": "aucune version active"}
    maintenant = datetime.now(timezone.utc)
    evaluation = fiche["metriques"].get("evaluation", {})
    production = fiche["metriques"].get("production")

    # 1. Dérive
    if not production or production["nb_paiements"] < NB_MIN_PAIEMENTS_PRODUCTION:
        derive = {"statut": "non mesurable", "motif": "moins de %s paiements notés en production" % NB_MIN_PAIEMENTS_PRODUCTION}
    else:
        part_eval = max(evaluation.get("part_bloquee", 0.0), 1e-4)
        rapport = production["part_bloquee"] / part_eval
        alerte = rapport > RAPPORT_ALERTE_DERIVE or rapport < 1 / RAPPORT_ALERTE_DERIVE
        derive = {"statut": "alerte" if alerte else "normal",
                  "part_bloquee_evaluation": evaluation.get("part_bloquee"),
                  "part_bloquee_production": production["part_bloquee"],
                  "rapport": round(rapport, 2), "seuil_rapport": RAPPORT_ALERTE_DERIVE}

    # 2. Performance réelle provisoire sur les paiements notés en direct par la version active
    notes = list(mongo.transactions_enrichies.find(
        {"score.version": fiche["version"], "score.modele": NOM_MODELE}, {"_id": 1, "score.valeur": 1}))
    identifiants = [n["_id"] for n in notes]
    with pg.cursor() as cur:
        cur.execute("SELECT transaction_id::text FROM litiges WHERE motif = 'fraude' AND transaction_id = ANY(%s::uuid[])",
                    (identifiants,))
        fraudes = {r[0] for r in cur.fetchall()}
    bloques = {n["_id"] for n in notes if n["score"]["valeur"] >= SEUIL_BLOCAGE}
    performance = {
        "nb_paiements_notes": len(notes),
        "nb_fraudes_connues": len(fraudes),
        "nb_bloques": len(bloques),
        "rappel_provisoire": round(len(fraudes & bloques) / len(fraudes), 4) if fraudes else None,
        "precision_provisoire": round(len(fraudes & bloques) / len(bloques), 4) if bloques else None,
    }

    resultat = {"date": maintenant, "derive": derive, "performance_provisoire": performance}
    mongo.modeles_ml.update_one({"_id": fiche["_id"]}, {"$set": {"metriques.suivi": resultat}})
    if derive["statut"] == "alerte":
        mongo.journaux_applicatifs.insert_one({
            "horodatage": maintenant, "niveau": "AVERTISSEMENT",
            "source": {"service": "suivi-modeles", "hote": "service-ml"},
            "message": (f"Dérive du modèle {NOM_MODELE} version {fiche['version']} : part bloquée en production "
                        f"{pourcentage(derive['part_bloquee_production'])} contre {pourcentage(derive['part_bloquee_evaluation'])} à l'évaluation"),
        })
    pg.close()
    return {"modele": NOM_MODELE, "version": fiche["version"], **resultat, "date": maintenant.isoformat()}
