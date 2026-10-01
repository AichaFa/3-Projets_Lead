#!/bin/bash
# Création des rôles et des bases, un compte par service.
# Exécuté une seule fois, à l'initialisation du volume PostgreSQL.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE airflow LOGIN PASSWORD '${AIRFLOW_DB_PASSWORD}';
    CREATE DATABASE airflow OWNER airflow;
    REVOKE CONNECT ON DATABASE airflow FROM PUBLIC;

    CREATE ROLE mlflow LOGIN PASSWORD '${MLFLOW_DB_PASSWORD}';
    CREATE DATABASE mlflow OWNER mlflow;
    REVOKE CONNECT ON DATABASE mlflow FROM PUBLIC;

    CREATE ROLE fraud LOGIN PASSWORD '${FRAUD_DB_PASSWORD}';
    CREATE DATABASE fraud OWNER fraud;
    REVOKE CONNECT ON DATABASE fraud FROM PUBLIC;
EOSQL