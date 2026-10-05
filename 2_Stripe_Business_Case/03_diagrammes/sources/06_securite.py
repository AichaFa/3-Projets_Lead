"""
Diagramme 6 - Sécurité et conformité - Stripe Business Case
Gauche : matrice des comptes et de leurs droits sur les trois bases (moindre privilège), conforme aux
scripts 04_oltp_postgresql/05 à 07, 05_olap_entrepot/07 et 08, 06_nosql_mongodb/03_utilisateurs.js.
Droite : couches de protection superposées (défense en profondeur).
"""

import os
from xml.sax.saxutils import escape

from schema_outils import COUCHES, GRIS, POLICE, Schema

s = Schema(2260, 1000, "Sécurité et conformité",
           "Qui accède à quoi (moindre privilège), et comment les données sont protégées (défense en profondeur)")


def texte(x, y, contenu, taille=12.5, couleur="#262626", gras=False, ancre="start", italique=False):
    s.elements.append(s._texte(x, y, contenu, taille, couleur, gras=gras, ancre=ancre, italique=italique))


# Matrice des droits
s.section(50, 125, "Qui accède à quoi : un compte par programme, un rôle par usage")
X0, Y0, LC, LB, H_ENTETE, H = 50, 150, 300, 375, 58, 74
colonnes = [("oltp", "Base transactionnelle (OLTP)"), ("olap", "Entrepôt analytique (OLAP)"), ("nosql", "Base NoSQL (MongoDB)")]
s.elements.append(f'<rect x="{X0}" y="{Y0}" width="{LC}" height="{H_ENTETE}" fill="{COUCHES["gouvernance"][0]}"/>')
texte(X0 + 14, Y0 + 35, "Compte (programme ou personne)", 14, "white", gras=True)
for i, (couche, titre) in enumerate(colonnes):
    x = X0 + LC + i * LB
    s.elements.append(f'<rect x="{x}" y="{Y0}" width="{LB}" height="{H_ENTETE}" fill="{COUCHES[couche][0]}"/>')
    texte(x + LB / 2, Y0 + 35, titre, 14, "white", gras=True, ancre="middle")

AUCUN = None
lignes = [
    ("svc_generateur", "application de paiement",
     ("role_application_paiements", "crée paiements, clients, remboursements", "et litiges ; ni modification ni suppression"),
     AUCUN,
     ("role_generateur_nosql", "insère navigation, avis, journaux, documents ;", "aucun accès aux paiements ni aux profils")),
    ("svc_flux", "consommateur, entraînement",
     ("role_flux_temps_reel", "lit les paiements (sans adresse IP) et le pays", "des clients, jamais l'e-mail ; écrit le seul score"),
     AUCUN,
     ("role_flux_nosql", "lit et écrit fiches, profils et modèles ;", "aucune suppression")),
    ("svc_airflow, svc_airflow_dwh", "orchestrateur",
     ("role_orchestrateur", "lecture seule (e-mail chiffré, sans la clé)", "et statistiques de réplication"),
     ("role_chargement", "écrit faits, dimensions et agrégats ;", "vues rafraîchies par fonction dédiée"),
     ("role_orchestrateur_nosql", "lit journaux et index pour les contrôles ;", "consigne leur résultat")),
    ("cdc_debezium", "capture des changements",
     ("réplication et lecture", "de la seule table des paiements ;", "adresse IP exclue du flux"),
     AUCUN, AUCUN),
    ("replicator", "réplica",
     ("réplication physique", "uniquement, connexion chiffrée", ""),
     AUCUN, AUCUN),
    ("svc_grafana, svc_grafana_dwh", "supervision",
     ("role_supervision", "statistiques internes ; date, statut", "et score des paiements seulement"),
     ("role_supervision", "suivi des chargements et dates", "de chargement seulement"),
     AUCUN),
    ("analyste_demo", "analyste",
     AUCUN,
     ("role_analyste", "faits, dimensions, agrégats et vues ;", "pas de journal d'audit"),
     AUCUN),
    ("auditeur_demo", "auditeur",
     AUCUN,
     ("role_auditeur", "journal d'audit et suivi des chargements ;", "pas de paiements ni de clients"),
     AUCUN),
]
for r, (compte, usage, *cellules) in enumerate(lignes):
    y = Y0 + H_ENTETE + r * H
    fond_compte = "#F2F2F2" if r % 2 == 0 else "white"
    s.elements.append(f'<rect x="{X0}" y="{y}" width="{LC}" height="{H}" fill="{fond_compte}" stroke="#BFBFBF" stroke-width="1"/>')
    texte(X0 + 14, y + 30, compte, 13.5, COUCHES["gouvernance"][0], gras=True)
    texte(X0 + 14, y + 52, usage, 12.5, GRIS, italique=True)
    for i, cellule in enumerate(cellules):
        x = X0 + LC + i * LB
        couche = colonnes[i][0]
        if cellule is None:
            s.elements.append(f'<rect x="{x}" y="{y}" width="{LB}" height="{H}" fill="white" stroke="#BFBFBF" stroke-width="1"/>')
            texte(x + LB / 2, y + H / 2 + 5, "aucun accès", 12.5, "#7F7F7F", ancre="middle", italique=True)
        else:
            s.elements.append(f'<rect x="{x}" y="{y}" width="{LB}" height="{H}" fill="{COUCHES[couche][1]}" stroke="#BFBFBF" stroke-width="1"/>')
            role, detail1, detail2 = cellule
            texte(x + 12, y + 22, role, 13, COUCHES[couche][0], gras=True)
            texte(x + 12, y + 42, detail1, 12)
            if detail2:
                texte(x + 12, y + 60, detail2, 12)
y_fin = Y0 + H_ENTETE + len(lignes) * H
texte(X0, y_fin + 26, "Comptes administrateurs réservés à la création des bases et des rôles, jamais utilisés par les programmes. "
      "Comptes svc_ et de supervision : mots de passe aléatoires de 48 caractères.", 12.5, GRIS, italique=True)

# Couches de protection
s.section(1495, 125, "Comment les données sont protégées")
couches = [
    ("Réseau et transport", "oltp", ["Chiffrement TLS 1.3 obligatoire vers la base transactionnelle,",
                                     "serveur vérifié (verify-full) ; connexions en clair refusées"]),
    ("Authentification", "gouvernance", ["Comptes dédiés, mots de passe vérifiés par SCRAM-SHA-256 ;",
                                          "secrets hors du code et du dépôt (fichier .env exclu de Git)"]),
    ("Autorisation", "gouvernance", ["Contrôle d'accès par rôles : droits par table, par colonne et par",
                                      "collection ; aucun compte de service ne peut supprimer dans la caisse ni MongoDB"]),
    ("Données", "nosql", ["E-mails chiffrés (pgcrypto), cartes remplacées par un jeton,",
                          "minimisation dans l'entrepôt, adresse IP hors du flux"]),
    ("Traçabilité", "olap", ["Journal d'audit non modifiable (déclencheurs),",
                             "copié dans l'entrepôt, lisible par le seul auditeur"]),
    ("Contrôle continu", "ia", ["13 contrôles quotidiens (rapport daté), 5 règles d'alerte,",
                                "45 tests automatisés des droits et du chiffrement"]),
]
XC, LC2, HC = 1495, 715, 98
for i, (titre, couche, detail) in enumerate(couches):
    y = 150 + i * (HC + 14)
    retrait = i * 14
    foncee, fond, _ = COUCHES[couche]
    s.elements.append(f'<rect x="{XC + retrait}" y="{y}" width="{LC2 - 2 * retrait}" height="{HC}" rx="10" fill="{fond}" '
                      f'stroke="{foncee}" stroke-width="1.8"/>')
    s.elements.append(f'<rect x="{XC + retrait}" y="{y}" width="12" height="{HC}" rx="4" fill="{foncee}"/>')
    texte(XC + retrait + 26, y + 30, f"{i + 1}. {titre}", 15.5, foncee, gras=True)
    texte(XC + retrait + 26, y + 56, detail[0], 12.5)
    texte(XC + retrait + 26, y + 76, detail[1], 12.5)
y_fleche = 150 + len(couches) * (HC + 14) + 4
texte(XC + LC2 / 2, y_fleche + 18, "de la couche la plus extérieure (le réseau) à la plus intérieure (le contrôle continu)",
      12.5, GRIS, ancre="middle", italique=True)

# Références réglementaires
s.note(50, y_fin + 50, 1425, "Références réglementaires couvertes", [
    "RGPD : article 5 (minimisation, limitation de la conservation des journaux à 90 jours), article 25 (protection dès la conception :",
    "  adresse IP exclue du flux), article 32 (sécurité du traitement : chiffrement, contrôle d'accès, traçabilité)",
    "PCI-DSS : exigence 3 (aucun numéro de carte stocké), exigence 4 (chiffrement des transmissions), exigence 7 (restriction des accès),",
    "  exigence 8 (identifiants protégés), exigence 10 (journalisation et surveillance)"], couleur=COUCHES["gouvernance"][0])

s.enregistrer(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "06_securite"))
