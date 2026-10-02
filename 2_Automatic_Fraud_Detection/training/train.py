"""Entraînement du détecteur de fraude et enregistrement dans MLflow.

Lit l'historique des paiements (fraudTest.csv), construit un pipeline
complet (préparation + modèle), l'évalue sur des mesures adaptées aux
fraudes rares, puis l'enregistre dans le registre MLflow sous le nom
fraud-detector.
"""

from __future__ import annotations

import os
import sys

import mlflow
import mlflow.sklearn
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import classification_report, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

sys.path.insert(0, "/opt/airflow/src")
from preprocessing import (  # noqa: E402
    COLONNES_CATEGORIELLES,
    COLONNES_NUMERIQUES,
    CIBLE,
    preparer,
)

CHEMIN_DONNEES = os.environ.get("CHEMIN_DONNEES", "/opt/airflow/data/fraudTest.csv")
URI_MLFLOW = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000")
NOM_EXPERIENCE = "detection-fraude"
NOM_MODELE = "fraud-detector"


def construire_pipeline() -> Pipeline:
    """Assemble la préparation numérique/catégorielle et le modèle en un seul objet."""
    prep_num = Pipeline(
        steps=[
            ("imputation", SimpleImputer(strategy="median")),
            ("mise_echelle", StandardScaler()),
        ]
    )
    prep_cat = Pipeline(
        steps=[
            ("imputation", SimpleImputer(strategy="most_frequent")),
            ("encodage", OneHotEncoder(handle_unknown="ignore")),
        ]
    )
    transformeur = ColumnTransformer(
        transformers=[
            ("num", prep_num, COLONNES_NUMERIQUES),
            ("cat", prep_cat, COLONNES_CATEGORIELLES),
        ]
    )
    modele = RandomForestClassifier(
        n_estimators=100,
        class_weight="balanced",
        n_jobs=-1,
        random_state=42,
    )
    return Pipeline(steps=[("preparation", transformeur), ("modele", modele)])


def main() -> None:
    donnees = preparer(pd.read_csv(CHEMIN_DONNEES))
    X = donnees.drop(columns=[CIBLE])
    y = donnees[CIBLE]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )

    mlflow.set_tracking_uri(URI_MLFLOW)
    mlflow.set_experiment(NOM_EXPERIENCE)

    with mlflow.start_run():
        pipeline = construire_pipeline()
        pipeline.fit(X_train, y_train)

        y_pred = pipeline.predict(X_test)
        precision = precision_score(y_test, y_pred, zero_division=0)
        rappel = recall_score(y_test, y_pred, zero_division=0)
        f1 = f1_score(y_test, y_pred, zero_division=0)

        mlflow.log_param("modele", "RandomForest")
        mlflow.log_param("n_estimators", 100)
        mlflow.log_param("class_weight", "balanced")
        mlflow.log_metric("precision", precision)
        mlflow.log_metric("rappel", rappel)
        mlflow.log_metric("f1", f1)

        mlflow.sklearn.log_model(
            sk_model=pipeline,
            name="pipeline",
            registered_model_name=NOM_MODELE,
        )

        print(classification_report(y_test, y_pred, zero_division=0))
        print(f"Precision : {precision:.3f}  Rappel : {rappel:.3f}  F1 : {f1:.3f}")


if __name__ == "__main__":
    main()
