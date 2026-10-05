"""
Diagramme 2 - Modèle entité-relation de la base transactionnelle (OLTP) - Stripe Business Case
Conforme au script 04_oltp_postgresql/01_schema.sql : 12 tables en troisième forme normale.
Notation « patte de corbeau » : trait simple = un, patte = plusieurs, cercle = facultatif.
Colonnes sensibles signalées : donnée chiffrée, jeton de carte, adresse IP exclue du flux temps réel.
"""

import os
import subprocess

from schema_outils import COUCHES

MARINE, FOND = COUCHES["oltp"][0], COUCHES["oltp"][1]
AUDIT, FOND_AUDIT = COUCHES["gouvernance"][0], COUCHES["gouvernance"][1]
SENSIBLE = "#C55A11"

TABLES = {
    "pays": ("Référentiel", [("PK", "code_pays", "CHAR(2)"), ("", "nom", "TEXT"), ("", "region", "TEXT")]),
    "devises": ("Référentiel", [("PK", "code_devise", "CHAR(3)"), ("", "nom", "TEXT")]),
    "taux_change": ("Référentiel", [("PK FK", "code_devise", "CHAR(3)"), ("PK", "date_taux", "DATE"), ("", "taux_vers_eur", "NUMERIC(18,8)")]),
    "marchands": ("Acteur", [("PK", "marchand_id", "UUID"), ("", "raison_sociale", "TEXT"), ("FK", "code_pays", "CHAR(2)"),
                             ("", "categorie", "TEXT"), ("", "date_creation", "TIMESTAMPTZ")]),
    "clients": ("Acteur", [("PK", "client_id", "UUID"), ("", "email_chiffre", "BYTEA", "chiffré (pgcrypto)"),
                           ("FK", "code_pays", "CHAR(2)"), ("", "date_creation", "TIMESTAMPTZ")]),
    "moyens_paiement": ("Acteur", [("PK", "moyen_paiement_id", "UUID"), ("FK", "client_id", "UUID"), ("", "type", "TEXT"),
                                   ("", "marque", "TEXT"), ("", "quatre_derniers", "CHAR(4)"), ("UQ", "jeton", "TEXT", "jeton, jamais le numéro")]),
    "produits": ("Catalogue", [("PK", "produit_id", "UUID"), ("FK", "marchand_id", "UUID"), ("", "nom", "TEXT"),
                               ("", "prix", "NUMERIC(12,2)"), ("FK", "code_devise", "CHAR(3)")]),
    "abonnements": ("Catalogue", [("PK", "abonnement_id", "UUID"), ("FK", "client_id", "UUID"), ("FK", "produit_id", "UUID"),
                                  ("", "statut", "TEXT"), ("", "date_debut", "DATE"), ("", "date_fin", "DATE")]),
    "transactions": ("Paiement", [("PK", "transaction_id", "UUID"), ("FK", "marchand_id", "UUID"), ("FK", "client_id", "UUID"),
                                  ("FK", "moyen_paiement_id", "UUID"), ("FK", "produit_id", "UUID"), ("FK", "abonnement_id", "UUID"),
                                  ("", "montant", "NUMERIC(12,2)"), ("FK", "code_devise", "CHAR(3)"), ("", "statut", "TEXT"),
                                  ("", "date_heure", "TIMESTAMPTZ"), ("", "adresse_ip", "INET", "exclue du flux"),
                                  ("FK", "pays_ip", "CHAR(2)"), ("", "type_appareil", "TEXT"), ("", "score_anomalie", "NUMERIC(5,4)"),
                                  ("", "date_maj", "TIMESTAMPTZ")]),
    "remboursements": ("Après-vente", [("PK", "remboursement_id", "UUID"), ("FK", "transaction_id", "UUID"), ("", "montant", "NUMERIC(12,2)"),
                                       ("", "motif", "TEXT"), ("", "date_remboursement", "TIMESTAMPTZ")]),
    "litiges": ("Après-vente", [("PK", "litige_id", "UUID"), ("FK UQ", "transaction_id", "UUID"), ("", "motif", "TEXT"),
                                ("", "statut", "TEXT"), ("", "date_ouverture", "TIMESTAMPTZ")]),
    "journal_audit": ("Audit", [("PK", "audit_id", "BIGINT"), ("", "table_cible", "TEXT"), ("", "operation", "TEXT"),
                                ("", "identifiant_ligne", "TEXT"), ("", "utilisateur_bd", "TEXT"), ("", "date_action", "TIMESTAMPTZ"),
                                ("", "anciennes_valeurs", "JSONB"), ("", "nouvelles_valeurs", "JSONB")]),
}

# (table enfant, colonne, table parente, facultatif) : l'enfant porte la clé étrangère (plusieurs vers un)
RELATIONS = [
    ("taux_change", "code_devise", "devises", False),
    ("marchands", "code_pays", "pays", False),
    ("clients", "code_pays", "pays", False),
    ("moyens_paiement", "client_id", "clients", False),
    ("produits", "marchand_id", "marchands", False),
    ("produits", "code_devise", "devises", False),
    ("abonnements", "client_id", "clients", False),
    ("abonnements", "produit_id", "produits", False),
    ("transactions", "marchand_id", "marchands", False),
    ("transactions", "client_id", "clients", False),
    ("transactions", "moyen_paiement_id", "moyens_paiement", False),
    ("transactions", "produit_id", "produits", True),
    ("transactions", "abonnement_id", "abonnements", True),
    ("transactions", "code_devise", "devises", False),
    ("transactions", "pays_ip", "pays", True),
    ("remboursements", "transaction_id", "transactions", False),
    ("litiges", "transaction_id", "transactions", False),
]


def table_html(nom, categorie, colonnes):
    entete, fond = (AUDIT, FOND_AUDIT) if nom == "journal_audit" else (MARINE, FOND)
    lignes = [f'<TR><TD COLSPAN="3" BGCOLOR="{entete}" ALIGN="CENTER"><FONT COLOR="white" POINT-SIZE="10">{categorie.upper()}</FONT><BR/>'
              f'<FONT COLOR="white" POINT-SIZE="15"><B>{nom}</B></FONT></TD></TR>']
    for colonne in colonnes:
        cle, nom_col, type_col = colonne[:3]
        note = colonne[3] if len(colonne) > 3 else None
        cle_txt = f'<FONT COLOR="{entete}"><B>{cle}</B></FONT>' if cle else ""
        nom_txt = f"<B>{nom_col}</B>" if "PK" in cle else nom_col
        if note:
            nom_txt += f'<BR/><FONT COLOR="{SENSIBLE}" POINT-SIZE="10"><I>{note}</I></FONT>'
        # Points d'attache sur le bord gauche (première cellule) et droit (dernière cellule) de la ligne
        lignes.append(f'<TR><TD ALIGN="LEFT" WIDTH="38" PORT="{nom_col}_g">{cle_txt}</TD><TD ALIGN="LEFT">{nom_txt}</TD>'
                      f'<TD ALIGN="LEFT" PORT="{nom_col}_d"><FONT COLOR="#595959">{type_col}</FONT></TD></TR>')
    return (f'<<TABLE BORDER="1" COLOR="{entete}" CELLBORDER="0" CELLSPACING="0" CELLPADDING="5" BGCOLOR="{fond}">'
            + "".join(lignes) + "</TABLE>>")


def generer():
    dot = ['digraph erd {',
           '  graph [rankdir=LR, fontname="Carlito", nodesep=0.5, ranksep=0.9, splines=true, pad=0.5, bgcolor="white", labelloc=t, '
           'label=<<FONT POINT-SIZE="28" COLOR="#1F3864"><B>Modèle entité-relation de la base transactionnelle</B></FONT><BR/>'
           '<FONT POINT-SIZE="15" COLOR="#595959">12 tables en troisième forme normale - PK : clé primaire, FK : clé étrangère, '
           'UQ : valeur unique - patte de corbeau : plusieurs, trait : un, cercle : facultatif</FONT><BR/> >];',
           '  node [shape=plain, fontname="Carlito", fontsize=12];',
           f'  edge [color="{MARINE}", penwidth=1.5, arrowsize=1.1, dir=both, fontname="Carlito"];']
    for nom, (categorie, colonnes) in TABLES.items():
        dot.append(f"  {nom} [label={table_html(nom, categorie, colonnes)}];")
    for enfant, colonne, parent, facultatif in RELATIONS:
        # Litige : contrainte d'unicité sur transaction_id, donc zéro ou un litige par paiement
        queue = "teeodot" if enfant == "litiges" else ("crowodot" if facultatif else "crowtee")
        cle_parent = TABLES[parent][1][0][1]
        dot.append(f'  {enfant}:{colonne}_d:e -> {parent}:{cle_parent}_g:w [arrowtail={queue}, arrowhead=teetee];')
    # Notes : intégrité renforcée et journal d'audit
    notes = [
        ("note_integrite", "Intégrité renforcée", [
            "Clés étrangères composées :",
            "(moyen_paiement_id, client_id) : un paiement n'utilise que",
            "une carte de son propre client ;",
            "(produit_id, marchand_id) : un produit vendu par le marchand payé ;",
            "(abonnement_id, client_id) : un abonnement du client payeur.",
            "Contrainte d'unicité : un seul litige par paiement.",
            "Déclencheurs : remboursement refusé au-delà du montant payé,",
            "statut du paiement mis à jour (remboursé, contesté),",
            "abonnement cohérent avec le produit ;",
            "remboursements non modifiables une fois enregistrés."]),
        ("note_audit", "Journal d'audit", [
            "Alimenté par déclencheurs sur les tables sensibles ;",
            "anciennes et nouvelles valeurs, compte et date de l'action.",
            "Sans clé étrangère : il survit à la suppression des lignes.",
            "Non modifiable : toute mise à jour ou suppression est refusée."]),
    ]
    for nom_note, titre_note, lignes_note in notes:
        contenu = "".join(f'<TR><TD ALIGN="LEFT">{texte}</TD></TR>' for texte in lignes_note)
        dot.append(f'  {nom_note} [label=<<TABLE BORDER="1" COLOR="#7F7F7F" CELLBORDER="0" CELLSPACING="0" CELLPADDING="4" BGCOLOR="#F2F2F2">'
                   f'<TR><TD ALIGN="LEFT"><FONT COLOR="{MARINE}" POINT-SIZE="13"><B>{titre_note}</B></FONT></TD></TR>{contenu}</TABLE>>];')
    # Rangs imposés : tables dépendantes et notes à gauche, référentiels à droite ;
    # ordre vertical de la colonne de gauche fixé par des liens invisibles
    dot.append('  { rank=same; journal_audit; note_audit; remboursements; litiges; note_integrite; }')
    dot.append('  journal_audit -> note_audit -> remboursements -> litiges -> note_integrite [style=invis];')
    dot.append('  { rank=same; moyens_paiement; abonnements; }')
    dot.append('  { rank=same; clients; produits; }')
    dot.append('  { rank=same; marchands; taux_change; }')
    dot.append('  { rank=same; pays; devises; }')
    dot.append("}")
    dossier = os.path.dirname(os.path.abspath(__file__))
    source = os.path.join(dossier, "02_modele_entite_relation.dot")
    with open(source, "w", encoding="utf-8") as fichier:
        fichier.write("\n".join(dot))
    subprocess.run(["dot", "-Tpng", "-Gdpi=170", source, "-o", os.path.join(dossier, "..", "02_modele_entite_relation.png")], check=True)
    subprocess.run(["dot", "-Tsvg", source, "-o", os.path.join(dossier, "..", "02_modele_entite_relation.svg")], check=True)


if __name__ == "__main__":
    generer()
