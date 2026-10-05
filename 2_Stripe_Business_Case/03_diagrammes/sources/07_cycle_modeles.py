"""
Diagramme 7 - Cycle de vie des modèles d'apprentissage automatique - Stripe Business Case
Conforme à 07_pipeline/ml (indicateurs.py, entrainement.py, entrainement_recommandations.py,
consommateur.py, suivi.py) et à la chaîne Airflow suivi_modeles.
Sept étapes disposées en cercle : collecte, indices, entraînement, registre, déploiement, suivi,
réentraînement, puis retour à la collecte.
"""

import math
import os

from schema_outils import BLEU_MARINE, GRIS, Schema

s = Schema(2200, 1260, "Cycle de vie des modèles d'apprentissage automatique",
           "Détection de fraude et recommandation de produits : de la collecte des données au réentraînement")

CX, CY, RAYON, L, H = 1100, 640, 440, 330, 130
etapes = [
    ("Base transactionnelle", "1. Collecte", ["paiements et leur contexte", "litiges : fraudes confirmées", "achats pour les recommandations"], "oltp"),
    ("Code partagé", "2. Calcul des indices", ["10 indices (montant, pays, appareil...)", "même code à l'entraînement", "et en production"], "ia"),
    ("Service d'entraînement", "3. Entraînement", ["fraude : HistGradientBoosting", "évaluation sur période récente", "recommandations : similarité cosinus"], "ia"),
    ("MongoDB", "4. Registre des modèles", ["version, statut, métriques", "fichier du modèle (GridFS)", "une seule version active"], "nosql"),
    ("Consommateur temps réel", "5. Déploiement", ["version active rechargée à chaud", "(vérification toutes les 60 s)", "notation en environ 540 ms"], "ia"),
    ("Supervision", "6. Suivi en production", ["part bloquée comparée à l'évaluation", "alerte si elle double ou diminue", "de moitié ; règle Grafana"], "gouvernance"),
    ("Airflow, chaque lundi", "7. Réentraînement", ["reporté sans 10 nouvelles fraudes", "champion / challenger : activé", "seulement si meilleur"], "gouvernance"),
]
boites = []
for i, (domaine, titre, lignes, couche) in enumerate(etapes):
    angle = -math.pi / 2 + i * 2 * math.pi / len(etapes)
    x, y = CX + RAYON * 1.35 * math.cos(angle) - L / 2, CY + RAYON * math.sin(angle) - H / 2
    boites.append(s.boite(x, y, L, H, domaine, titre, lignes, couche=couche))


def bord(boite, vers_x, vers_y):
    """Point du bord du bloc situé sur le segment reliant son centre à un point donné."""
    dx, dy = vers_x - boite["cx"], vers_y - boite["cy"]
    t = min((boite["l"] / 2) / abs(dx) if dx else 1e9, (boite["h"] / 2) / abs(dy) if dy else 1e9)
    return boite["cx"] + dx * t, boite["cy"] + dy * t


for i, a in enumerate(boites):
    b = boites[(i + 1) % len(boites)]
    depart = bord(a, b["cx"], b["cy"])
    arrivee = bord(b, a["cx"], a["cy"])
    # léger retrait pour que la pointe ne touche pas le bord
    dx, dy = arrivee[0] - depart[0], arrivee[1] - depart[1]
    n = math.hypot(dx, dy)
    s.fleche([(depart[0] + dx / n * 6, depart[1] + dy / n * 6), (arrivee[0] - dx / n * 6, arrivee[1] - dy / n * 6)])

# Centre du cycle
s.elements.append(f'<circle cx="{CX}" cy="{CY}" r="205" fill="#F4F8FC" stroke="{BLEU_MARINE}" stroke-width="1.5" stroke-dasharray="6,5"/>')
s.elements.append(s._texte(CX, CY - 110, "Deux modèles, un même cycle", 19, BLEU_MARINE, gras=True))
for i, (texte, gras) in enumerate([
        ("fraude_hgb", True), ("probabilité de fraude de chaque paiement", False), ("AUC de 0,99 à l'évaluation", False), ("", False),
        ("recommandation_produits", True), ("5 produits proposés à chaque client", False),
        ("52,3 % de réussite dans les 5 premiers", False), ("(8,2 % pour la seule popularité)", False)]):
    s.elements.append(s._texte(CX, CY - 72 + i * 23, texte, 15 if gras else 14, "#7030A0" if gras else "#262626", gras=gras))

s.note(40, 1135, 1040, "Une évaluation honnête", [
    "Une fraude n'est confirmée qu'à l'ouverture d'un litige, parfois longtemps après le paiement (délai de maturité).",
    "Deux versions sont comparées sur les seuls paiements postérieurs à l'entraînement de la version active :",
    "  aucune des deux ne les a vus. Critère : précision moyenne (aire sous la courbe précision-rappel)."], couleur="#7030A0")
s.note(1120, 1135, 1040, "Cohérence entre entraînement et production", [
    "Le même module calcule les indices à l'entraînement et en temps réel : un modèle reçoit en production",
    "  exactement les variables qu'il a apprises. Les habitudes du client sont lues dans son profil MongoDB,",
    "  enrichies par chaque paiement non échoué ; toute tentative compte pour la vitesse."], couleur="#7030A0")

s.enregistrer(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "07_cycle_modeles"))
