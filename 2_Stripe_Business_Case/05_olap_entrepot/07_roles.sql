-- Entrepôt analytique (OLAP) - Stripe Business Case
-- Contrôle d'accès par rôles (RBAC) : chargement, analyse et audit séparés
--
-- - role_chargement : écriture par l'orchestrateur (aucun accès humain) ;
-- - role_analyste   : lecture des faits, dimensions, agrégats et vues, sans le journal d'audit ;
-- - role_auditeur   : lecture du journal d'audit et du suivi des chargements uniquement.
-- Mots de passe lus dans les variables d'environnement du conteneur (\getenv).

\getenv mdp_chargement CHARGEMENT_DWH_PASSWORD
\getenv mdp_analyste ANALYSTE_DWH_PASSWORD
\getenv mdp_auditeur AUDITEUR_DWH_PASSWORD

-- Opérations réservées au propriétaire des objets (création de partition, rafraîchissement des
-- vues matérialisées), exposées sous forme de fonctions exécutées avec ses droits : le compte de
-- chargement peut les déclencher sans être propriétaire des tables
ALTER FUNCTION fn_creer_partition_mensuelle(DATE) SECURITY DEFINER SET search_path = public;

CREATE FUNCTION fn_rafraichir_vues() RETURNS SETOF TEXT
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_vue TEXT;
BEGIN
    FOREACH v_vue IN ARRAY ARRAY['mv_fraude_quotidienne_pays', 'mv_performance_produits_mensuelle', 'mv_segmentation_rfm'] LOOP
        EXECUTE format('REFRESH MATERIALIZED VIEW CONCURRENTLY %I', v_vue);
        RETURN NEXT v_vue;
    END LOOP;
END;
$$;
REVOKE EXECUTE ON FUNCTION fn_rafraichir_vues() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION fn_creer_partition_mensuelle(DATE) FROM PUBLIC;

-- Rôles

CREATE ROLE role_chargement NOLOGIN;
GRANT USAGE ON SCHEMA public TO role_chargement;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO role_chargement;
GRANT EXECUTE ON FUNCTION fn_rafraichir_vues(), fn_creer_partition_mensuelle(DATE) TO role_chargement;

CREATE ROLE role_analyste NOLOGIN;
GRANT USAGE ON SCHEMA public TO role_analyste;
GRANT SELECT ON dim_date, dim_client, dim_marchand, dim_produit, dim_geographie, dim_devise, dim_moyen_paiement,
                fait_transactions, agg_ca_quotidien_marchand,
                mv_fraude_quotidienne_pays, mv_performance_produits_mensuelle, mv_segmentation_rfm
      TO role_analyste;

CREATE ROLE role_auditeur NOLOGIN;
GRANT USAGE ON SCHEMA public TO role_auditeur;
GRANT SELECT ON fait_audit, suivi_chargements, dim_date TO role_auditeur;

-- Comptes

CREATE ROLE svc_airflow_dwh LOGIN PASSWORD :'mdp_chargement' IN ROLE role_chargement;
CREATE ROLE analyste_demo   LOGIN PASSWORD :'mdp_analyste'   IN ROLE role_analyste;
CREATE ROLE auditeur_demo   LOGIN PASSWORD :'mdp_auditeur'   IN ROLE role_auditeur;

COMMENT ON ROLE role_chargement IS 'Chargement de l''entrepôt par l''orchestrateur';
COMMENT ON ROLE role_analyste   IS 'Analyse : lecture des données analytiques, sans le journal d''audit';
COMMENT ON ROLE role_auditeur   IS 'Audit : lecture du journal d''audit et du suivi des chargements';
COMMENT ON FUNCTION fn_rafraichir_vues() IS 'Rafraîchissement sans blocage des trois vues matérialisées, avec les droits du propriétaire';
