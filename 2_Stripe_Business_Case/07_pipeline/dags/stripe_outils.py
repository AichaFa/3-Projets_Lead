"""
Fonctions communes aux chaînes de tâches Airflow - Stripe Business Case

Regroupe la logique métier des traitements (connexions, alimentation de l'entrepôt, contrôles de
qualité et de conformité, appels au service d'entraînement), indépendamment d'Airflow : les
fichiers de chaînes de tâches se limitent à l'ordonnancement, et cette logique reste testable
sans orchestrateur.

Connexions définies par variables d'environnement du conteneur Airflow (aucun identifiant dans le
code) : OLTP_*, DWH_*, MONGO_URL, CONNECT_URL, SERVICE_ML_URL.
"""

import os
from datetime import datetime, timedelta, timezone

import psycopg
import requests
from pymongo import MongoClient

# Recouvrement appliqué au filigrane : relecture des 5 dernières minutes à chaque exécution, pour
# ne pas manquer une ligne validée tardivement par une transaction longue. Sans risque de
# doublon : l'écriture dans l'entrepôt est une insertion ou mise à jour (upsert).
RECOUVREMENT = timedelta(minutes=5)


# Connexions

def connexion_oltp():
    # Chiffrement TLS : précisé pour cette seule connexion (une variable globale PGSSLMODE
    # s'appliquerait aussi à l'entrepôt et à la base interne d'Airflow, non chiffrés)
    return psycopg.connect(host=os.environ["OLTP_HOTE"], dbname=os.environ["OLTP_BASE"],
                           user=os.environ["OLTP_UTILISATEUR"], password=os.environ["OLTP_MOT_DE_PASSE"],
                           sslmode=os.getenv("OLTP_SSLMODE", "prefer"), sslrootcert=os.getenv("OLTP_SSLROOTCERT"))


def connexion_dwh():
    return psycopg.connect(host=os.environ["DWH_HOTE"], dbname=os.environ["DWH_BASE"],
                           user=os.environ["DWH_UTILISATEUR"], password=os.environ["DWH_MOT_DE_PASSE"])


def base_mongo():
    return MongoClient(os.environ["MONGO_URL"], tz_aware=True, serverSelectionTimeoutMS=30000)["stripe_nosql"]


# Alimentation de l'entrepôt

def maintenir_partitions():
    """Crée à l'avance les partitions du mois courant et des deux mois suivants (si absentes)."""
    with connexion_dwh() as dwh, dwh.cursor() as cur:
        cur.execute("""
            SELECT fn_creer_partition_mensuelle((date_trunc('month', current_date) + make_interval(months => n))::date)
            FROM generate_series(0, 2) AS n
        """)
        return [r[0] for r in cur.fetchall()]


def charger_dimensions():
    """Copie complète et idempotente des dimensions (dimension à évolution lente de type 1 :
    une modification dans la base OLTP écrase l'ancienne valeur). Aucune donnée personnelle
    directe n'est copiée (ni e-mail, ni jeton, ni chiffres de carte)."""
    with connexion_oltp() as oltp, oltp.cursor() as source, connexion_dwh() as dwh, dwh.cursor() as cible:
        source.execute("SELECT code_pays, nom, region FROM pays")
        cible.executemany("""
            INSERT INTO dim_geographie (code_pays, nom_pays, region) VALUES (%s, %s, %s)
            ON CONFLICT (code_pays) DO UPDATE SET nom_pays = EXCLUDED.nom_pays, region = EXCLUDED.region
        """, source.fetchall())

        source.execute("SELECT code_devise, nom FROM devises")
        cible.executemany("""
            INSERT INTO dim_devise (code_devise, nom) VALUES (%s, %s)
            ON CONFLICT (code_devise) DO UPDATE SET nom = EXCLUDED.nom
        """, source.fetchall())

        source.execute("""
            SELECT m.marchand_id, m.raison_sociale, m.categorie, m.code_pays, p.nom, p.region
            FROM marchands m JOIN pays p ON p.code_pays = m.code_pays
        """)
        cible.executemany("""
            INSERT INTO dim_marchand (marchand_id, raison_sociale, categorie, code_pays, nom_pays, region)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (marchand_id) DO UPDATE SET raison_sociale = EXCLUDED.raison_sociale,
                categorie = EXCLUDED.categorie, code_pays = EXCLUDED.code_pays,
                nom_pays = EXCLUDED.nom_pays, region = EXCLUDED.region
        """, source.fetchall())

        source.execute("""
            SELECT c.client_id, c.code_pays, p.nom, p.region, c.date_creation::date
            FROM clients c JOIN pays p ON p.code_pays = c.code_pays
        """)
        cible.executemany("""
            INSERT INTO dim_client (client_id, code_pays, nom_pays, region, date_inscription)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (client_id) DO UPDATE SET code_pays = EXCLUDED.code_pays,
                nom_pays = EXCLUDED.nom_pays, region = EXCLUDED.region
        """, source.fetchall())

        source.execute("""
            SELECT pr.produit_id, pr.nom, pr.prix, pr.code_devise, m.raison_sociale
            FROM produits pr JOIN marchands m ON m.marchand_id = pr.marchand_id
        """)
        cible.executemany("""
            INSERT INTO dim_produit (produit_id, nom, prix_catalogue, code_devise, raison_sociale_marchand)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (produit_id) DO UPDATE SET nom = EXCLUDED.nom, prix_catalogue = EXCLUDED.prix_catalogue,
                code_devise = EXCLUDED.code_devise, raison_sociale_marchand = EXCLUDED.raison_sociale_marchand
        """, source.fetchall())

        source.execute("SELECT DISTINCT type, COALESCE(marque, 'non applicable') FROM moyens_paiement")
        cible.executemany("""
            INSERT INTO dim_moyen_paiement (type, marque) VALUES (%s, %s)
            ON CONFLICT (type, marque) DO NOTHING
        """, source.fetchall())

        cible.execute("SELECT (SELECT count(*) FROM dim_client), (SELECT count(*) FROM dim_marchand), (SELECT count(*) FROM dim_produit)")
        clients, marchands, produits = cible.fetchone()
        return {"dim_client": clients, "dim_marchand": marchands, "dim_produit": produits}


# Paiements à charger : modifiés depuis le filigrane, ou ayant reçu un remboursement depuis
# (un remboursement partiel ne modifie pas la ligne du paiement, seul un remboursement total
# change son statut). Montants convertis au taux du jour du paiement ; à défaut, dernier taux
# antérieur, puis premier taux connu.
SQL_PAIEMENTS_MODIFIES = """
    WITH candidats AS (
        SELECT transaction_id FROM transactions WHERE date_maj > %(depuis)s::timestamptz
        UNION
        SELECT transaction_id FROM remboursements WHERE date_remboursement > %(depuis)s::timestamptz
    )
    SELECT t.transaction_id::text,
           to_char(t.date_heure AT TIME ZONE 'UTC', 'YYYYMMDD')::int AS date_cle,
           t.client_id::text, t.marchand_id::text, t.produit_id::text, t.pays_ip, t.code_devise,
           mp.type, COALESCE(mp.marque, 'non applicable') AS marque,
           extract(hour FROM t.date_heure AT TIME ZONE 'UTC')::int AS heure,
           t.statut, t.type_appareil, t.abonnement_id IS NOT NULL AS est_abonnement,
           t.montant,
           round(t.montant * tx.taux, 2) AS montant_eur,
           round(COALESCE(rb.total, 0) * tx.taux, 2) AS montant_rembourse_eur,
           l.transaction_id IS NOT NULL AS a_litige,
           l.motif AS motif_litige,
           t.score_anomalie,
           t.date_maj
    FROM candidats c
    JOIN transactions t ON t.transaction_id = c.transaction_id
    JOIN moyens_paiement mp ON mp.moyen_paiement_id = t.moyen_paiement_id
    CROSS JOIN LATERAL (
        SELECT COALESCE(
            (SELECT taux_vers_eur FROM taux_change
             WHERE code_devise = t.code_devise AND date_taux <= (t.date_heure AT TIME ZONE 'UTC')::date
             ORDER BY date_taux DESC LIMIT 1),
            (SELECT taux_vers_eur FROM taux_change WHERE code_devise = t.code_devise ORDER BY date_taux LIMIT 1)
        ) AS taux
    ) tx
    LEFT JOIN LATERAL (SELECT sum(montant) AS total FROM remboursements r WHERE r.transaction_id = t.transaction_id) rb ON true
    LEFT JOIN litiges l ON l.transaction_id = t.transaction_id
"""

SQL_UPSERT_FAIT = """
    INSERT INTO fait_transactions (transaction_id, date_cle, client_cle, marchand_cle, produit_cle,
        geographie_ip_cle, devise_cle, moyen_paiement_cle, heure, statut, type_appareil, est_abonnement,
        montant_origine, montant_eur, montant_rembourse_eur, a_litige, motif_litige, score_anomalie)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (transaction_id, date_cle) DO UPDATE SET
        statut = EXCLUDED.statut,
        montant_rembourse_eur = EXCLUDED.montant_rembourse_eur,
        a_litige = EXCLUDED.a_litige,
        motif_litige = EXCLUDED.motif_litige,
        score_anomalie = EXCLUDED.score_anomalie,
        date_chargement = now()
"""


def _correspondances(cible):
    """Tables de correspondance entre identifiants de la base OLTP et clés de substitution de l'entrepôt."""
    resultat = {}
    for nom, requete in {
        "client": "SELECT client_id::text, client_cle FROM dim_client",
        "marchand": "SELECT marchand_id::text, marchand_cle FROM dim_marchand",
        "produit": "SELECT produit_id::text, produit_cle FROM dim_produit WHERE produit_id IS NOT NULL",
        "geographie": "SELECT code_pays, geographie_cle FROM dim_geographie",
        "devise": "SELECT code_devise, devise_cle FROM dim_devise",
        "moyen": "SELECT type || '|' || marque, moyen_paiement_cle FROM dim_moyen_paiement",
    }.items():
        cible.execute(requete)
        resultat[nom] = dict(cible.fetchall())
    return resultat


def charger_faits():
    """Chargement incrémental de la table de faits ; retourne les jours (date_cle) touchés."""
    with connexion_oltp() as oltp, oltp.cursor() as source, connexion_dwh() as dwh, dwh.cursor() as cible:
        cible.execute("SELECT derniere_valeur FROM suivi_chargements WHERE flux = 'transactions'")
        ligne = cible.fetchone()
        filigrane = datetime.fromisoformat(ligne[0]) if ligne else None
        depuis = filigrane - RECOUVREMENT if filigrane else "-infinity"
        source.execute(SQL_PAIEMENTS_MODIFIES, {"depuis": depuis})
        lignes = source.fetchall()
        if not lignes:
            # Aucun paiement modifié : passage enregistré quand même (zéro ligne), pour que la
            # supervision distingue « rien à charger » d'une chaîne de chargement arrêtée
            cible.execute("UPDATE suivi_chargements SET nb_lignes = 0, date_execution = now() WHERE flux = 'transactions'")
            return []

        cles = _correspondances(cible)
        if any(l[2] not in cles["client"] or l[3] not in cles["marchand"] for l in lignes):
            # Nouveaux clients ou marchands apparus depuis le chargement des dimensions
            dwh.commit()
            charger_dimensions()
            cles = _correspondances(cible)

        valeurs, jours, max_maj = [], set(), filigrane
        for (transaction_id, date_cle, client, marchand, produit, pays_ip, devise, type_moyen, marque, heure,
             statut, appareil, est_abonnement, montant, montant_eur, rembourse_eur, a_litige, motif, score, date_maj) in lignes:
            valeurs.append((
                transaction_id, date_cle, cles["client"][client], cles["marchand"][marchand],
                cles["produit"].get(produit, 0) if produit else 0,
                cles["geographie"].get(pays_ip, 0) if pays_ip else 0,
                cles["devise"][devise], cles["moyen"][f"{type_moyen}|{marque}"],
                heure, statut, appareil, est_abonnement, montant, montant_eur, rembourse_eur, a_litige, motif, score,
            ))
            jours.add(date_cle)
            max_maj = date_maj if max_maj is None or date_maj > max_maj else max_maj
        cible.executemany(SQL_UPSERT_FAIT, valeurs)

        cible.execute("""
            INSERT INTO suivi_chargements (flux, derniere_valeur, nb_lignes, date_execution) VALUES ('transactions', %s, %s, now())
            ON CONFLICT (flux) DO UPDATE SET derniere_valeur = EXCLUDED.derniere_valeur,
                nb_lignes = EXCLUDED.nb_lignes, date_execution = now()
        """, (max_maj.isoformat(), len(valeurs)))
        return sorted(jours)


def charger_audit():
    """Copie incrémentale du journal d'audit (qui, quoi, quand, sur quelle table), sans les valeurs."""
    with connexion_oltp() as oltp, oltp.cursor() as source, connexion_dwh() as dwh, dwh.cursor() as cible:
        cible.execute("SELECT COALESCE(max(audit_id), 0) FROM fait_audit")
        dernier = cible.fetchone()[0]
        source.execute("""
            SELECT audit_id, to_char(date_action AT TIME ZONE 'UTC', 'YYYYMMDD')::int,
                   extract(hour FROM date_action AT TIME ZONE 'UTC')::int, table_cible, operation, utilisateur_bd
            FROM journal_audit WHERE audit_id > %s ORDER BY audit_id
        """, (dernier,))
        lignes = source.fetchall()
        cible.executemany("""
            INSERT INTO fait_audit (audit_id, date_cle, heure, table_cible, operation, utilisateur_bd)
            VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (audit_id) DO NOTHING
        """, lignes)
        return len(lignes)


def recalculer_agregats(jours):
    """Recalcul de la table pré-agrégée pour les seuls jours modifiés (suppression puis insertion,
    dans une même transaction : aucun lecteur ne voit un jour à moitié calculé)."""
    if not jours:
        return 0
    with connexion_dwh() as dwh, dwh.cursor() as cur:
        cur.execute("DELETE FROM agg_ca_quotidien_marchand WHERE date_cle = ANY(%s)", (jours,))
        cur.execute("""
            INSERT INTO agg_ca_quotidien_marchand (date_cle, marchand_cle, nb_transactions, nb_reussies,
                montant_brut_eur, montant_rembourse_eur, montant_net_eur)
            SELECT date_cle, marchand_cle,
                   count(*),
                   count(*) FILTER (WHERE statut = 'reussie'),
                   COALESCE(sum(montant_eur) FILTER (WHERE statut <> 'echouee'), 0),
                   COALESCE(sum(montant_rembourse_eur), 0),
                   COALESCE(sum(montant_eur) FILTER (WHERE statut <> 'echouee'), 0) - COALESCE(sum(montant_rembourse_eur), 0)
            FROM fait_transactions
            WHERE date_cle = ANY(%s)
            GROUP BY date_cle, marchand_cle
        """, (jours,))
        return cur.rowcount


def rafraichir_vues():
    """Rafraîchissement des vues matérialisées sans bloquer les lectures (CONCURRENTLY), par la
    fonction fn_rafraichir_vues, exécutée avec les droits du propriétaire des vues : le compte de
    chargement n'a pas besoin d'en être propriétaire."""
    with connexion_dwh() as dwh, dwh.cursor() as cur:
        cur.execute("SELECT fn_rafraichir_vues()")
        return [r[0] for r in cur.fetchall()]


def controler_qualite():
    """Contrôles de qualité après chargement ; une anomalie fait échouer la tâche (alerte visible
    dans Airflow) au lieu de laisser des données douteuses servir aux analyses."""
    anomalies, mesures = [], {}
    with connexion_oltp() as oltp, oltp.cursor() as source, connexion_dwh() as dwh, dwh.cursor() as cible:
        cible.execute("SELECT derniere_valeur FROM suivi_chargements WHERE flux = 'transactions'")
        ligne = cible.fetchone()
        filigrane = ligne[0] if ligne else "-infinity"
        source.execute("SELECT count(*) FROM transactions WHERE date_heure <= %s::timestamptz", (filigrane,))
        mesures["paiements_oltp_avant_filigrane"] = source.fetchone()[0]
        cible.execute("SELECT count(*) FROM fait_transactions")
        mesures["paiements_entrepot"] = cible.fetchone()[0]
        if mesures["paiements_entrepot"] < mesures["paiements_oltp_avant_filigrane"]:
            anomalies.append("Complétude : paiements manquants dans l'entrepôt")

        cible.execute("SELECT count(*) FROM fait_transactions WHERE montant_eur <= 0")
        mesures["montants_non_positifs"] = cible.fetchone()[0]
        if mesures["montants_non_positifs"]:
            anomalies.append("Validité : montants nuls ou négatifs")

        cible.execute("SELECT count(*) FROM fait_transactions WHERE montant_rembourse_eur > montant_eur + 0.01")
        mesures["remboursements_superieurs_au_montant"] = cible.fetchone()[0]
        if mesures["remboursements_superieurs_au_montant"]:
            anomalies.append("Cohérence : remboursements supérieurs au montant payé")

        cible.execute("""
            SELECT abs(COALESCE((SELECT sum(montant_net_eur) FROM agg_ca_quotidien_marchand), 0)
                     - COALESCE((SELECT sum(montant_eur) FILTER (WHERE statut <> 'echouee') - sum(montant_rembourse_eur)
                                 FROM fait_transactions), 0))
        """)
        mesures["ecart_agregats_eur"] = float(cible.fetchone()[0])
        if mesures["ecart_agregats_eur"] > 1:
            anomalies.append("Cohérence : table pré-agrégée différente de la table de faits")
    if anomalies:
        raise ValueError(f"Contrôles de qualité en échec : {anomalies} ; mesures : {mesures}")
    return mesures


# Contrôles de conformité

def _executer_controle(domaine, controle, reference, fonction):
    """Exécute un contrôle ; une erreur technique est consignée comme non-conformité."""
    try:
        conforme, detail = fonction()
    except Exception as erreur:
        conforme, detail = False, f"Contrôle impossible : {type(erreur).__name__} - {str(erreur)[:200]}"
    return {"domaine": domaine, "controle": controle, "reference": reference,
            "resultat": "conforme" if conforme else "non conforme", "detail": detail}


def controles_oltp():
    def chiffrement():
        # pgp_key_id renvoie SYMKEY pour une donnée chiffrée par clé symétrique et échoue sur une donnée en clair
        with connexion_oltp() as c, c.cursor() as cur:
            cur.execute("SELECT count(*), count(*) FILTER (WHERE pgp_key_id(email_chiffre) = 'SYMKEY') FROM clients")
            total, chiffres = cur.fetchone()
        return total == chiffres, f"{chiffres} adresses chiffrées sur {total}"

    def numeros_carte():
        with connexion_oltp() as c, c.cursor() as cur:
            cur.execute("SELECT count(*) FROM moyens_paiement WHERE jeton ~ '^[0-9]{13,19}$'")
            jetons_suspects = cur.fetchone()[0]
            cur.execute("""
                SELECT count(*) FROM information_schema.columns
                WHERE table_schema = 'public' AND column_name IN ('numero_carte', 'pan', 'card_number', 'cvv', 'cryptogramme')
            """)
            colonnes = cur.fetchone()[0]
        return (jetons_suspects == 0 and colonnes == 0,
                f"{jetons_suspects} jeton ressemblant à un numéro de carte, {colonnes} colonne interdite")

    def privilege_capture():
        # has_table_privilege interroge les droits d'un autre compte ; la vue role_table_grants ne
        # montrerait que les droits du compte connecté
        with connexion_oltp() as c, c.cursor() as cur:
            cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = 'cdc_debezium'")
            super_utilisateur = cur.fetchone()[0]
            cur.execute("""
                SELECT string_agg(t.relname, ', ' ORDER BY t.relname)
                FROM pg_class t JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = 'public' AND t.relkind IN ('r', 'p')
                  AND has_table_privilege('cdc_debezium', t.oid, 'SELECT, INSERT, UPDATE, DELETE')
            """)
            tables = cur.fetchone()[0]
        return (not super_utilisateur and tables == "transactions",
                f"administrateur : {'oui' if super_utilisateur else 'non'} ; tables accessibles : {tables}")

    def audit():
        with connexion_oltp() as c, c.cursor() as cur:
            cur.execute("""
                SELECT count(*) FROM pg_trigger
                WHERE tgname IN ('trg_journal_audit_immuable', 'trg_audit_transactions', 'trg_audit_clients') AND tgenabled = 'O'
            """)
            declencheurs = cur.fetchone()[0]
            cur.execute("SELECT max(date_action) > now() - interval '1 day' FROM journal_audit")
            recent = cur.fetchone()[0]
        return (declencheurs == 3 and bool(recent),
                f"{declencheurs} déclencheurs d'audit actifs sur 3 ; activité dans les dernières 24 heures : {'oui' if recent else 'non'}")

    def chiffrement_transit():
        # Toutes les connexions réseau ouvertes (programmes, réplica, capture des changements)
        with connexion_oltp() as c, c.cursor() as cur:
            cur.execute("""
                SELECT count(*), count(*) FILTER (WHERE s.ssl), string_agg(DISTINCT s.version, ', ')
                FROM pg_stat_activity a JOIN pg_stat_ssl s ON s.pid = a.pid
                WHERE a.client_addr IS NOT NULL
            """)
            total, chiffrees, versions = cur.fetchone()
        return (total > 0 and total == chiffrees,
                f"{chiffrees} connexions réseau chiffrées sur {total} ; protocole : {versions or 'aucun'}")

    return [
        _executer_controle("Base transactionnelle", "Chiffrement des échanges réseau (TLS)",
                           "RGPD, article 32 ; PCI-DSS, exigence 4 (chiffrement des données transmises)", chiffrement_transit),
        _executer_controle("Base transactionnelle", "Chiffrement des adresses e-mail des clients",
                           "RGPD, article 32 (sécurité du traitement)", chiffrement),
        _executer_controle("Base transactionnelle", "Absence de numéro de carte complet",
                           "PCI-DSS, exigence 3 (protection des données de carte stockées)", numeros_carte),
        _executer_controle("Base transactionnelle", "Moindre privilège du compte de capture des changements",
                           "PCI-DSS, exigence 7 (restriction des accès)", privilege_capture),
        _executer_controle("Base transactionnelle", "Journal d'audit actif et non modifiable",
                           "PCI-DSS, exigence 10 (journalisation et surveillance)", audit),
    ]


def controles_entrepot():
    def minimisation():
        with connexion_dwh() as c, c.cursor() as cur:
            cur.execute("""
                SELECT string_agg(table_name || '.' || column_name, ', ') FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND column_name IN ('email', 'email_chiffre', 'adresse_ip', 'jeton', 'quatre_derniers')
            """)
            colonnes = cur.fetchone()[0]
        return colonnes is None, "aucune colonne de donnée personnelle directe" if colonnes is None else f"colonnes trouvées : {colonnes}"

    return [_executer_controle("Entrepôt analytique", "Minimisation des données personnelles",
                               "RGPD, article 5.1.c (minimisation)", minimisation)]


def controles_capture():
    adresse = os.environ.get("CONNECT_URL", "http://connect:8083")

    def configuration():
        return requests.get(f"{adresse}/connectors/stripe-cdc-transactions/config", timeout=30).json()

    def exclusion_ip():
        exclues = configuration().get("column.exclude.list", "")
        return "adresse_ip" in exclues, f"colonnes exclues du flux : {exclues or 'aucune'}"

    def secret():
        reference = configuration().get("database.password", "").startswith("${env:")
        return reference, ("mot de passe référencé par variable d'environnement" if reference
                           else "mot de passe en clair dans la configuration")

    def disponibilite():
        etat = requests.get(f"{adresse}/connectors/stripe-cdc-transactions/status", timeout=30).json()
        connecteur, tache = etat["connector"]["state"], etat["tasks"][0]["state"]
        return connecteur == tache == "RUNNING", f"connecteur {connecteur}, tâche {tache}"

    return [
        _executer_controle("Capture des changements", "Exclusion de l'adresse IP du flux temps réel",
                           "RGPD, article 25 (protection des données dès la conception)", exclusion_ip),
        _executer_controle("Capture des changements", "Absence de secret en clair dans la configuration",
                           "PCI-DSS, exigence 8 (protection des identifiants)", secret),
        _executer_controle("Capture des changements", "Disponibilité du connecteur",
                           "Continuité du service", disponibilite),
    ]


def controles_mongodb():
    def conservation():
        base = base_mongo()
        ttl = [i for i in base.journaux_applicatifs.list_indexes() if i.get("expireAfterSeconds") == 7776000]
        limite = datetime.now(timezone.utc) - timedelta(days=91)
        anciens = base.journaux_applicatifs.count_documents({"horodatage": {"$lt": limite}})
        return (bool(ttl) and anciens == 0,
                f"index d'expiration à 90 jours : {'présent' if ttl else 'absent'} ; journaux de plus de 91 jours : {anciens}")

    def validation():
        base = base_mongo()
        attendues = {"transactions_enrichies", "profils_clients", "modeles_ml", "sessions_navigation",
                     "avis_clients", "journaux_applicatifs", "documents_externes"}
        validees = {c["name"] for c in base.list_collections() if "$jsonSchema" in c.get("options", {}).get("validator", {})}
        manquantes = attendues - validees
        detail = f"{len(attendues & validees)} collections sur 7 avec règles de validation"
        return not manquantes, detail + (f" ; sans règle : {sorted(manquantes)}" if manquantes else "")

    return [
        _executer_controle("Base NoSQL", "Durée de conservation limitée des journaux techniques",
                           "RGPD, article 5.1.e (limitation de la conservation)", conservation),
        _executer_controle("Base NoSQL", "Règles de validation des collections",
                           "Qualité et intégrité des données", validation),
    ]


def controles_replication():
    def replica():
        # Seules les connexions de réplication physique comptent : la connexion de Debezium, qui
        # lit le même journal par réplication logique (slot logique), est exclue
        with connexion_oltp() as c, c.cursor() as cur:
            cur.execute("""
                SELECT count(*) FROM pg_stat_replication
                WHERE state = 'streaming'
                  AND pid NOT IN (SELECT active_pid FROM pg_replication_slots
                                  WHERE slot_type = 'logical' AND active_pid IS NOT NULL)
            """)
            nb = cur.fetchone()[0]
        return nb >= 1, f"{nb} réplica en réplication continue"

    def retard_capture():
        with connexion_oltp() as c, c.cursor() as cur:
            cur.execute("""
                SELECT active, pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)
                FROM pg_replication_slots WHERE slot_name = 'slot_stripe_cdc'
            """)
            ligne = cur.fetchone()
        if ligne is None:
            return False, "slot de réplication slot_stripe_cdc absent"
        active, retard = ligne
        retard_mo = round(float(retard or 0) / 1024 / 1024, 1)
        return (bool(active) and retard_mo < 100,
                f"slot actif : {'oui' if active else 'non'} ; journal en attente de lecture : {retard_mo} Mo")

    return [
        _executer_controle("Disponibilité", "Réplication de la base transactionnelle",
                           "Continuité d'activité et reprise après sinistre", replica),
        _executer_controle("Disponibilité", "Retard de la capture des changements",
                           "Fraîcheur des données en temps réel", retard_capture),
    ]


def rediger_rapport(resultats, dossier):
    """Rapport daté au format Markdown, lisible par un auditeur, et trace dans les journaux applicatifs."""
    maintenant = datetime.now(timezone.utc)
    non_conformes = [r for r in resultats if r["resultat"] != "conforme"]
    lignes = [
        f"# Rapport de conformité du {maintenant:%d/%m/%Y}",
        "",
        f"Généré automatiquement le {maintenant:%d/%m/%Y à %H:%M} (temps universel) par la chaîne de tâches `controles_conformite`.",
        "",
        f"**Synthèse : {len(resultats) - len(non_conformes)} contrôles conformes sur {len(resultats)}.**",
        "",
        "| Domaine | Contrôle | Référence | Résultat | Détail |",
        "|---|---|---|---|---|",
    ]
    lignes += [f"| {r['domaine']} | {r['controle']} | {r['reference']} | {r['resultat']} | {r['detail']} |" for r in resultats]
    lignes += [
        "",
        "## Hors périmètre de la démonstration locale",
        "",
        "Chiffrement TLS des échanges avec l'entrepôt, MongoDB et Kafka, et chiffrement des disques au repos : "
        "prévus dans l'architecture cible et décrits dans le plan de sécurité ; non contrôlés ici, "
        "l'environnement de démonstration fonctionnant sur un réseau Docker interne à un seul poste. "
        "Les échanges avec la base transactionnelle, la plus sensible, sont chiffrés et contrôlés ci-dessus.",
        "",
    ]
    os.makedirs(dossier, exist_ok=True)
    chemin = os.path.join(dossier, f"rapport_conformite_{maintenant:%Y-%m-%d}.md")
    with open(chemin, "w", encoding="utf-8") as fichier:
        fichier.write("\n".join(lignes))

    base_mongo().journaux_applicatifs.insert_one({
        "horodatage": maintenant, "niveau": "ERREUR" if non_conformes else "INFO",
        "source": {"service": "controles-conformite", "hote": "airflow"},
        "message": f"Contrôles de conformité : {len(resultats) - len(non_conformes)} conformes sur {len(resultats)}",
    })
    return {"rapport": chemin, "non_conformes": [r["controle"] for r in non_conformes]}


# Service d'entraînement

def appeler_service_ml(chemin):
    """Appel d'un point d'accès du service d'entraînement ; une réponse en erreur fait échouer la tâche."""
    reponse = requests.post(f"{os.environ['SERVICE_ML_URL']}{chemin}", timeout=900)
    reponse.raise_for_status()
    return reponse.json()
