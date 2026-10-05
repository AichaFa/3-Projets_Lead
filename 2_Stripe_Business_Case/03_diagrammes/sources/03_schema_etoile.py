"""
Diagramme 3 - Schéma en étoile de l'entrepôt analytique (OLAP) - Stripe Business Case
Conforme aux scripts 05_olap_entrepot/01_schema_etoile.sql à 04_vues_materialisees.sql.
Table de faits au centre, sept dimensions autour ; tables complémentaires et optimisations à droite.
"""

import os

from schema_outils import COUCHES, Schema

VERT, VERT_FONCE_FOND = COUCHES["olap"][0], "#C6E0B4"

s = Schema(2180, 1110, "Schéma en étoile de l'entrepôt analytique",
           "Une table de faits (un paiement par ligne) entourée de sept dimensions - PK : clé primaire, FK : clé étrangère, "
           "UQ : clé naturelle de la base transactionnelle, M : mesure")

faits = s.table(650, 420, 400, "fait_transactions", "Table de faits - grain : un paiement", [
    ("PK", "transaction_id", "UUID"), ("PK FK", "date_cle", "INT"), ("FK", "client_cle", "INT"), ("FK", "marchand_cle", "INT"),
    ("FK", "produit_cle", "INT"), ("FK", "geographie_ip_cle", "INT"), ("FK", "devise_cle", "INT"), ("FK", "moyen_paiement_cle", "INT"),
    ("", "heure", "SMALLINT"), ("", "statut", "TEXT"), ("", "type_appareil", "TEXT"), ("", "est_abonnement", "BOOLEAN"),
    ("M", "montant_origine", "NUMERIC(12,2)"), ("M", "montant_eur", "NUMERIC(14,2)"), ("M", "montant_rembourse_eur", "NUMERIC(14,2)"),
    ("", "a_litige", "BOOLEAN"), ("", "motif_litige", "TEXT"), ("M", "score_anomalie", "NUMERIC(5,4)"), ("", "date_chargement", "TIMESTAMPTZ"),
], fond=VERT_FONCE_FOND)

dates = s.table(700, 110, 300, "dim_date", "Dimension", [
    ("PK", "date_cle", "INT (AAAAMMJJ)"), ("UQ", "date_complete", "DATE"), ("", "annee", "SMALLINT"), ("", "trimestre", "SMALLINT"),
    ("", "mois, nom_mois", "SMALLINT, TEXT"), ("", "semaine_iso", "SMALLINT"), ("", "jour_mois", "SMALLINT"),
    ("", "jour_semaine, nom_jour", "SMALLINT, TEXT"),
    ("", "est_weekend", "BOOLEAN")])
clients = s.table(100, 150, 310, "dim_client", "Dimension", [
    ("PK", "client_cle", "INT"), ("UQ", "client_id", "UUID"), ("", "code_pays, nom_pays", "CHAR(2), TEXT"), ("", "region", "TEXT"),
    ("", "date_inscription", "DATE")])
moyens = s.table(100, 560, 310, "dim_moyen_paiement", "Dimension", [
    ("PK", "moyen_paiement_cle", "INT"), ("UQ", "type", "TEXT"), ("UQ", "marque", "TEXT")])
marchands = s.table(1190, 150, 320, "dim_marchand", "Dimension", [
    ("PK", "marchand_cle", "INT"), ("UQ", "marchand_id", "UUID"), ("", "raison_sociale", "TEXT"), ("", "categorie", "TEXT"),
    ("", "code_pays, nom_pays", "CHAR(2), TEXT"), ("", "region", "TEXT")])
produits = s.table(1190, 470, 320, "dim_produit", "Dimension", [
    ("PK", "produit_cle", "INT (0 : sans produit)"), ("UQ", "produit_id", "UUID"), ("", "nom", "TEXT"), ("", "prix_catalogue", "NUMERIC(12,2)"),
    ("", "code_devise", "CHAR(3)"), ("", "raison_sociale_marchand", "TEXT")])
geographie = s.table(1190, 790, 320, "dim_geographie", "Dimension", [
    ("PK", "geographie_cle", "INT (0 : inconnu)"), ("UQ", "code_pays", "CHAR(2)"), ("", "nom_pays", "TEXT"), ("", "region", "TEXT")])
devises = s.table(700, 960, 300, "dim_devise", "Dimension", [
    ("PK", "devise_cle", "INT"), ("UQ", "code_devise", "CHAR(3)"), ("", "nom", "TEXT")])

def ligne(table, colonne):
    return table["lignes"][colonne]

c = VERT
s.relation([(faits["cx"], faits["haut"]), (dates["cx"], dates["bas"])], c)
s.relation([(faits["gauche"], ligne(faits, "client_cle")), (540, ligne(faits, "client_cle")), (540, ligne(clients, "client_cle")),
            (clients["droite"], ligne(clients, "client_cle"))], c)
s.relation([(faits["gauche"], ligne(faits, "moyen_paiement_cle")), (585, ligne(faits, "moyen_paiement_cle")),
            (585, ligne(moyens, "moyen_paiement_cle")), (moyens["droite"], ligne(moyens, "moyen_paiement_cle"))], c)
s.relation([(faits["droite"], ligne(faits, "marchand_cle")), (1110, ligne(faits, "marchand_cle")), (1110, ligne(marchands, "marchand_cle")),
            (marchands["gauche"], ligne(marchands, "marchand_cle"))], c)
s.relation([(faits["droite"], ligne(faits, "produit_cle")), (1150, ligne(faits, "produit_cle")), (1150, ligne(produits, "produit_cle")),
            (produits["gauche"], ligne(produits, "produit_cle"))], c)
s.relation([(faits["droite"], ligne(faits, "geographie_ip_cle")), (1080, ligne(faits, "geographie_ip_cle")),
            (1080, ligne(geographie, "geographie_cle")), (geographie["gauche"], ligne(geographie, "geographie_cle"))], c)
s.relation([(faits["cx"], faits["bas"]), (devises["cx"], devises["haut"])], c)

# Tables complémentaires
audit = s.table(1600, 150, 520, "fait_audit", "Seconde table de faits - audit", [
    ("PK", "audit_id", "BIGINT"), ("FK", "date_cle", "INT -> dim_date"), ("", "heure", "SMALLINT"), ("", "table_cible", "TEXT"),
    ("", "operation", "TEXT"), ("", "utilisateur_bd", "TEXT"), ("", "date_chargement", "TIMESTAMPTZ")], couche="gouvernance")
agregats = s.table(1600, 400, 520, "agg_ca_quotidien_marchand", "Table d'agrégats (pré-calcul)", [
    ("PK FK", "date_cle", "INT -> dim_date"), ("PK FK", "marchand_cle", "INT -> dim_marchand"), ("M", "nb_transactions", "INT"),
    ("M", "nb_reussies", "INT"), ("M", "montant_brut_eur", "NUMERIC(16,2)"), ("M", "montant_rembourse_eur", "NUMERIC(16,2)"),
    ("M", "montant_net_eur", "NUMERIC(16,2)"), ("", "date_calcul", "TIMESTAMPTZ")])
s.note(1600, 660, 520, "Vues matérialisées (rafraîchies sans blocage des lectures)", [
    "mv_fraude_quotidienne_pays : paiements, suspects et litiges",
    "  pour fraude, par jour et par pays de l'adresse IP",
    "mv_performance_produits_mensuelle : ventes, abonnements,",
    "  chiffre d'affaires et remboursements, par mois et produit",
    "mv_segmentation_rfm : récence, fréquence, montant et segment",
    "  (Champions, Fidèles, Nouveaux, À risque, Inactifs...)"], couleur=VERT)
s.note(1600, 860, 520, "Optimisations de l'entrepôt", [
    "Faits partitionnés par mois (2025 à 2027, partition par défaut) :",
    "  une requête sur un mois ne lit que sa partition",
    "Chargement incrémental toutes les 15 minutes (filigrane),",
    "  écriture idempotente sans doublon",
    "Montants convertis en euros au dernier taux connu à la date",
    "  du paiement"], couleur=VERT)

s.note(100, 760, 400, "Minimisation des données (RGPD)", [
    "Aucune donnée personnelle directe dans l'entrepôt :",
    "  ni e-mail, ni numéro ou jeton de carte, ni adresse IP",
    "Clients et marchands décrits par leur pays et leur",
    "  région ; clé naturelle conservée pour le rapprochement",
    "Consultation humaine réservée aux comptes analyste et auditeur"], couleur=VERT)

s.enregistrer(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "03_schema_etoile"))
