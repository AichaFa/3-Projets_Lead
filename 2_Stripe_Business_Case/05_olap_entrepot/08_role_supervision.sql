-- Entrepôt analytique (OLAP) - Stripe Business Case
-- Compte de supervision de l'infrastructure (tableau de bord Grafana)
--
-- Lecture seule : suivi des chargements (fraîcheur de l'entrepôt) et dates de chargement des
-- paiements (volume chargé par heure), sans montant ni donnée client.
-- Mot de passe lu dans la variable d'environnement du conteneur (\getenv).

\getenv mdp_supervision SUPERVISION_DWH_PASSWORD

CREATE ROLE role_supervision NOLOGIN;
GRANT USAGE ON SCHEMA public TO role_supervision;
GRANT SELECT ON suivi_chargements TO role_supervision;
GRANT SELECT (date_chargement) ON fait_transactions TO role_supervision;

CREATE ROLE svc_grafana_dwh LOGIN PASSWORD :'mdp_supervision' IN ROLE role_supervision;

COMMENT ON ROLE role_supervision IS 'Supervision : fraîcheur et volume des chargements, sans donnée métier';
COMMENT ON ROLE svc_grafana_dwh  IS 'Compte du tableau de bord de supervision Grafana';
