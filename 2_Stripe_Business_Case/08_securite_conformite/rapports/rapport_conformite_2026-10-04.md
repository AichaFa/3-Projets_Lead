# Rapport de conformité du 04/10/2026

Généré automatiquement le 04/10/2026 à 19:24 (temps universel) par la chaîne de tâches `controles_conformite`.

**Synthèse : 13 contrôles conformes sur 13.**

| Domaine | Contrôle | Référence | Résultat | Détail |
|---|---|---|---|---|
| Base transactionnelle | Chiffrement des échanges réseau (TLS) | RGPD, article 32 ; PCI-DSS, exigence 4 (chiffrement des données transmises) | conforme | 8 connexions réseau chiffrées sur 8 ; protocole : TLSv1.3 |
| Base transactionnelle | Chiffrement des adresses e-mail des clients | RGPD, article 32 (sécurité du traitement) | conforme | 2000 adresses chiffrées sur 2000 |
| Base transactionnelle | Absence de numéro de carte complet | PCI-DSS, exigence 3 (protection des données de carte stockées) | conforme | 0 jeton ressemblant à un numéro de carte, 0 colonne interdite |
| Base transactionnelle | Moindre privilège du compte de capture des changements | PCI-DSS, exigence 7 (restriction des accès) | conforme | administrateur : non ; tables accessibles : transactions |
| Base transactionnelle | Journal d'audit actif et non modifiable | PCI-DSS, exigence 10 (journalisation et surveillance) | conforme | 3 déclencheurs d'audit actifs sur 3 ; activité dans les dernières 24 heures : oui |
| Entrepôt analytique | Minimisation des données personnelles | RGPD, article 5.1.c (minimisation) | conforme | aucune colonne de donnée personnelle directe |
| Capture des changements | Exclusion de l'adresse IP du flux temps réel | RGPD, article 25 (protection des données dès la conception) | conforme | colonnes exclues du flux : public.transactions.adresse_ip |
| Capture des changements | Absence de secret en clair dans la configuration | PCI-DSS, exigence 8 (protection des identifiants) | conforme | mot de passe référencé par variable d'environnement |
| Capture des changements | Disponibilité du connecteur | Continuité du service | conforme | connecteur RUNNING, tâche RUNNING |
| Base NoSQL | Durée de conservation limitée des journaux techniques | RGPD, article 5.1.e (limitation de la conservation) | conforme | index d'expiration à 90 jours : présent ; journaux de plus de 91 jours : 0 |
| Base NoSQL | Règles de validation des collections | Qualité et intégrité des données | conforme | 7 collections sur 7 avec règles de validation |
| Disponibilité | Réplication de la base transactionnelle | Continuité d'activité et reprise après sinistre | conforme | 1 réplica en réplication continue |
| Disponibilité | Retard de la capture des changements | Fraîcheur des données en temps réel | conforme | slot actif : oui ; journal en attente de lecture : 0.3 Mo |

## Hors périmètre de la démonstration locale

Chiffrement TLS des échanges avec l'entrepôt, MongoDB et Kafka, et chiffrement des disques au repos : prévus dans l'architecture cible et décrits dans le plan de sécurité ; non contrôlés ici, l'environnement de démonstration fonctionnant sur un réseau Docker interne à un seul poste. Les échanges avec la base transactionnelle, la plus sensible, sont chiffrés et contrôlés ci-dessus.
