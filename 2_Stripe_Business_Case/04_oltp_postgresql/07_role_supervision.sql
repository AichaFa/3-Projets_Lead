-- Base transactionnelle (OLTP) - Stripe Business Case
-- Compte de supervision de l'infrastructure (tableau de bord Grafana)
--
-- Lecture seule, sans aucune donnée personnelle :
-- - statistiques internes de PostgreSQL (connexions, chiffrement, réplication, cache) par le rôle
--   prédéfini pg_monitor ;
-- - trois colonnes des paiements (date, statut, score) pour le débit et la part de paiements bloqués.
-- Mot de passe lu dans la variable d'environnement du conteneur (\getenv).

\getenv mdp_supervision SUPERVISION_OLTP_PASSWORD

CREATE ROLE role_supervision NOLOGIN;
GRANT pg_monitor TO role_supervision;
GRANT USAGE ON SCHEMA public TO role_supervision;
GRANT SELECT (date_heure, statut, score_anomalie) ON transactions TO role_supervision;

CREATE ROLE svc_grafana LOGIN PASSWORD :'mdp_supervision' IN ROLE role_supervision;

COMMENT ON ROLE role_supervision IS 'Supervision : statistiques internes et débit des paiements, sans donnée personnelle';
COMMENT ON ROLE svc_grafana      IS 'Compte du tableau de bord de supervision Grafana';
