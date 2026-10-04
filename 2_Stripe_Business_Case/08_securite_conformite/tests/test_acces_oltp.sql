-- Tests du contrôle d'accès par rôles - Base transactionnelle (OLTP)
--
-- Chaque essai est exécuté sous l'identité d'un compte de service ; la fonction tests.essai
-- tente l'opération et compare le résultat (autorisé ou refusé) au résultat attendu.
-- Les essais d'écriture portent sur « WHERE false » : PostgreSQL vérifie les droits avant
-- l'exécution, aucune donnée n'est modifiée. Le schéma de test est supprimé en fin d'exécution.

\set QUIET on
\pset tuples_only on
\pset format unaligned
\getenv administrateur POSTGRES_USER

CREATE SCHEMA tests;
GRANT USAGE ON SCHEMA tests TO PUBLIC;
CREATE FUNCTION tests.essai(libelle TEXT, requete TEXT, attendu TEXT) RETURNS TEXT
LANGUAGE plpgsql SECURITY INVOKER AS $$
DECLARE
    obtenu TEXT;
BEGIN
    BEGIN
        EXECUTE requete;
        obtenu := 'autorisé';
    EXCEPTION WHEN insufficient_privilege THEN
        obtenu := 'refusé';
    END;
    RETURN format('%s | %-15s | %s | attendu : %s | obtenu : %s',
                  CASE WHEN obtenu = attendu THEN 'CONFORME    ' ELSE 'NON CONFORME' END,
                  current_user, libelle, attendu, obtenu);
END;
$$;

\connect - svc_generateur
SELECT tests.essai('Créer un paiement', 'INSERT INTO transactions (marchand_id) SELECT NULL WHERE false', 'autorisé');
SELECT tests.essai('Lire l''adresse e-mail chiffrée d''un client', 'SELECT email_chiffre FROM clients LIMIT 1', 'refusé');
SELECT tests.essai('Modifier le montant d''un paiement', 'UPDATE transactions SET montant = 1 WHERE false', 'refusé');
SELECT tests.essai('Supprimer un paiement', 'DELETE FROM transactions WHERE false', 'refusé');
SELECT tests.essai('Lire le journal d''audit', 'SELECT * FROM journal_audit LIMIT 1', 'refusé');

\connect - svc_flux
SELECT tests.essai('Lire les paiements sans l''adresse IP', 'SELECT transaction_id, montant, pays_ip, score_anomalie FROM transactions LIMIT 1', 'autorisé');
SELECT tests.essai('Lire l''adresse IP d''un paiement', 'SELECT adresse_ip FROM transactions LIMIT 1', 'refusé');
SELECT tests.essai('Lire le pays et la date d''inscription des clients', 'SELECT code_pays, date_creation FROM clients LIMIT 1', 'autorisé');
SELECT tests.essai('Lire l''adresse e-mail chiffrée d''un client', 'SELECT email_chiffre FROM clients LIMIT 1', 'refusé');
SELECT tests.essai('Écrire le score de fraude', 'UPDATE transactions SET score_anomalie = 0 WHERE false', 'autorisé');
SELECT tests.essai('Modifier le statut d''un paiement', 'UPDATE transactions SET statut = ''reussie'' WHERE false', 'refusé');
SELECT tests.essai('Créer un paiement', 'INSERT INTO transactions (marchand_id) SELECT NULL WHERE false', 'refusé');

\connect - svc_airflow
SELECT tests.essai('Lire le journal d''audit', 'SELECT count(*) FROM journal_audit', 'autorisé');
SELECT tests.essai('Lire les statistiques de réplication', 'SELECT count(*) FROM pg_stat_replication', 'autorisé');
SELECT tests.essai('Modifier un référentiel', 'UPDATE pays SET nom = nom WHERE false', 'refusé');
SELECT tests.essai('Supprimer une ligne du journal d''audit', 'DELETE FROM journal_audit WHERE false', 'refusé');

\connect - cdc_debezium
SELECT tests.essai('Lire les paiements', 'SELECT count(*) FROM transactions', 'autorisé');
SELECT tests.essai('Lire les clients', 'SELECT count(*) FROM clients', 'refusé');

\connect - :administrateur
SET client_min_messages = warning;
DROP SCHEMA tests CASCADE;
