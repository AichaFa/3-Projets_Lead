# Image du générateur de données fictives - Stripe Business Case

# Image de base légère (variante « slim ») de Python 3.12
FROM python:3.12-slim

WORKDIR /app

# Dépendances installées avant la copie du code : cette étape reste en cache tant que
# requirements.txt ne change pas, ce qui accélère les reconstructions
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY generateur.py .

# Interpréteur Python en mode non tamponné (-u) : journaux affichés immédiatement par Docker.
# Mode par défaut « direct » ; le mode « historique » est passé en argument lors d'un lancement ponctuel.
ENTRYPOINT ["python", "-u", "generateur.py"]
CMD ["direct"]
