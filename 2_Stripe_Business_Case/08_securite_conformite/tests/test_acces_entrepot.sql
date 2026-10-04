-- Tests du contrôle d'accès par rôles - Entrepôt analytique (OLAP)
--
-- Même principe que pour la base transactionnelle : chaque essai est exécuté sous l'identité
-- d'un compte, sans aucune modification de données, et le schéma de test est supprimé à la fin.

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

\connect - analyste_demo
SELECT tests.essai('Lire les paiements', 'SELECT count(*) FROM fait_transactions', 'autorisé');
SELECT tests.essai('Lire la segmentation des clients', 'SELECT count(*) FROM mv_segmentation_rfm', 'autorisé');
SELECT tests.essai('Lire le journal d''audit', 'SELECT count(*) FROM fait_audit', 'refusé');
SELECT tests.essai('Modifier un agrégat', 'UPDATE agg_ca_quotidien_marchand SET nb_transactions = 0 WHERE false', 'refusé');
SELECT tests.essai('Rafraîchir les vues matérialisées', 'SELECT fn_rafraichir_vues() WHERE false', 'refusé');

\connect - auditeur_demo
SELECT tests.essai('Lire le journal d''audit', 'SELECT count(*) FROM fait_audit', 'autorisé');
SELECT tests.essai('Lire les paiements', 'SELECT count(*) FROM fait_transactions', 'refusé');
SELECT tests.essai('Lire les clients', 'SELECT count(*) FROM dim_client', 'refusé');

\connect - svc_airflow_dwh
SELECT tests.essai('Écrire dans la table de faits', 'DELETE FROM fait_transactions WHERE false', 'autorisé');
SELECT tests.essai('Rafraîchir les vues matérialisées', 'SELECT fn_rafraichir_vues() WHERE false', 'autorisé');
SELECT tests.essai('Supprimer une table (journal d''audit)', 'DROP TABLE fait_audit', 'refusé');

\connect - :administrateur
SET client_min_messages = warning;
DROP SCHEMA tests CASCADE;
