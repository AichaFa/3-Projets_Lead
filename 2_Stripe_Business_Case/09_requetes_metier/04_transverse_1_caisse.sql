-- Requête transverse (Q17), volet 1 sur 3 - Base transactionnelle (OLTP) - Stripe Business Case
--
-- Suivi d'un même paiement dans les trois bases grâce à l'identifiant commun transaction_id :
-- volet 1 (caisse) : le paiement tel qu'enregistré, avec ses références normalisées ;
-- volet 2 (NoSQL)  : sa fiche enrichie (indices, score, décision, historique des statuts) ;
-- volet 3 (entrepôt) : sa place dans le schéma en étoile (dimensions, montants convertis).
-- Paramètre obligatoire : variable psql transaction_id.

\pset null '-'
\echo '\n=== Q17, volet 1 : le paiement dans la base transactionnelle' :transaction_id
SELECT t.transaction_id, t.date_heure, m.raison_sociale AS marchand, m.categorie, c.code_pays AS pays_client,
       t.pays_ip, t.type_appareil, t.montant, t.code_devise, t.statut, t.score_anomalie,
       mp.type AS moyen_paiement, mp.marque, mp.quatre_derniers, l.motif AS motif_litige
FROM transactions t
JOIN marchands m        ON m.marchand_id = t.marchand_id
JOIN clients c          ON c.client_id = t.client_id
JOIN moyens_paiement mp ON mp.moyen_paiement_id = t.moyen_paiement_id
LEFT JOIN litiges l     ON l.transaction_id = t.transaction_id
WHERE t.transaction_id = :'transaction_id';
