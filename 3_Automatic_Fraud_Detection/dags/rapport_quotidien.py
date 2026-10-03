"""DAG de rapport quotidien.

Chaque matin, calcule le bilan des paiements de la veille (nombre,
fraudes détectées, montants, rejets, passages du pipeline) et l'écrit
dans les journaux. Prépare le terrain pour un envoi par e-mail ultérieur.
"""

from __future__ import annotations

import logging

import pendulum
from airflow.decorators import dag, task
from airflow.providers.postgres.hooks.postgres import PostgresHook

CONN_ID = "fraud_db"

logger = logging.getLogger("rapport_quotidien")


@dag(
    dag_id="rapport_quotidien",
    schedule="0 8 * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="Europe/Paris"),
    catchup=False,
    max_active_runs=1,
    tags=["fraude", "rapport"],
)
def rapport_quotidien():
    @task
    def calculer_bilan() -> dict:
        """Interroge la base pour établir le bilan de la veille."""
        hook = PostgresHook(postgres_conn_id=CONN_ID)

        # Fenêtre : la journée d'hier, en heure de Paris.
        transactions = hook.get_first(
            """
            SELECT
                count(*),
                coalesce(sum(CASE WHEN prediction = 1 THEN 1 ELSE 0 END), 0),
                coalesce(sum(amt), 0),
                coalesce(sum(CASE WHEN prediction = 1 THEN amt ELSE 0 END), 0)
            FROM transactions
            WHERE (recu_le AT TIME ZONE 'Europe/Paris')::date
                  = ((now() AT TIME ZONE 'Europe/Paris')::date - INTERVAL '1 day')
            """
        )
        rejets = hook.get_first(
            """
            SELECT count(*)
            FROM quarantaine
            WHERE (recu_le AT TIME ZONE 'Europe/Paris')::date
                  = ((now() AT TIME ZONE 'Europe/Paris')::date - INTERVAL '1 day')
            """
        )
        passages = hook.get_first(
            """
            SELECT count(*)
            FROM suivi_executions
            WHERE (execute_le AT TIME ZONE 'Europe/Paris')::date
                  = ((now() AT TIME ZONE 'Europe/Paris')::date - INTERVAL '1 day')
            """
        )

        return {
            "paiements": int(transactions[0]),
            "fraudes": int(transactions[1]),
            "montant_total": float(transactions[2]),
            "montant_fraudes": float(transactions[3]),
            "rejets": int(rejets[0]),
            "passages": int(passages[0]),
        }

    @task
    def publier_bilan(bilan: dict) -> None:
        """Écrit le bilan de la veille dans les journaux."""
        bordure = "=" * 48
        logger.info(bordure)
        logger.info("  BILAN DES PAIEMENTS DE LA VEILLE")
        logger.info(bordure)
        logger.info("  Paiements traites      : %d", bilan["paiements"])
        logger.info("  Fraudes detectees      : %d", bilan["fraudes"])
        logger.info("  Montant total          : %.2f", bilan["montant_total"])
        logger.info("  Montant des fraudes    : %.2f", bilan["montant_fraudes"])
        logger.info("  Paiements rejetes      : %d", bilan["rejets"])
        logger.info("  Passages du pipeline   : %d", bilan["passages"])
        logger.info(bordure)

    publier_bilan(calculer_bilan())


rapport_quotidien()
