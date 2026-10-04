"""
Chaîne de tâches : réentraînement et suivi des modèles - Stripe Business Case

Fréquence : chaque lundi à 3 h (temps universel), ou déclenchement manuel.

Les traitements sont exécutés par le service d'entraînement (image d'apprentissage, mêmes versions
de bibliothèques que le consommateur temps réel) ; Airflow se limite à l'ordonnancement et au suivi
des résultats. Chaque réentraînement applique la règle champion / challenger : une nouvelle version
n'est activée que si elle fait mieux que la version en service, sur des données qu'aucune des deux
n'a vues. Le consommateur recharge automatiquement la nouvelle version active, sans interruption.

Enchaînement : reentrainer_fraude -> reentrainer_recommandations -> suivre_fraude
"""

from datetime import timedelta

import pendulum
from airflow.sdk import dag, task

import stripe_outils as outils


@dag(
    dag_id="suivi_modeles",
    description="Réentraînement hebdomadaire des modèles et contrôle de dérive en production",
    schedule="0 3 * * 1",
    start_date=pendulum.datetime(2026, 10, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=5)},
    tags=["stripe", "modeles", "mlops"],
    doc_md=__doc__,
)
def suivi_modeles():

    @task
    def reentrainer_fraude():
        return outils.appeler_service_ml("/entrainements/fraude")

    @task
    def reentrainer_recommandations():
        return outils.appeler_service_ml("/entrainements/recommandations")

    @task
    def suivre_fraude():
        return outils.appeler_service_ml("/suivi/fraude")

    reentrainer_fraude() >> reentrainer_recommandations() >> suivre_fraude()


suivi_modeles()
