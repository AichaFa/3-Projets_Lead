-- Requêtes métier - Entrepôt analytique (OLAP) - Stripe Business Case
--
-- Exécution avec le compte analyste_demo (rôle role_analyste) : lecture des faits, dimensions,
-- agrégats et vues matérialisées, sans accès au journal d'audit ni aux données personnelles.
-- Montants en euros, convertis au taux du jour du paiement lors du chargement.
-- Paiements échoués exclus du chiffre d'affaires ; montant net = montant encaissé - remboursements.

\pset null '-'
\pset numericlocale off

-- Q1. Chiffre d'affaires net par mois et par région du marchand (six derniers mois)
-- Schéma en étoile : la table de faits est jointe aux dimensions date et marchand
\echo '\n=== Q1. Chiffre d''affaires net par mois et par région (six derniers mois)'
SELECT d.annee,
       d.mois,
       d.nom_mois,
       m.region,
       count(*) FILTER (WHERE f.statut <> 'echouee')                          AS nb_paiements,
       round(sum(f.montant_eur) FILTER (WHERE f.statut <> 'echouee'), 2)       AS ca_brut_eur,
       round(sum(f.montant_rembourse_eur), 2)                                  AS rembourse_eur,
       round(sum(f.montant_eur) FILTER (WHERE f.statut <> 'echouee')
             - sum(f.montant_rembourse_eur), 2)                                AS ca_net_eur
FROM fait_transactions f
JOIN dim_date d     ON d.date_cle = f.date_cle
JOIN dim_marchand m ON m.marchand_cle = f.marchand_cle
WHERE d.date_complete >= date_trunc('month', current_date) - interval '5 months'
GROUP BY d.annee, d.mois, d.nom_mois, m.region
ORDER BY d.annee, d.mois, ca_net_eur DESC;

-- Q2. Série temporelle hebdomadaire : chiffre d'affaires net, moyenne glissante sur quatre semaines
-- et variation par rapport à la semaine précédente (fonctions de fenêtre)
-- La semaine en cours est incomplète : sa variation est à interpréter avec prudence
\echo '\n=== Q2. Évolution hebdomadaire du chiffre d''affaires net (douze dernières semaines)'
WITH semaines AS (
    SELECT date_trunc('week', d.date_complete)::date                              AS semaine,
           sum(f.montant_eur) FILTER (WHERE f.statut <> 'echouee') - sum(f.montant_rembourse_eur) AS ca_net_eur
    FROM fait_transactions f
    JOIN dim_date d ON d.date_cle = f.date_cle
    GROUP BY 1
)
SELECT semaine,
       round(ca_net_eur, 2)                                                       AS ca_net_eur,
       round(avg(ca_net_eur) OVER (ORDER BY semaine ROWS BETWEEN 3 PRECEDING AND CURRENT ROW), 2) AS moyenne_glissante_4_semaines,
       round(100.0 * (ca_net_eur - lag(ca_net_eur) OVER w) / NULLIF(lag(ca_net_eur) OVER w, 0), 1) AS variation_pct
FROM semaines
WINDOW w AS (ORDER BY semaine)
ORDER BY semaine DESC
LIMIT 12;

-- Q3. Dix marchands les plus rentables sur 90 jours et leur taux de remboursement
-- Table pré-agrégée : quelques milliers de lignes lues au lieu de dizaines de milliers de paiements
\echo '\n=== Q3. Dix marchands les plus rentables (90 derniers jours)'
SELECT m.raison_sociale,
       m.categorie,
       m.nom_pays,
       sum(a.nb_reussies)                                                           AS paiements_reussis,
       round(sum(a.montant_net_eur), 2)                                             AS ca_net_eur,
       round(100.0 * sum(a.montant_rembourse_eur) / NULLIF(sum(a.montant_brut_eur), 0), 2) AS taux_remboursement_pct
FROM agg_ca_quotidien_marchand a
JOIN dim_marchand m ON m.marchand_cle = a.marchand_cle
JOIN dim_date d     ON d.date_cle = a.date_cle
WHERE d.date_complete >= current_date - 90
GROUP BY m.raison_sociale, m.categorie, m.nom_pays
ORDER BY ca_net_eur DESC
LIMIT 10;

-- Q4. Pays de l'adresse IP présentant le plus de paiements suspects (score de fraude >= 0,8)
-- Vue matérialisée de fraude ; seuil de 50 paiements pour écarter les pays trop peu représentés
\echo '\n=== Q4. Pays de l''adresse IP les plus exposés à la fraude'
SELECT g.nom_pays                                                                  AS pays_ip,
       sum(v.nb_transactions)                                                      AS nb_paiements,
       sum(v.nb_suspectes)                                                         AS nb_suspects,
       round(100.0 * sum(v.nb_suspectes) / sum(v.nb_transactions), 2)              AS taux_suspects_pct,
       sum(v.nb_litiges_fraude)                                                    AS litiges_fraude,
       round(sum(v.montant_suspect_eur), 2)                                        AS montant_suspect_eur
FROM mv_fraude_quotidienne_pays v
JOIN dim_geographie g ON g.geographie_cle = v.geographie_ip_cle
GROUP BY g.nom_pays
HAVING sum(v.nb_transactions) >= 50
ORDER BY taux_suspects_pct DESC
LIMIT 10;

-- Q5. Performance des produits du catalogue sur les trois derniers mois
-- Vue matérialisée des produits ; la ligne « Sans produit » (clé 0) est exclue
\echo '\n=== Q5. Dix produits les plus vendus et leur taux de remboursement (trois derniers mois)'
SELECT p.nom                                                                       AS produit,
       p.raison_sociale_marchand                                                   AS marchand,
       sum(v.nb_ventes)                                                            AS ventes,
       sum(v.nb_ventes_abonnement)                                                 AS dont_abonnements,
       round(sum(v.chiffre_affaires_eur), 2)                                       AS ca_eur,
       round(100.0 * sum(v.nb_ventes_remboursees) / sum(v.nb_ventes), 2)           AS taux_ventes_remboursees_pct
FROM mv_performance_produits_mensuelle v
JOIN dim_produit p ON p.produit_cle = v.produit_cle
WHERE v.produit_cle <> 0
  AND make_date(v.annee, v.mois, 1) >= date_trunc('month', current_date) - interval '2 months'
GROUP BY p.nom, p.raison_sociale_marchand
ORDER BY ca_eur DESC
LIMIT 10;

-- Q6. Segmentation des clients (méthode RFM : récence, fréquence, montant)
-- Poids de chaque segment dans le chiffre d'affaires (fonction de fenêtre sur l'ensemble)
\echo '\n=== Q6. Segments de clients : effectif, comportement et poids dans le chiffre d''affaires'
SELECT segment,
       count(*)                                                                    AS nb_clients,
       round(avg(recence_jours))                                                   AS recence_moyenne_jours,
       round(avg(frequence), 1)                                                    AS achats_moyens,
       round(sum(montant_net_eur), 2)                                              AS ca_net_eur,
       round(100.0 * sum(montant_net_eur) / sum(sum(montant_net_eur)) OVER (), 1)  AS part_ca_pct
FROM mv_segmentation_rfm
GROUP BY segment
ORDER BY ca_net_eur DESC;

-- Q7. Efficacité du modèle de fraude : part de litiges pour fraude selon la décision du modèle
-- Lecture indicative : les scores de l'historique ont été attribués par un modèle entraîné sur ces
-- mêmes données ; la mesure rigoureuse est celle de l'évaluation sur données jamais vues (modeles_ml)
\echo '\n=== Q7. Litiges pour fraude selon la décision du modèle'
SELECT CASE WHEN score_anomalie >= 0.8 THEN '1. bloquer (score >= 0,8)'
            WHEN score_anomalie >= 0.5 THEN '2. verifier (0,5 à 0,8)'
            ELSE '3. accepter (score < 0,5)' END                                   AS decision_du_modele,
       count(*)                                                                    AS nb_paiements,
       count(*) FILTER (WHERE a_litige AND motif_litige = 'fraude')                AS litiges_fraude,
       round(100.0 * count(*) FILTER (WHERE a_litige AND motif_litige = 'fraude') / count(*), 2) AS taux_litiges_fraude_pct,
       round(sum(montant_eur), 2)                                                  AS montant_eur
FROM fait_transactions
WHERE score_anomalie IS NOT NULL
GROUP BY 1
ORDER BY 1;
