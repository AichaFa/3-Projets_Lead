-- Base transactionnelle (OLTP) - Stripe Business Case
-- Contrôle d'accès par rôles (RBAC) : un rôle par usage, un compte de service par programme
--
-- Principes
-- - Moindre privilège : chaque rôle reçoit uniquement les droits nécessaires à son usage.
-- - Séparation rôle / compte : le rôle porte les droits (NOLOGIN), le compte porte l'identité
--   (LOGIN) et hérite des droits de son rôle ; un nouveau programme reçoit un nouveau compte.
-- - Aucun droit de suppression ni de modification des montants pour les comptes de service.
-- - Mots de passe lus dans les variables d'environnement du conteneur (\getenv), absents du dépôt.

\getenv mdp_paiements APP_PAIEMENTS_PASSWORD
\getenv mdp_flux FLUX_TEMPS_REEL_PASSWORD
\getenv mdp_orchestrateur ORCHESTRATEUR_OLTP_PASSWORD

-- Règles métier exécutées avec les droits de leur propriétaire : un compte limité déclenche les
-- contrôles (remboursements, litiges, abonnements) sans détenir lui-même le droit de modifier
-- les paiements. search_path fixé pour empêcher le détournement d'objets par un autre schéma.
ALTER FUNCTION fn_controle_remboursement() SECURITY DEFINER SET search_path = public;
ALTER FUNCTION fn_controle_litige()        SECURITY DEFINER SET search_path = public;
ALTER FUNCTION fn_controle_abonnement()    SECURITY DEFINER SET search_path = public;

-- Rôles (ensembles de droits)

-- Application de paiement : enregistre marchands, clients, moyens de paiement, abonnements,
-- paiements, remboursements et litiges ; aucune modification ni suppression
CREATE ROLE role_application_paiements NOLOGIN;
GRANT USAGE ON SCHEMA public TO role_application_paiements;
GRANT SELECT ON pays, devises, taux_change, marchands, produits, abonnements TO role_application_paiements;
GRANT SELECT (client_id, code_pays) ON clients TO role_application_paiements;
GRANT SELECT (moyen_paiement_id, client_id) ON moyens_paiement TO role_application_paiements;
GRANT INSERT ON marchands, produits, clients, moyens_paiement, abonnements,
                transactions, remboursements, litiges, taux_change TO role_application_paiements;

-- Flux temps réel et apprentissage : lecture des paiements sans l'adresse IP, lecture du seul
-- pays et de la date d'inscription des clients (jamais de l'adresse e-mail), écriture limitée
-- à la colonne du score de fraude
CREATE ROLE role_flux_temps_reel NOLOGIN;
GRANT USAGE ON SCHEMA public TO role_flux_temps_reel;
GRANT SELECT (transaction_id, marchand_id, client_id, moyen_paiement_id, produit_id, abonnement_id,
              montant, code_devise, statut, date_heure, pays_ip, type_appareil, score_anomalie, date_maj)
      ON transactions TO role_flux_temps_reel;
GRANT UPDATE (score_anomalie) ON transactions TO role_flux_temps_reel;
GRANT SELECT (client_id, code_pays, date_creation) ON clients TO role_flux_temps_reel;
GRANT SELECT ON taux_change, marchands, produits, litiges TO role_flux_temps_reel;

-- Orchestrateur : lecture seule de toutes les tables (alimentation de l'entrepôt, contrôles de
-- conformité) et lecture des statistiques de réplication (rôle prédéfini pg_monitor).
-- L'adresse e-mail n'est lisible que sous forme chiffrée : la clé de déchiffrement n'est pas
-- transmise à l'orchestrateur.
CREATE ROLE role_orchestrateur NOLOGIN;
GRANT USAGE ON SCHEMA public TO role_orchestrateur;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO role_orchestrateur;
GRANT pg_monitor TO role_orchestrateur;

-- Comptes de service (identités)

CREATE ROLE svc_generateur LOGIN PASSWORD :'mdp_paiements' IN ROLE role_application_paiements;
CREATE ROLE svc_flux       LOGIN PASSWORD :'mdp_flux'      IN ROLE role_flux_temps_reel;
CREATE ROLE svc_airflow    LOGIN PASSWORD :'mdp_orchestrateur' IN ROLE role_orchestrateur;

COMMENT ON ROLE role_application_paiements IS 'Application de paiement : création uniquement, ni modification ni suppression';
COMMENT ON ROLE role_flux_temps_reel       IS 'Flux temps réel et apprentissage : lecture sans données personnelles, écriture du seul score';
COMMENT ON ROLE role_orchestrateur         IS 'Orchestrateur : lecture seule et statistiques de réplication';
COMMENT ON ROLE svc_generateur IS 'Compte du générateur (application de paiement simulée)';
COMMENT ON ROLE svc_flux       IS 'Compte du consommateur temps réel et du service d''entraînement';
COMMENT ON ROLE svc_airflow    IS 'Compte de l''orchestrateur Airflow';
