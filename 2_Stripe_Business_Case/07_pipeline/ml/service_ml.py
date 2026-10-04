"""
Service d'entraînement et de suivi des modèles (interface web interne) - Stripe Business Case

Rôle : exécuter les entraînements et le suivi dans l'environnement exact de l'image
d'apprentissage (mêmes versions de scikit-learn et numpy que le consommateur temps réel), à la
demande de l'orchestrateur Airflow. Un modèle entraîné dans un autre environnement risquerait de
ne pas pouvoir être rechargé par le consommateur.

Points d'accès :
- GET  /sante                         : disponibilité du service
- POST /entrainements/fraude          : réentraînement du modèle de fraude (champion / challenger)
- POST /entrainements/recommandations : réentraînement du modèle de recommandation
- POST /suivi/fraude                  : contrôle de dérive et performance provisoire en production

Sécurité : service accessible uniquement sur le réseau interne Docker (aucun port publié sur la
machine hôte). Un verrou empêche deux entraînements simultanés (réponse 409 si occupé).
"""

import threading

from fastapi import FastAPI, HTTPException

import entrainement
import entrainement_recommandations
import suivi

app = FastAPI(title="Service ML - Stripe Business Case")
verrou = threading.Lock()


def executer(traitement):
    if not verrou.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Un traitement est déjà en cours")
    try:
        return traitement()
    finally:
        verrou.release()


@app.get("/sante")
def sante():
    return {"statut": "disponible"}


@app.post("/entrainements/fraude")
def entrainer_fraude():
    return executer(entrainement.entrainer)


@app.post("/entrainements/recommandations")
def entrainer_recommandations():
    return executer(entrainement_recommandations.entrainer)


@app.post("/suivi/fraude")
def suivre_fraude():
    return executer(suivi.suivre_fraude)
