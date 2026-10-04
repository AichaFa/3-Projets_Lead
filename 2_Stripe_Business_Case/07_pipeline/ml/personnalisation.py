"""
Personnalisation : recommandations de produits par filtrage collaboratif produit à produit.

Principe
--------
Deux produits sont considérés comme proches lorsqu'ils sont achetés par les mêmes clients
(« les clients qui ont acheté ce produit ont aussi acheté celui-là »). La proximité est mesurée
par la similarité cosinus entre les colonnes de la matrice clients x produits (1 si le client a
acheté le produit, 0 sinon) :

    similarité(A, B) = nombre de clients ayant acheté A et B
                       / racine(nombre d'acheteurs de A x nombre d'acheteurs de B)

Valeur entre 0 (aucun acheteur commun) et 1 (exactement les mêmes acheteurs).

Le modèle entraîné est un dictionnaire : pour chaque produit, ses voisins les plus proches et leur
similarité, complété par la liste des produits les plus populaires. Cette liste sert de solution de
repli pour un client sans historique (problème du « démarrage à froid »).

Module commun à l'entraînement (entrainement_recommandations.py) et au consommateur temps réel
(consommateur.py) : calcul des recommandations identique dans les deux contextes.
"""

import numpy as np

NB_RECOMMANDATIONS = 5          # recommandations conservées dans le profil du client
NB_VOISINS = 10                 # voisins conservés par produit dans le modèle
SEUIL_SIMILARITE = 0.05         # similarité minimale pour retenir un voisin (élimine les rapprochements fortuits)
NB_MAX_PRODUITS_HISTORIQUE = 50 # borne de la liste des produits achetés stockée dans le profil
NB_POPULAIRES = 50              # taille de la liste de repli


def entrainer_similarites(achats):
    """Construit le modèle de recommandation à partir de couples (client, produit).

    Les identifiants sont manipulés sous forme de texte, comme dans les profils MongoDB.
    """
    couples = {(str(c), str(p)) for c, p in achats}
    clients = sorted({c for c, _ in couples})
    produits = sorted({p for _, p in couples})
    rang_client = {c: i for i, c in enumerate(clients)}
    rang_produit = {p: i for i, p in enumerate(produits)}

    # Matrice binaire clients x produits
    matrice = np.zeros((len(clients), len(produits)), dtype=np.float32)
    for c, p in couples:
        matrice[rang_client[c], rang_produit[p]] = 1.0

    # Cooccurrences : nombre de clients communs à chaque paire de produits ;
    # la diagonale contient le nombre d'acheteurs de chaque produit
    cooccurrences = matrice.T @ matrice
    acheteurs = np.diag(cooccurrences).copy()
    normes = np.sqrt(np.outer(acheteurs, acheteurs))
    similarites = np.divide(cooccurrences, normes, out=np.zeros_like(cooccurrences), where=normes > 0)
    np.fill_diagonal(similarites, 0.0)  # un produit n'est pas son propre voisin

    voisins = {}
    for i, produit in enumerate(produits):
        ordre = np.argsort(-similarites[i])[:NB_VOISINS]
        voisins[produit] = [(produits[j], round(float(similarites[i, j]), 4))
                            for j in ordre if similarites[i, j] >= SEUIL_SIMILARITE]

    popularite = [produits[i] for i in np.argsort(-acheteurs)[:NB_POPULAIRES]]
    return {"voisins": voisins, "popularite": popularite}


def recommander(modele, produits_achetes, n=NB_RECOMMANDATIONS):
    """Retourne les n produits recommandés, jamais déjà achetés par le client.

    Score d'un produit candidat : somme de ses similarités avec les produits déjà achetés.
    Les places restantes sont complétées par les produits les plus populaires (origine « popularite »).
    """
    deja_achetes = set(produits_achetes)
    scores = {}
    for produit in produits_achetes:
        for voisin, similarite in modele["voisins"].get(produit, []):
            if voisin not in deja_achetes:
                scores[voisin] = scores.get(voisin, 0.0) + similarite

    classement = sorted(scores, key=lambda p: -scores[p])[:n]
    recommandations = [{"produit_id": p, "score": round(scores[p], 4), "origine": "similarite"} for p in classement]
    for produit in modele["popularite"]:
        if len(recommandations) >= n:
            break
        if produit not in deja_achetes and produit not in classement:
            recommandations.append({"produit_id": produit, "score": 0.0, "origine": "popularite"})
    return recommandations


def mettre_a_jour_preferences(profil, produit_id, categorie):
    """Ajoute un achat aux préférences du client : produits achetés (sans doublon, du plus ancien
    au plus récent, liste bornée) et nombre d'achats par catégorie de marchand."""
    produits = [p for p in profil.get("produits_achetes", []) if p != str(produit_id)]
    produits.append(str(produit_id))
    profil["produits_achetes"] = produits[-NB_MAX_PRODUITS_HISTORIQUE:]
    categories = profil.get("categories_preferees", {})
    if categorie:
        categories[categorie] = categories.get(categorie, 0) + 1
    profil["categories_preferees"] = categories
    return profil
