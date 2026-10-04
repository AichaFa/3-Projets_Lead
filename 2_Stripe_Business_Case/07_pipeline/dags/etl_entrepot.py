"""
Chaîne de tâches : alimentation de l'entrepôt analytique - Stripe Business Case

Fréquence : toutes les 15 minutes (analyses historiques et quasi temps réel).

Enchaînement :
    maintenir_partitions -> charger_dimensions -> charger_faits -> recalculer_agregats -> rafraichir_vues -> controler_qualite
                                                -> charger_audit ----------------------------------------^

Chargement incrémental : seuls les paiements modifiés depuis la précédente exécution sont relus
(filigrane sur la date de modification, table suivi_chargements de l'entrepôt). Toutes les écritures
sont idempotentes : une tâche relancée après un échec ne crée aucun doublon.
"""

from datetime import timedelta

import pendulum
from airflow.sdk import dag, task

import stripe_outils as outils


@dag(
    dag_id="etl_entrepot",
    description="Alimentation incrémentale de l'entrepôt analytique depuis la base transactionnelle",
    schedule="*/15 * * * *",
    start_date=pendulum.datetime(2026, 10, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=1)},
    tags=["stripe", "entrepot", "etl"],
    doc_md=__doc__,
)
def etl_entrepot():

    @task
    def maintenir_partitions():
        return outils.maintenir_partitions()

    @task
    def charger_dimensions():
        return outils.charger_dimensions()

    @task
    def charger_faits():
        return outils.charger_faits()

    @task
    def charger_audit():
        return outils.charger_audit()

    @task
    def recalculer_agregats(jours):
        return outils.recalculer_agregats(jours)

    @task
    def rafraichir_vues():
        return outils.rafraichir_vues()

    @task
    def controler_qualite():
        return outils.controler_qualite()

    dimensions = charger_dimensions()
    jours = charger_faits()
    audit = charger_audit()
    agregats = recalculer_agregats(jours)
    vues = rafraichir_vues()
    qualite = controler_qualite()

    maintenir_partitions() >> dimensions >> jours
    dimensions >> audit
    agregats >> vues >> qualite
    audit >> qualite


etl_entrepot()
