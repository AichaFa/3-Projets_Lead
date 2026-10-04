"""
Chaîne de tâches : contrôles de conformité automatisés - Stripe Business Case

Fréquence : chaque jour à 6 h (temps universel).

Cinq familles de contrôles exécutées en parallèle (base transactionnelle, entrepôt, capture des
changements, base NoSQL, disponibilité), puis rédaction d'un rapport daté au format Markdown dans
le dossier 08_securite_conformite/rapports, avec la référence réglementaire de chaque contrôle
(RGPD, PCI-DSS). Toute non-conformité fait échouer la dernière tâche : l'anomalie apparaît en
rouge dans Airflow et une trace de niveau ERREUR est écrite dans les journaux applicatifs.
"""

import pendulum
from airflow.sdk import dag, task

import stripe_outils as outils

DOSSIER_RAPPORTS = "/opt/airflow/rapports"


@dag(
    dag_id="controles_conformite",
    description="Contrôles quotidiens de sécurité et de conformité, avec rapport daté",
    schedule="0 6 * * *",
    start_date=pendulum.datetime(2026, 10, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["stripe", "conformite", "securite"],
    doc_md=__doc__,
)
def controles_conformite():

    @task
    def controler_base_transactionnelle():
        return outils.controles_oltp()

    @task
    def controler_entrepot():
        return outils.controles_entrepot()

    @task
    def controler_capture_des_changements():
        return outils.controles_capture()

    @task
    def controler_base_nosql():
        return outils.controles_mongodb()

    @task
    def controler_disponibilite():
        return outils.controles_replication()

    @task
    def rediger_rapport(*familles):
        resultats = [controle for famille in familles for controle in famille]
        bilan = outils.rediger_rapport(resultats, DOSSIER_RAPPORTS)
        if bilan["non_conformes"]:
            raise ValueError(f"Contrôles non conformes : {bilan['non_conformes']} (rapport : {bilan['rapport']})")
        return bilan

    rediger_rapport(
        controler_base_transactionnelle(),
        controler_entrepot(),
        controler_capture_des_changements(),
        controler_base_nosql(),
        controler_disponibilite(),
    )


controles_conformite()
