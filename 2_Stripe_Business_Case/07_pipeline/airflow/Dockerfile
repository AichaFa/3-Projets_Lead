# Image Airflow du projet - Stripe Business Case
# Base officielle Airflow 3.3.1, complétée des pilotes PostgreSQL (psycopg 3) et MongoDB (pymongo).
# Versions alignées sur les contraintes officielles d'Airflow 3.3.1 pour Python 3.13, version de
# l'image de base (fichier constraints-3.13.txt) ;
# la réinstallation explicite d'apache-airflow à la même version empêche toute mise à jour involontaire.
FROM apache/airflow:3.3.1

RUN pip install --no-cache-dir "apache-airflow==3.3.1" "psycopg[binary]==3.3.4" "pymongo==4.17.0"
