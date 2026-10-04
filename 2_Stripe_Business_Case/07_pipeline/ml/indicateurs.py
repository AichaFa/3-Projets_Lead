"""
Calcul des indices (variables explicatives) du modèle de détection de fraude.

Rôle du module
--------------
Le modèle ne reçoit pas les paiements bruts mais des indices qui comparent chaque paiement aux
habitudes du client : un montant de 500 euros est banal pour un client qui dépense 450 euros en
moyenne, suspect pour un client qui dépense 20 euros.

Module commun à l'entraînement (entrainement.py) et au consommateur temps réel (consommateur.py).
Un calcul strictement identique dans les deux contextes évite le décalage entre entraînement et
production (training-serving skew) : un modèle qui recevrait en production des valeurs calculées
autrement qu'à l'entraînement produirait des scores non fiables.

Principe de chronologie
-----------------------
Les indices d'un paiement sont calculés à partir du profil du client tel qu'il était AVANT ce
paiement ; le profil n'est mis à jour qu'ensuite. Calculer les indices avec un profil qui contient
déjà le paiement reviendrait à utiliser une information du futur (fuite de données).

Structure d'un profil client (stocké dans la collection MongoDB profils_clients)
--------------------------------------------------------------------------------
- _id                 : identifiant du client dans la base OLTP
- code_pays           : pays de résidence déclaré
- date_inscription    : date de création du compte
- nb_paiements        : nombre de paiements non échoués déjà effectués
- montant_total_eur   : cumul de ces paiements, converti en euros
- montant_moyen_eur   : montant moyen, conservé pour la lisibilité du profil
- pays_connus         : pays d'adresse IP déjà utilisés avec succès
- appareils_connus    : types d'appareils déjà utilisés
- marchands_connus    : marchands chez lesquels le client a déjà payé
- horodatages_recents : dates des tentatives des dernières 24 heures (mesure de la vitesse)
- dernier_paiement    : date de la dernière tentative
"""

import math
from datetime import timedelta

# Ordre des indices : le modèle reçoit un vecteur de nombres sans nom de colonne, l'ordre de
# cette liste doit donc rester identique entre l'entraînement et la production.
# Elle est aussi enregistrée dans la fiche du modèle (collection modeles_ml) pour la traçabilité.
NOMS_INDICES = [
    "montant_eur_log",              # montant en euros, échelle logarithmique
    "ecart_au_montant_moyen",       # rapport entre le montant et la moyenne habituelle du client
    "pays_ip_inhabituel",           # 1 si le pays de l'adresse IP n'a jamais été utilisé par le client
    "appareil_inhabituel",          # 1 si le type d'appareil n'a jamais été utilisé par le client
    "marchand_nouveau",             # 1 si premier achat chez ce marchand
    "nb_paiements_derniere_heure",  # nombre de tentatives dans l'heure précédente (rafales)
    "heure",                        # heure du paiement (0 à 23, temps universel)
    "est_nuit",                     # 1 si le paiement a lieu entre 0 h et 6 h
    "anciennete_jours",             # ancienneté du compte client en jours
    "nb_paiements_anterieurs",      # volume d'historique disponible pour ce client
]

# Fenêtre d'observation de la vitesse des paiements : plusieurs tentatives en moins d'une heure
# caractérisent les rafales typiques d'une carte volée testée puis utilisée.
FENETRE_VITESSE = timedelta(hours=1)

# Nombre minimal de paiements avant de juger un appareil ou un marchand « inhabituel » : sans
# historique suffisant, tout serait nouveau et l'indice n'apporterait aucune information.
NB_MIN_HABITUDES = 3

# Plafond de la liste des horodatages : borne la taille du document MongoDB (limite de 16 Mo par
# document, et lecture plus rapide d'un document court).
NB_MAX_HORODATAGES = 50


def profil_vide(client_id, code_pays, date_inscription):
    """Profil initial d'un client sans aucun paiement."""
    return {
        "_id": str(client_id),
        "code_pays": code_pays,
        "date_inscription": date_inscription,
        "nb_paiements": 0,
        "montant_total_eur": 0.0,
        "montant_moyen_eur": 0.0,
        "pays_connus": [],
        "appareils_connus": [],
        "marchands_connus": [],
        "horodatages_recents": [],
        "dernier_paiement": None,
    }


def calculer_indices(profil, paiement):
    """Retourne le dictionnaire des indices d'un paiement, au regard des habitudes du client.

    Le paiement est un dictionnaire contenant au minimum : montant_eur, date_heure (avec fuseau
    horaire), pays_ip (éventuellement absent), type_appareil et marchand_id.
    """
    nb = profil["nb_paiements"]
    montant = float(paiement["montant_eur"])
    # Moyenne calculée à partir du cumul plutôt que lue dans montant_moyen_eur (valeur arrondie)
    moyenne = profil["montant_total_eur"] / nb if nb else None
    instant = paiement["date_heure"]

    # Le pays de résidence est considéré comme habituel même sans paiement antérieur
    pays_habituels = set(profil["pays_connus"]) | {profil["code_pays"]}
    pays_ip = paiement.get("pays_ip")

    # Tentatives antérieures situées dans l'heure précédant ce paiement ; la borne inférieure à
    # zéro écarte toute date postérieure (protection contre une horloge décalée)
    recents = [h for h in profil["horodatages_recents"] if timedelta(0) <= instant - h <= FENETRE_VITESSE]

    return {
        # Échelle logarithmique : réduit l'écart entre petits et très gros montants, que le modèle
        # traite ainsi de façon plus stable
        "montant_eur_log": math.log1p(montant),
        # Sans historique, valeur neutre de 1 (montant égal à la moyenne)
        "ecart_au_montant_moyen": montant / moyenne if moyenne else 1.0,
        # Paiement sans adresse IP (prélèvement d'abonnement initié par le marchand) : non suspect
        "pays_ip_inhabituel": int(pays_ip is not None and pays_ip not in pays_habituels),
        "appareil_inhabituel": int(nb >= NB_MIN_HABITUDES and paiement["type_appareil"] not in profil["appareils_connus"]),
        # Identifiants comparés sous forme de texte : identiques qu'ils proviennent de PostgreSQL
        # (type UUID), de Kafka (texte JSON) ou de MongoDB (texte)
        "marchand_nouveau": int(nb >= NB_MIN_HABITUDES and str(paiement["marchand_id"]) not in profil["marchands_connus"]),
        "nb_paiements_derniere_heure": len(recents),
        "heure": instant.hour,
        "est_nuit": int(instant.hour < 6),
        "anciennete_jours": max(0, (instant - profil["date_inscription"]).days),
        "nb_paiements_anterieurs": nb,
    }


def vecteur(indices):
    """Convertit le dictionnaire des indices en liste de nombres, dans l'ordre de NOMS_INDICES."""
    return [float(indices[nom]) for nom in NOMS_INDICES]


def mettre_a_jour_profil(profil, paiement):
    """Intègre un paiement au profil du client.

    Toute tentative, même échouée, compte pour la vitesse : une rafale de refus est un signal de
    fraude. En revanche, seuls les paiements non échoués enrichissent les habitudes (montants,
    pays, appareils, marchands) : un fraudeur qui échoue ne doit pas rendre « habituel » son pays.
    """
    instant = paiement["date_heure"]

    # Conservation des seules tentatives des dernières 24 heures, dans la limite du plafond
    horodatages = [h for h in profil["horodatages_recents"] if instant - h <= timedelta(hours=24)]
    horodatages.append(instant)
    profil["horodatages_recents"] = horodatages[-NB_MAX_HORODATAGES:]

    if paiement["statut"] != "echouee":
        profil["nb_paiements"] += 1
        profil["montant_total_eur"] = round(profil["montant_total_eur"] + float(paiement["montant_eur"]), 2)
        profil["montant_moyen_eur"] = round(profil["montant_total_eur"] / profil["nb_paiements"], 2)
        if paiement.get("pays_ip") and paiement["pays_ip"] not in profil["pays_connus"]:
            profil["pays_connus"].append(paiement["pays_ip"])
        if paiement["type_appareil"] not in profil["appareils_connus"]:
            profil["appareils_connus"].append(paiement["type_appareil"])
        marchand = str(paiement["marchand_id"])
        if marchand not in profil["marchands_connus"]:
            profil["marchands_connus"].append(marchand)
    profil["dernier_paiement"] = instant
    return profil


def decision(score, seuil_verification, seuil_blocage):
    """Traduit un score (probabilité de fraude entre 0 et 1) en décision opérationnelle.

    - bloquer  : score supérieur ou égal au seuil de blocage, paiement refusé ;
    - verifier : score intermédiaire, paiement soumis à une vérification complémentaire
                 (authentification forte du porteur, revue manuelle) ;
    - accepter : score faible, paiement autorisé sans friction.
    Les seuils sont lus dans la fiche du modèle actif, ce qui permet de les ajuster sans
    modifier le code.
    """
    if score >= seuil_blocage:
        return "bloquer"
    if score >= seuil_verification:
        return "verifier"
    return "accepter"
