-- Entrepôt analytique (OLAP) - Stripe Business Case
-- Vues matérialisées : résultats de calcul stockés, rafraîchis par l'orchestrateur
-- Chaque vue possède un index unique, condition du rafraîchissement sans blocage (REFRESH ... CONCURRENTLY)

-- Fraude par jour et par pays de l'adresse IP
CREATE MATERIALIZED VIEW mv_fraude_quotidienne_pays AS
SELECT f.date_cle,
       f.geographie_ip_cle,
       count(*)                                                          AS nb_transactions,
       count(*) FILTER (WHERE f.score_anomalie >= 0.8)                   AS nb_suspectes,
       count(*) FILTER (WHERE f.a_litige)                                AS nb_litiges,
       count(*) FILTER (WHERE f.a_litige AND f.motif_litige = 'fraude')  AS nb_litiges_fraude,
       round(avg(f.score_anomalie), 4)                                   AS score_moyen,
       COALESCE(sum(f.montant_eur) FILTER (WHERE f.score_anomalie >= 0.8), 0) AS montant_suspect_eur
FROM fait_transactions f
GROUP BY f.date_cle, f.geographie_ip_cle;

CREATE UNIQUE INDEX uq_mv_fraude ON mv_fraude_quotidienne_pays (date_cle, geographie_ip_cle);

-- Performance mensuelle des produits (les paiements échoués ne sont pas des ventes)
CREATE MATERIALIZED VIEW mv_performance_produits_mensuelle AS
SELECT d.annee,
       d.mois,
       f.produit_cle,
       count(*)                                     AS nb_ventes,
       sum(f.montant_eur)                           AS chiffre_affaires_eur,
       sum(f.montant_rembourse_eur)                 AS montant_rembourse_eur,
       count(*) FILTER (WHERE f.montant_rembourse_eur > 0) AS nb_ventes_remboursees,
       count(*) FILTER (WHERE f.est_abonnement)     AS nb_ventes_abonnement
FROM fait_transactions f
JOIN dim_date d ON d.date_cle = f.date_cle
WHERE f.statut <> 'echouee'
GROUP BY d.annee, d.mois, f.produit_cle;

CREATE UNIQUE INDEX uq_mv_produits ON mv_performance_produits_mensuelle (annee, mois, produit_cle);

-- Segmentation RFM : récence, fréquence et montant net, notés de 1 à 5 par quintiles
CREATE MATERIALIZED VIEW mv_segmentation_rfm AS
WITH base AS (
    SELECT f.client_cle,
           max(d.date_complete)                       AS dernier_achat,
           count(*)                                   AS frequence,
           sum(f.montant_eur - f.montant_rembourse_eur) AS montant_net_eur
    FROM fait_transactions f
    JOIN dim_date d ON d.date_cle = f.date_cle
    WHERE f.statut <> 'echouee'
    GROUP BY f.client_cle
),
notes AS (
    SELECT client_cle,
           dernier_achat,
           current_date - dernier_achat               AS recence_jours,
           frequence,
           montant_net_eur,
           ntile(5) OVER (ORDER BY dernier_achat)     AS note_r,
           ntile(5) OVER (ORDER BY frequence)         AS note_f,
           ntile(5) OVER (ORDER BY montant_net_eur)   AS note_m
    FROM base
)
SELECT client_cle,
       dernier_achat,
       recence_jours,
       frequence,
       montant_net_eur,
       note_r,
       note_f,
       note_m,
       CASE
           WHEN note_r >= 4 AND note_f >= 4 AND note_m >= 4 THEN 'Champions'
           WHEN note_r >= 3 AND note_f >= 3                 THEN 'Fidèles'
           WHEN note_r >= 4 AND note_f <= 2                 THEN 'Nouveaux'
           WHEN note_r <= 2 AND note_f >= 3                 THEN 'À risque'
           WHEN note_r <= 2                                 THEN 'Inactifs'
           ELSE 'À développer'
       END AS segment
FROM notes;

CREATE UNIQUE INDEX uq_mv_rfm ON mv_segmentation_rfm (client_cle);
CREATE INDEX idx_mv_rfm_segment ON mv_segmentation_rfm (segment);

COMMENT ON MATERIALIZED VIEW mv_fraude_quotidienne_pays        IS 'Indicateurs de fraude par jour et par pays de l''adresse IP';
COMMENT ON MATERIALIZED VIEW mv_performance_produits_mensuelle IS 'Ventes, chiffre d''affaires et remboursements par produit et par mois';
COMMENT ON MATERIALIZED VIEW mv_segmentation_rfm               IS 'Segmentation des clients par récence, fréquence et montant (RFM)';
