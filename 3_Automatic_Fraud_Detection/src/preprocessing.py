"""Préparation des données de paiement pour la détection de fraude.

Ce module est partagé entre l'entraînement (sur fraudTest.csv) et les
prédictions en temps réel (sur les paiements de l'API). Il garantit que
les deux sources produisent exactement les mêmes colonnes, dans le même
ordre, avant d'être présentées au modèle.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Colonnes personnelles ou redondantes, retirées avant toute analyse.
COLONNES_A_SUPPRIMER = [
    "Unnamed: 0",
    "cc_num",
    "first",
    "last",
    "street",
    "job",
    "trans_num",
    "unix_time",
    "city",
    "state",
    "zip",
    "merchant",
    "lat",
    "long",
    "merch_lat",
    "merch_long",
    "dob",
    "trans_date_trans_time",
    "current_time",
]

# Colonnes finales attendues par le modèle, dans cet ordre.
COLONNES_NUMERIQUES = ["amt", "city_pop", "distance_km", "age", "heure", "jour_semaine"]
COLONNES_CATEGORIELLES = ["category", "gender"]
CIBLE = "is_fraud"


def _distance_km(lat1, lon1, lat2, lon2):
    """Distance à vol d'oiseau entre deux points, en kilomètres (formule de Haversine)."""
    rayon_terre = 6371.0
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    d_lat = lat2 - lat1
    d_lon = lon2 - lon1
    a = np.sin(d_lat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(d_lon / 2) ** 2
    return rayon_terre * 2 * np.arcsin(np.sqrt(a))


def _horodatage(df):
    """Retrouve la date et l'heure du paiement selon la source (CSV ou API)."""
    if "trans_date_trans_time" in df.columns:
        return pd.to_datetime(df["trans_date_trans_time"], errors="coerce")
    if "current_time" in df.columns:
        return pd.to_datetime(df["current_time"], unit="ms", errors="coerce")
    return pd.Series(pd.NaT, index=df.index)


def preparer(df: pd.DataFrame) -> pd.DataFrame:
    """Transforme des paiements bruts en colonnes prêtes pour le modèle.

    Accepte le format du CSV comme celui de l'API temps réel.
    Retourne un tableau ne contenant que les colonnes utiles, plus la
    cible is_fraud si elle est présente dans l'entrée.
    """
    df = df.copy()

    horodatage = _horodatage(df)
    df["heure"] = horodatage.dt.hour
    df["jour_semaine"] = horodatage.dt.dayofweek

    naissance = pd.to_datetime(df.get("dob"), errors="coerce")
    df["age"] = (horodatage - naissance).dt.days / 365.25

    df["distance_km"] = _distance_km(
        df["lat"], df["long"], df["merch_lat"], df["merch_long"]
    )

    colonnes_gardees = COLONNES_NUMERIQUES + COLONNES_CATEGORIELLES
    if CIBLE in df.columns:
        colonnes_gardees = colonnes_gardees + [CIBLE]

    return df[colonnes_gardees]
