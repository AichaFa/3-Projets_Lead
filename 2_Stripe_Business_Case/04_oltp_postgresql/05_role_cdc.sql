-- Base transactionnelle (OLTP) - Stripe Business Case
-- Préparation de la capture des changements (CDC) par Debezium
--
-- Principe du moindre privilège : le compte de capture n'est pas administrateur. Il dispose
-- uniquement de l'attribut REPLICATION (lecture du journal des transactions) et du droit de
-- lecture sur la seule table capturée. La publication, qui délimite les données transmises,
-- est créée à l'avance par l'administrateur (publication.autocreate.mode = disabled côté
-- connecteur), au lieu d'accorder au compte de capture le droit de la créer lui-même.
--
-- Mot de passe lu dans la variable d'environnement CDC_PASSWORD du conteneur (commande \getenv
-- de psql) : il n'apparaît dans aucun fichier du dépôt.

\getenv mot_de_passe_cdc CDC_PASSWORD

CREATE ROLE cdc_debezium WITH LOGIN REPLICATION PASSWORD :'mot_de_passe_cdc';

GRANT USAGE ON SCHEMA public TO cdc_debezium;
GRANT SELECT ON transactions TO cdc_debezium;

-- Publication limitée aux paiements : seules les modifications de cette table sont diffusées
CREATE PUBLICATION pub_stripe_cdc FOR TABLE transactions;

COMMENT ON ROLE cdc_debezium IS 'Compte de capture des changements (Debezium), lecture seule de la table transactions';
