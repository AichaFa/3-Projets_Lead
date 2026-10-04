# Image des traitements d'apprentissage automatique - Stripe Business Case
# Contient l'entraînement du modèle de fraude et le consommateur temps réel, qui partagent le
# module de calcul des indices (indicateurs.py) : une seule image garantit des versions de
# bibliothèques identiques entre l'entraînement et la production.

# Image de base légère (variante « slim ») de Python 3.12
FROM python:3.12-slim

WORKDIR /app

# Dépendances installées avant la copie du code : cette étape reste en cache tant que
# requirements.txt ne change pas, ce qui accélère les reconstructions
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

# Interpréteur Python en mode non tamponné (-u) : journaux affichés immédiatement par Docker.
# Le programme à lancer est fourni par la commande du service (entrainement.py ou consommateur.py).
ENTRYPOINT ["python", "-u"]
CMD ["entrainement.py"]
