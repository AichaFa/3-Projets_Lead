"""
Diagramme 5 - Architecture du pipeline de données - Stripe Business Case
Partie haute : parcours d'un paiement en temps réel (capture des changements, Kafka, notation).
Partie basse : les trois chaînes de traitement par lots d'Airflow, avec l'enchaînement exact des tâches
(07_pipeline/dags : etl_entrepot.py, controles_conformite.py, suivi_modeles.py).
"""

import os

from schema_outils import Schema

s = Schema(2240, 1290, "Architecture du pipeline de données",
           "Traitement en temps réel de chaque paiement, puis traitements par lots orchestrés par Airflow")

# Partie haute : temps réel
s.section(55, 125, "Parcours d'un paiement en temps réel")
L, ECART, Y = 270, 40, 160
etapes = [
    ("Base transactionnelle", "1. Enregistrement", ["paiement inséré (TLS)", "déclencheurs : contrôles, audit"], "oltp"),
    ("Journal des transactions", "2. Conservation", ["journal (WAL), slot logique", "gardé jusqu'à lecture (2 Go)"], "oltp"),
    ("Debezium", "3. Capture", ["événement de modification", "adresse IP retirée"], "flux"),
    ("Kafka", "4. Diffusion", ["clé = client : ordre garanti", "relecture possible"], "flux"),
    ("Consommateur", "5. Indices", ["10 indices calculés", "à partir du profil client"], "ia"),
    ("Modèle de fraude", "6. Score et décision", ["moins de 0,5 : accepter", "de 0,5 à moins de 0,8 : vérifier", "0,8 et plus : bloquer"], "ia"),
    ("MongoDB", "7. Écritures", ["fiche enrichie, profil", "recommandations de produits"], "nosql"),
]
boites = []
for i, (domaine, titre, lignes, couche) in enumerate(etapes):
    boites.append(s.boite(55 + i * (L + ECART), Y, L, 125, domaine, titre, lignes, couche=couche))
for a, b in zip(boites, boites[1:]):
    s.fleche([(a["droite"], a["cy"]), (b["gauche"], b["cy"])])
s.fleche([(boites[6]["cx"], boites[6]["bas"]), (boites[6]["cx"], 335), (boites[0]["cx"], 335), (boites[0]["cx"], boites[0]["bas"])],
         "8. score de fraude renvoyé à la base transactionnelle (TLS), pour la décision de la caisse",
         ((boites[0]["cx"] + boites[6]["cx"]) / 2, 340), style="retour")

s.note(55, 375, 690, "Latence", [
    "Environ 540 millisecondes (médiane mesurée) entre l'enregistrement du paiement",
    "  et sa décision ; suivie en continu dans les fiches enrichies (latence_ms)"])
s.note(775, 375, 690, "Aucune perte de paiement", [
    "Slot de réplication : le journal est conservé tant que Debezium ne l'a pas lu ;",
    "  position Kafka validée seulement après traitement (au moins une fois)"])
s.note(1495, 375, 690, "Ordre et absence de doublon", [
    "Paiements d'un même client traités dans l'ordre (clé de partition) ;",
    "  écritures idempotentes ; 3 tentatives, puis échec consigné"])

# Partie basse : traitements par lots
s.section(55, 525, "Traitements par lots orchestrés par Airflow 3.3")
TL, TH = 215, 58

def couloir(y, h, frequence, nom, details):
    return s.boite(55, y, 270, h, frequence, nom, details, couche="gouvernance")

# Chaîne 1 : alimentation de l'entrepôt
c1 = couloir(560, 200, "Toutes les 15 minutes", "etl_entrepot", ["2 nouvelles tentatives", "une exécution à la fois"])
t_part = s.tache(370, 631, TL, TH, "maintenir_partitions", "partitions mensuelles", "olap")
t_dim = s.tache(615, 631, TL, TH, "charger_dimensions", "clients, marchands...", "olap")
t_faits = s.tache(860, 572, TL, TH, "charger_faits", "paiements depuis le filigrane", "olap")
t_audit = s.tache(860, 690, TL, TH, "charger_audit", "journal d'audit", "olap")
t_agg = s.tache(1105, 572, TL, TH, "recalculer_agregats", "jours touchés seulement", "olap")
t_vues = s.tache(1350, 572, TL, TH, "rafraichir_vues", "sans bloquer les lectures", "olap")
t_qual = s.tache(1595, 631, TL, TH, "controler_qualite", "volumes, cohérence", "olap")
s.fleche([(c1["droite"], t_part["cy"]), (t_part["gauche"], t_part["cy"])])
s.fleche([(t_part["droite"], t_part["cy"]), (t_dim["gauche"], t_dim["cy"])])
s.fleche([(t_dim["droite"], t_dim["cy"]), (838, t_dim["cy"]), (838, t_faits["cy"]), (t_faits["gauche"], t_faits["cy"])])
s.fleche([(t_dim["droite"], t_dim["cy"]), (838, t_dim["cy"]), (838, t_audit["cy"]), (t_audit["gauche"], t_audit["cy"])])
s.fleche([(t_faits["droite"], t_faits["cy"]), (t_agg["gauche"], t_agg["cy"])])
s.fleche([(t_agg["droite"], t_agg["cy"]), (t_vues["gauche"], t_vues["cy"])])
s.fleche([(t_vues["droite"], t_vues["cy"]), (1580, t_vues["cy"]), (1580, t_qual["cy"] - 12), (t_qual["gauche"], t_qual["cy"] - 12)])
s.fleche([(t_audit["droite"], t_audit["cy"]), (1580, t_audit["cy"]), (1580, t_qual["cy"] + 12), (t_qual["gauche"], t_qual["cy"] + 12)])
r1 = s.tache(1870, 631, 315, TH, "Entrepôt à jour", "filigrane enregistré", "olap")
s.fleche([(t_qual["droite"], t_qual["cy"]), (r1["gauche"], r1["cy"])])

# Chaîne 2 : contrôles de conformité
c2 = couloir(790, 210, "Chaque jour à 6 heures", "controles_conformite", ["13 contrôles", "RGPD et PCI-DSS"])
# Cinq contrôles exécutés en parallèle, réunis par un trait commun vers la rédaction du rapport
controles = [
    ("controler_base_transactionnelle", "chiffrement, TLS, audit", 250),
    ("controler_entrepot", "minimisation", 180),
    ("controler_capture_des_changements", "IP exclue, secrets, état", 262),
    ("controler_base_nosql", "validation, expiration", 192),
    ("controler_disponibilite", "réplica, retard de capture", 205),
]
t_rapport = s.tache(1595, 905, TL, TH, "rediger_rapport", "échec si non conforme", "gouvernance")
x, Y_BUS = 370, t_rapport["cy"]
for nom, detail, largeur in controles:
    t = s.tache(x, 805, largeur, TH, nom, detail, "gouvernance")
    s.fleche([(t["cx"], t["bas"]), (t["cx"], Y_BUS), (t_rapport["gauche"], Y_BUS)])
    x += largeur + 20
s.fleche([(c2["droite"], 834), (370, 834)])
r2 = s.tache(1870, 905, 315, TH, "Rapport Markdown daté", "08_securite_conformite/rapports", "gouvernance")
s.fleche([(t_rapport["droite"], t_rapport["cy"]), (r2["gauche"], r2["cy"])])

# Chaîne 3 : suivi des modèles
c3 = couloir(1030, 200, "Chaque lundi à 3 heures", "suivi_modeles", ["appels au service", "d'entraînement"])
t_f = s.tache(370, 1101, TL, TH, "reentrainer_fraude", "si nouveaux litiges", "ia")
t_r = s.tache(615, 1101, 260, TH, "reentrainer_recommandations", "évaluation sur achats récents", "ia")
t_s = s.tache(905, 1101, TL, TH, "suivre_fraude", "dérive production", "ia")
s.fleche([(c3["droite"], t_f["cy"]), (t_f["gauche"], t_f["cy"])])
s.fleche([(t_f["droite"], t_f["cy"]), (t_r["gauche"], t_r["cy"])])
s.fleche([(t_r["droite"], t_r["cy"]), (t_s["gauche"], t_s["cy"])])
s.note(1160, 1060, 1025, "Règle champion / challenger", [
    "Une nouvelle version n'est activée que si elle fait mieux que la version en service",
    "  sur des données jamais vues ; sinon, elle reste candidate dans le registre des modèles",
    "Dérive : part de paiements bloqués en production comparée à l'évaluation ; alerte consignée dans",
    "  les journaux techniques si l'écart dépasse le double (Grafana la surveille aussi en continu)"], couleur="#7030A0")

s.enregistrer(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "05_pipeline"))
