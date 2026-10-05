"""
Diagramme 1 - Architecture globale de la plateforme de données - Stripe Business Case
Grille de six colonnes : rangée 1 = flux temps réel, rangée 2 = continuité et apprentissage,
rangée 3 = traitement par lots et analyse, rangée 4 = supervision.
"""

import os

from schema_outils import Schema

COL = [40 + i * 370 for i in range(6)]
L = 260
R1, R2, R3, R4 = 170, 420, 640, 850

s = Schema(2190, 990, "Architecture globale de la plateforme de données",
           "Base transactionnelle, capture des changements, traitement temps réel, base NoSQL, entrepôt analytique, orchestration et supervision")

app = s.boite(COL[0], R1, L, 130, "Source", "Application de paiement",
              ["générateur Python (simulation)", "paiements, remboursements, litiges", "navigation, avis, documents"], couche="contexte")
caisse = s.boite(COL[1], R1, L, 130, "Base transactionnelle (OLTP)", "PostgreSQL 17",
                 ["12 tables normalisées (3FN)", "règles métier, journal d'audit", "e-mails chiffrés, cartes tokenisées"], couche="oltp")
debezium = s.boite(COL[2], R1, L, 130, "Capture des changements", "Debezium 3.7",
                   ["Kafka Connect", "lecture du journal (slot logique)", "adresse IP exclue du flux"], couche="flux")
kafka = s.boite(COL[3], R1, L, 130, "Diffusion", "Kafka 4.3 (KRaft)",
                ["sujet stripe.public.transactions", "clé = client : ordre garanti", "relecture possible"], couche="flux")
conso = s.boite(COL[4], R1, L, 130, "Traitement temps réel", "Consommateur",
                ["10 indices, score, décision", "recommandations de produits", "lit taux et clients dans la caisse"], couche="ia")
mongo = s.boite(COL[5], R1, L, 130, "Base NoSQL", "MongoDB 8.0",
                ["7 collections avec validation", "paiements enrichis, profils", "modèles (GridFS), journaux"], couche="nosql")

replica = s.boite(COL[0], R2, L, 125, "Continuité d'activité", "Réplica PostgreSQL",
                  ["réplication physique en continu", "reprise après sinistre"], couche="oltp")
service = s.boite(COL[4], R2, L, 125, "Apprentissage automatique", "Service d'entraînement",
                  ["FastAPI, réseau interne", "historique lu dans la caisse (TLS)", "règle champion / challenger"], couche="ia")

rapports = s.boite(COL[0], R3, L, 130, "Conformité", "Rapport quotidien",
                   ["13 contrôles RGPD et PCI-DSS", "rapport daté, versionné"], couche="gouvernance")
airflow = s.boite(COL[1], R3, L, 130, "Orchestration", "Airflow 3.3",
                  ["entrepôt : toutes les 15 minutes", "conformité : chaque jour", "modèles : chaque semaine"], couche="gouvernance")
entrepot = s.boite(COL[2], R3, L, 130, "Entrepôt analytique (OLAP)", "PostgreSQL 17",
                   ["schéma en étoile, 7 dimensions", "faits partitionnés par mois", "agrégats, vues matérialisées"], couche="olap")
analystes = s.boite(COL[3], R3, L, 130, "Utilisation", "Analystes et auditeurs",
                    ["requêtes métier, segmentation", "comptes en lecture seule"], couche="contexte")

grafana = s.boite(COL[0], R4, COL[3] + L - COL[0], 95, "Supervision de l'infrastructure",
                  "Grafana 13 : tableau de bord et 5 règles d'alerte",
                  ["comptes en lecture seule, connexion chiffrée à la base transactionnelle"], couche="gouvernance")

# Flux de données temps réel
s.fleche([(app["droite"], app["cy"]), (caisse["gauche"], caisse["cy"])], "paiements\n(TLS)", ((app["droite"] + caisse["gauche"]) / 2, app["cy"] - 22))
s.fleche([(caisse["droite"], caisse["cy"]), (debezium["gauche"], debezium["cy"])], "slot logique\n(TLS)", ((caisse["droite"] + debezium["gauche"]) / 2, caisse["cy"] - 22))
s.fleche([(debezium["droite"], debezium["cy"]), (kafka["gauche"], kafka["cy"])], "événements", ((debezium["droite"] + kafka["gauche"]) / 2, debezium["cy"] - 12))
s.fleche([(kafka["droite"], kafka["cy"]), (conso["gauche"], conso["cy"])], "flux ordonné", ((kafka["droite"] + conso["gauche"]) / 2, kafka["cy"] - 12))
s.fleche([(conso["droite"], conso["cy"]), (mongo["gauche"], mongo["cy"])], "fiches\nenrichies,\nprofils", ((conso["droite"] + mongo["gauche"]) / 2, conso["cy"] - 30))
s.fleche([(app["cx"], app["haut"]), (app["cx"], 140), (mongo["cx"], 140), (mongo["cx"], mongo["haut"])],
         "navigation, avis clients et documents reçus (écriture directe)", ((app["cx"] + mongo["cx"]) / 2, 145))
s.fleche([(conso["x"] + 40, conso["bas"]), (conso["x"] + 40, 345), (caisse["x"] + 220, 345), (caisse["x"] + 220, caisse["bas"])],
         "score de fraude renvoyé à la base transactionnelle (TLS)", ((caisse["x"] + 220 + conso["x"] + 40) / 2, 350), style="retour")
s.fleche([(caisse["x"] + 50, caisse["bas"]), (caisse["x"] + 50, replica["cy"]), (replica["droite"], replica["cy"])],
         "journal des\ntransactions", ((replica["droite"] + caisse["x"] + 50) / 2, replica["cy"] + 4))

# Traitement par lots
s.fleche([(caisse["x"] + 130, caisse["bas"]), (caisse["x"] + 130, airflow["haut"])], "lecture\nincrémentale\n(TLS)", (caisse["x"] + 120, 575), ancre="end")
s.fleche([(airflow["droite"], airflow["cy"]), (entrepot["gauche"], entrepot["cy"])], "chargement,\nagrégats", ((airflow["droite"] + entrepot["gauche"]) / 2, airflow["cy"] - 24))
s.fleche([(entrepot["droite"], entrepot["cy"]), (analystes["gauche"], analystes["cy"])], "analyses", ((entrepot["droite"] + analystes["gauche"]) / 2, entrepot["cy"] - 12))

# Pilotage
s.fleche([(airflow["x"] + 230, airflow["haut"]), (airflow["x"] + 230, service["cy"]), (service["gauche"], service["cy"])],
         "réentraînement hebdomadaire et suivi de dérive (appel du service)", ((airflow["x"] + 230 + service["gauche"]) / 2, service["cy"] - 8), style="pilotage")
s.fleche([(airflow["gauche"], airflow["cy"]), (rapports["droite"], rapports["cy"])], "contrôles\nquotidiens", ((airflow["gauche"] + rapports["droite"]) / 2, airflow["cy"] - 24), style="pilotage")
s.fleche([(service["droite"], service["cy"]), (mongo["cx"], service["cy"]), (mongo["cx"], mongo["bas"])],
         "modèles,\nsuivi", (mongo["cx"] + 12, mongo["bas"] + 50), style="pilotage", ancre="start")

# Supervision
s.fleche([(entrepot["cx"], grafana["haut"]), (entrepot["cx"], entrepot["bas"])], "lecture seule", (entrepot["cx"] + 10, grafana["haut"] - 25), style="supervision", ancre="start")
s.fleche([(grafana["gauche"], grafana["cy"]), (20, grafana["cy"]), (20, 375), (caisse["x"] + 20, 375), (caisse["x"] + 20, caisse["bas"])],
         "lecture seule (TLS)", (200, 370), style="supervision")

s.legende_couches(COL[5] - 20, R3 + 40, ["oltp", "olap", "nosql", "flux", "ia", "gouvernance", "contexte"])
s.legende(COL[4] - 10, R3 + 40, [("donnees", "flux de données"), ("retour", "retour du score de fraude"),
                                  ("pilotage", "pilotage (orchestration)"), ("supervision", "supervision (lecture seule)")])

s.enregistrer(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "01_architecture_globale"))
