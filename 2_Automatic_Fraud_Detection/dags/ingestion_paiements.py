"""DAG d'ingestion des paiements en temps réel.

Chaque minute : récupère un paiement depuis l'API, contrôle sa qualité,
le prépare, le soumet au modèle de détection, puis enregistre le résultat
dans la base fraud. Une ligne de suivi est écrite à chaque passage.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime

import pendulum
import requests
from airflow.decorators import dag, task
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.sdk import Variable

sys.path.insert(0, "/opt/airflow/src")

URL_API = "https://sdacelo-real-time-fraud-detection.hf.space/current-transactions"
CONN_ID = "fraud_db"
NOM_MODELE = "fraud-detector"
URI_MLFLOW = "http://mlflow:5000"

logger = logging.getLogger("ingestion_paiements")


@dag(
    dag_id="ingestion_paiements",
    schedule="* * * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="Europe/Paris"),
    catchup=False,
    max_active_runs=1,
    tags=["fraude", "ingestion"],
)
def ingestion_paiements():
    @task
    def extraire() -> dict:
        """Récupère le paiement courant depuis l'API temps réel."""
        reponse = requests.get(URL_API, timeout=30)
        reponse.raise_for_status()
        charge = reponse.json()
        if isinstance(charge, str):
            charge = json.loads(charge)
        colonnes = charge["columns"]
        valeurs = charge["data"][0]
        paiement = dict(zip(colonnes, valeurs))
        paiement["_debut_traitement"] = time.monotonic()
        return paiement

    @task
    def controler_qualite(paiement: dict) -> dict:
        """Vérifie que le paiement est exploitable ; sinon le met en quarantaine."""
        motifs = []
        montant = paiement.get("amt")
        if montant is None or float(montant) <= 0:
            motifs.append("montant absent ou non positif")
        for champ in ("lat", "long", "merch_lat", "merch_long"):
            if paiement.get(champ) is None:
                motifs.append(f"coordonnee manquante : {champ}")
        if not paiement.get("trans_num"):
            motifs.append("numero de transaction absent")

        debut = paiement.pop("_debut_traitement", None)
        if motifs:
            hook = PostgresHook(postgres_conn_id=CONN_ID)
            hook.run(
                "INSERT INTO quarantaine (motif, charge_utile) VALUES (%s, %s)",
                parameters=("; ".join(motifs), json.dumps(paiement)),
            )
            return {"valide": False, "paiement": paiement, "debut": debut}
        return {"valide": True, "paiement": paiement, "debut": debut}

    @task
    def predire(resultat_qualite: dict) -> dict:
        """Prépare le paiement et le soumet au modèle chargé depuis MLflow."""
        if not resultat_qualite["valide"]:
            return {"ignore": True}

        import mlflow
        import pandas as pd
        from preprocessing import preparer

        paiement = resultat_qualite["paiement"]
        mlflow.set_tracking_uri(URI_MLFLOW)
        modele = mlflow.sklearn.load_model(f"models:/{NOM_MODELE}/1")

        brut = pd.DataFrame([paiement])
        prepare = preparer(brut)
        colonnes_modele = [c for c in prepare.columns if c != "is_fraud"]
        prediction = int(modele.predict(prepare[colonnes_modele])[0])

        # Interrupteur de demonstration : force une fraude pour tester l alerte.
        # Active via la variable Airflow "forcer_fraude" = "1". Inactif par defaut.
        if Variable.get("forcer_fraude", default="0") == "1":
            prediction = 1

        ligne = prepare.iloc[0]
        return {
            "ignore": False,
            "cc_pseudo": f"****{str(paiement.get('cc_num', ''))[-4:]}",
            "amt": float(ligne["amt"]),
            "category": str(ligne["category"]),
            "gender": str(ligne["gender"]),
            "city_pop": int(ligne["city_pop"]),
            "distance_km": float(ligne["distance_km"]),
            "age": float(ligne["age"]),
            "heure": int(ligne["heure"]),
            "jour_semaine": int(ligne["jour_semaine"]),
            "prediction": prediction,
            "is_fraud_reel": int(paiement["is_fraud"]) if paiement.get("is_fraud") is not None else None,
            "trans_num": paiement.get("trans_num"),
        }

    @task
    def alerter(donnee: dict) -> dict:
        """Émet une alerte visible dans les journaux si une fraude est détectée."""
        if donnee.get("ignore") or int(donnee.get("prediction", 0)) != 1:
            return donnee

        bordure = "=" * 48
        logger.warning(bordure)
        logger.warning("  ALERTE FRAUDE DETECTEE")
        logger.warning("  Montant : %.2f  -  Categorie : %s", donnee["amt"], donnee["category"])
        logger.warning("  Carte : %s  -  Transaction : %s", donnee["cc_pseudo"], donnee["trans_num"])
        logger.warning(bordure)
        return donnee

    @task
    def charger(donnee: dict) -> dict:
        """Enregistre le paiement jugé dans la table transactions."""
        if donnee.get("ignore"):
            return {"charge": False, "fraude": 0}

        hook = PostgresHook(postgres_conn_id=CONN_ID)
        hook.run(
            """
            INSERT INTO transactions
                (cc_pseudo, amt, category, gender, city_pop, distance_km,
                 age, heure, jour_semaine, prediction, is_fraud_reel, trans_num)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (trans_num) DO NOTHING
            """,
            parameters=(
                donnee["cc_pseudo"], donnee["amt"], donnee["category"],
                donnee["gender"], donnee["city_pop"], donnee["distance_km"],
                donnee["age"], donnee["heure"], donnee["jour_semaine"],
                donnee["prediction"], donnee["is_fraud_reel"], donnee["trans_num"],
            ),
        )
        return {"charge": True, "fraude": int(donnee["prediction"] == 1)}

    @task
    def suivre(resultat_qualite: dict, resultat_charge: dict) -> None:
        """Écrit une ligne de suivi d'exécution."""
        rejete = 0 if resultat_qualite["valide"] else 1
        charge = 1 if resultat_charge.get("charge") else 0
        fraude = resultat_charge.get("fraude", 0)

        debut = resultat_qualite.get("debut")
        duree_ms = int((time.monotonic() - debut) * 1000) if debut is not None else None

        hook = PostgresHook(postgres_conn_id=CONN_ID)
        hook.run(
            """
            INSERT INTO suivi_executions
                (recus, valides, rejetes, fraudes_detectees, duree_ms)
            VALUES (%s, %s, %s, %s, %s)
            """,
            parameters=(1, charge, rejete, fraude, duree_ms),
        )

    paiement = extraire()
    qualite = controler_qualite(paiement)
    donnee = predire(qualite)
    donnee_alertee = alerter(donnee)
    charge = charger(donnee_alertee)
    suivre(qualite, charge)


ingestion_paiements()
