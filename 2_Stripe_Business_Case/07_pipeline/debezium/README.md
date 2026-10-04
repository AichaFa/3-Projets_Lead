# Connecteur Debezium : capture des changements de la table des paiements

Le fichier `connecteur_transactions.json` déclare le connecteur auprès de Kafka Connect (API REST).
Le format JSON n'admettant pas de commentaires, chaque réglage est documenté ci-dessous.

| Réglage | Valeur | Justification |
|---|---|---|
| `connector.class` | `PostgresConnector` | Connecteur Debezium pour PostgreSQL |
| `plugin.name` | `pgoutput` | Module de décodage logique natif de PostgreSQL, sans extension à installer |
| `database.user` | `cdc_debezium` | Compte dédié, non administrateur (moindre privilège) |
| `database.password` | `${env:CDC_PASSWORD}` | Référence à une variable d'environnement du conteneur Kafka Connect (EnvVarConfigProvider, Kafka 3.5 et plus) : le mot de passe n'apparaît ni dans ce fichier ni dans les sujets internes de Kafka Connect |
| `database.sslmode` | `verify-full` | Connexion chiffrée (TLS) avec vérification complète du serveur : certificat signé par l'autorité du projet et nom `postgres-oltp` présent dans le certificat (protection contre l'usurpation). Valeur par défaut de Debezium : `disable` (connexion en clair), refusée par la base transactionnelle |
| `database.sslrootcert` | `/certificats/ca.crt` | Certificat de l'autorité de certification du projet, monté en lecture seule dans le conteneur Kafka Connect |
| `topic.prefix` | `stripe` | Préfixe des sujets Kafka : les paiements sont publiés dans `stripe.public.transactions` |
| `table.include.list` | `public.transactions` | Seule la table des paiements est capturée |
| `column.exclude.list` | `public.transactions.adresse_ip` | Minimisation des données (RGPD) : l'adresse IP, donnée personnelle, ne quitte pas la base OLTP ; le pays déduit (`pays_ip`) suffit à la détection de fraude |
| `message.key.columns` | `public.transactions:client_id` | Clé des messages Kafka égale à l'identifiant du client (au lieu de l'identifiant du paiement) : tous les paiements d'un même client sont publiés dans la même partition, où Kafka garantit l'ordre ; le consommateur traite ainsi les rafales d'un client dans l'ordre chronologique |
| `publication.name` | `pub_stripe_cdc` | Publication créée par l'administrateur (script `05_role_cdc.sql`) |
| `publication.autocreate.mode` | `disabled` | Le connecteur utilise la publication existante sans droit de création |
| `slot.name` | `slot_stripe_cdc` | Slot de réplication logique : PostgreSQL conserve le journal tant que Debezium ne l'a pas lu, aucune modification n'est perdue en cas d'arrêt du connecteur |
| `snapshot.mode` | `no_data` | Lecture de la structure des tables sans transmission des lignes existantes : l'historique, déjà noté par l'entraînement initial, n'est pas retraité |
| `decimal.handling.mode` | `string` | Montants transmis en texte (`"80.00"`) : précision exacte, sans arrondi binaire |
| `tombstones.on.delete` | `false` | Pas de message de suppression supplémentaire (les paiements ne sont jamais supprimés) |
