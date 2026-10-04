-- Requête transverse (Q17), volet 3 sur 3 - Entrepôt analytique (OLAP) - Stripe Business Case
--
-- Place du paiement dans le schéma en étoile : clés de dimensions résolues, montant converti en
-- euros, score et litige recopiés par l'alimentation incrémentale (toutes les 15 minutes).
-- Paramètre obligatoire : variable psql transaction_id. Exécution possible avec le compte analyste_demo.

\pset null '-'
\echo '\n=== Q17, volet 3 : le paiement dans l''entrepôt analytique' :transaction_id
SELECT f.transaction_id, d.date_complete AS date_paiement, d.nom_jour, f.heure, m.raison_sociale AS marchand,
       m.region AS region_marchand, g.nom_pays AS pays_ip, f.statut, f.montant_origine, dv.code_devise,
       f.montant_eur, f.score_anomalie, f.a_litige, f.motif_litige, f.date_chargement
FROM fait_transactions f
JOIN dim_date d        ON d.date_cle = f.date_cle
JOIN dim_marchand m    ON m.marchand_cle = f.marchand_cle
JOIN dim_geographie g  ON g.geographie_cle = f.geographie_ip_cle
JOIN dim_devise dv     ON dv.devise_cle = f.devise_cle
WHERE f.transaction_id = :'transaction_id';
