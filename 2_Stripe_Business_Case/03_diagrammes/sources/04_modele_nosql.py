"""
Diagramme 4 - Modèle de données NoSQL (MongoDB) - Stripe Business Case
Conforme aux scripts 06_nosql_mongodb/01_collections.js et 02_index.js, et aux documents écrits par le
consommateur temps réel et les programmes d'entraînement (champs supplémentaires admis par la validation).
Imbrication ({ } objet, [ ] liste) pour les données lues ensemble ; références par identifiant commun.
"""

import os

from schema_outils import COUCHES, Schema

CANARD = COUCHES["nosql"][0]
s = Schema(2280, 920, "Modèle de données NoSQL (MongoDB 8.0)",
           "Sept collections avec règles de validation, deux espaces de fichiers GridFS - _id : identifiant, REF : référence, "
           "{ } : objet imbriqué, [ ] : liste imbriquée")

X = [50, 520, 990, 1460]
s.table(X[0], 120, 420, "transactions_enrichies", "Paiement noté en temps réel", [
    ("_id", "_id", "id du paiement (caisse)"), ("REF", "client_id", "vers profils_clients"), ("REF", "marchand_id", "vers caisse : marchands"),
    ("", "montant", "décimal (Decimal128)"), ("", "devise, statut", "chaîne, énumération"), ("", "date_heure", "date"),
    ("{ }", "contexte", "objet"), ("", "  montant_eur, pays_ip, type_appareil", ""),
    ("{ }", "indicateurs", "objet : 10 indices"), ("{ }", "score", "objet"), ("", "  valeur, modele, version", ""),
    ("", "  decision", "accepter, verifier, bloquer"), ("[ ]", "historique_statuts", "liste (20 au plus)"),
    ("", "  statut, date", ""), ("", "latence_ms", "entier"), ("", "date_traitement", "date")], couche="nosql")
s.table(X[1], 120, 420, "profils_clients", "Habitudes et personnalisation", [
    ("_id", "_id", "id du client (caisse)"), ("", "code_pays, date_inscription", "chaîne, date"),
    ("", "nb_paiements", "entier"), ("", "montant_total_eur, montant_moyen_eur", "décimal"),
    ("[ ]", "pays_connus", "codes pays"), ("[ ]", "appareils_connus", "types d'appareils"),
    ("[ ]", "marchands_connus", "identifiants"), ("[ ]", "horodatages_recents", "dates (24 heures)"),
    ("[ ]", "produits_achetes", "identifiants"), ("{ }", "categories_preferees", "catégorie : nombre"),
    ("[ ]", "recommandations", "liste (5 produits)"), ("", "  produit_id, score, origine", ""),
    ("{ }", "recommandations_modele", "nom, version"), ("", "date_maj", "date")], couche="nosql")
s.table(X[2], 120, 420, "modeles_ml", "Registre des modèles", [
    ("_id", "_id", "ObjectId"), ("", "nom, version", "unique (index)"), ("", "statut", "candidat, actif, archive"),
    ("", "date_entrainement", "date"), ("", "seuil_verification, seuil_decision", "0,5 et 0,8"), ("{ }", "periode", "début, fin des données"),
    ("{ }", "metriques", "objet"), ("", "  entraînement, production, suivi", "AUC, latence, dérive"),
    ("REF", "fichier_gridfs_id", "vers GridFS « modeles »")], couche="nosql")
s.table(X[3], 120, 380, "journaux_applicatifs", "Journaux techniques", [
    ("_id", "_id", "ObjectId"), ("", "horodatage", "date (expiration 90 j)"), ("", "niveau", "DEBUG à CRITIQUE"),
    ("{ }", "source", "objet"), ("", "  service, hote", "chaîne"), ("", "message", "chaîne"),
    ("", "code_http, duree_ms", "nombres facultatifs")], couche="nosql")

s.table(X[0], 590, 420, "sessions_navigation", "Visites sur les sites marchands", [
    ("_id", "_id", "id de session"), ("REF", "client_id", "facultatif : visiteur anonyme"), ("REF", "marchand_id", "vers caisse : marchands"),
    ("", "debut, fin", "date"), ("{ }", "appareil", "objet : type"), ("[ ]", "evenements", "liste (500 au plus)"),
    ("", "  type, horodatage, page", "page vue, panier, paiement..."), ("REF", "transaction_id", "si la visite aboutit")], couche="nosql")
s.table(X[1], 590, 420, "avis_clients", "Avis et enquêtes (structures variables)", [
    ("_id", "_id", "ObjectId"), ("", "type", "avis ou enquête"), ("REF", "client_id, marchand_id", "vers caisse"),
    ("", "date", "date"), ("", "note", "1 à 5 (si avis)"), ("", "commentaire", "recherche plein texte"),
    ("[ ]", "reponses", "si enquête"), ("", "  question, reponse", "")], couche="nosql")
s.table(X[2], 590, 420, "documents_externes", "Messages bancaires et justificatifs", [
    ("_id", "_id", "ObjectId"), ("", "type", "message ou pièce"), ("", "format", "xml, json, pdf, image"),
    ("", "date_reception", "date"), ("{ }", "references", "objet"), ("REF", "  transaction_id, litige_id", "vers caisse"),
    ("", "contenu_brut", "si XML ou JSON"), ("{ }", "champs_extraits", "motif, montant..."),
    ("REF", "fichier_gridfs_id", "si PDF ou image")], couche="nosql")
s.table(X[3], 590, 380, "GridFS « fichiers » et « modeles »", "Stockage de fichiers binaires", [
    ("", "fichiers.files, fichiers.chunks", "justificatifs PDF, images"), ("", "modeles.files, modeles.chunks", "modèles entraînés"),
    ("", "découpage en blocs de 255 Ko", "sans limite de 16 Mo")], couche="nosql")

s.note(1880, 120, 370, "Imbriquer ou référencer", [
    "Imbriqué : ce qui est lu ensemble,",
    "  en une seule lecture (score, indices,",
    "  événements d'une visite, historique)",
    "Listes bornées (20, 500) : un document",
    "  ne grossit pas sans limite",
    "Référencé : ce qui vit ailleurs ou grossit",
    "  (client, marchand, fichiers binaires)",
    "Identifiants communs avec la caisse :",
    "  écritures idempotentes, liens entre bases"], couleur=CANARD)
s.note(1880, 345, 370, "Validation et index", [
    "7 collections avec règles $jsonSchema :",
    "  champs obligatoires, types, valeurs",
    "  admises ; champs supplémentaires admis",
    "Structures variables : avis ou enquête,",
    "  message texte ou fichier (anyOf)",
    "Index composés client et date, unicité",
    "  nom et version des modèles, recherche",
    "  plein texte en français, expiration à 90 j"], couleur=CANARD)
s.note(1880, 570, 370, "Sécurité", [
    "Un compte par programme, droits définis",
    "  collection par collection",
    "Aucun droit de suppression accordé",
    "Aucune donnée de carte ni adresse IP",
    "Journaux supprimés après 90 jours (RGPD)"], couleur=CANARD)

s.enregistrer(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "04_modele_nosql"))
