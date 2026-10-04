-- Requêtes métier - Base transactionnelle (OLTP) - Stripe Business Case
--
-- Requêtes opérationnelles (service client, surveillance des marchands, audit) : elles portent
-- sur peu de lignes, accédées par index, dans le modèle normalisé.
-- Paramètres facultatifs (variables psql) : client_id, transaction_id ; à défaut, un exemple
-- représentatif est choisi automatiquement. Requête transverse aux trois bases : fichiers 04_*.

\pset null '-'

-- Q8. Derniers paiements d'un client, avec remboursements cumulés et litige éventuel
-- Exemple par défaut : le client le plus actif
\if :{?client_id}
\else
SELECT client_id::text AS client_id FROM transactions GROUP BY client_id ORDER BY count(*) DESC LIMIT 1 \gset
\endif
\echo '\n=== Q8. Dix derniers paiements du client' :client_id
SELECT t.date_heure,
       m.raison_sociale                     AS marchand,
       t.montant,
       t.code_devise,
       t.statut,
       t.score_anomalie,
       COALESCE(sum(r.montant), 0)          AS rembourse,
       l.motif                              AS motif_litige
FROM transactions t
JOIN marchands m           ON m.marchand_id = t.marchand_id
LEFT JOIN remboursements r ON r.transaction_id = t.transaction_id
LEFT JOIN litiges l        ON l.transaction_id = t.transaction_id
WHERE t.client_id = :'client_id'
GROUP BY t.transaction_id, m.raison_sociale, l.motif
ORDER BY t.date_heure DESC
LIMIT 10;

-- Q9. Marchands au taux de litige anormal sur les 30 derniers jours
-- Seuil de surveillance interne : 1 % des paiements réussis ; minimum de 20 paiements
\echo '\n=== Q9. Taux de litige par marchand (30 derniers jours, seuil de surveillance 1 %)'
SELECT m.raison_sociale                                                             AS marchand,
       m.categorie,
       count(*)                                                                     AS paiements,
       count(l.litige_id)                                                           AS litiges,
       round(100.0 * count(l.litige_id) / count(*), 2)                              AS taux_litige_pct,
       CASE WHEN 100.0 * count(l.litige_id) / count(*) > 1 THEN 'à surveiller' ELSE 'normal' END AS alerte
FROM transactions t
JOIN marchands m     ON m.marchand_id = t.marchand_id
LEFT JOIN litiges l  ON l.transaction_id = t.transaction_id
WHERE t.date_heure >= now() - interval '30 days'
  AND t.statut <> 'echouee'
GROUP BY m.raison_sociale, m.categorie
HAVING count(*) >= 20
ORDER BY taux_litige_pct DESC
LIMIT 10;

-- Q10. Historique des actions sur un paiement : qui, quand, quoi (journal d'audit)
-- Exemple par défaut : le dernier paiement ayant fait l'objet d'une modification
\if :{?transaction_id}
\else
SELECT identifiant_ligne AS transaction_id FROM journal_audit
WHERE table_cible = 'transactions' AND operation = 'UPDATE' ORDER BY audit_id DESC LIMIT 1 \gset
\endif
\echo '\n=== Q10. Journal d''audit du paiement' :transaction_id
SELECT date_action,
       operation,
       utilisateur_bd                                     AS compte,
       anciennes_valeurs ->> 'statut'                     AS ancien_statut,
       nouvelles_valeurs ->> 'statut'                     AS nouveau_statut,
       anciennes_valeurs ->> 'score_anomalie'             AS ancien_score,
       nouvelles_valeurs ->> 'score_anomalie'             AS nouveau_score
FROM journal_audit
WHERE table_cible = 'transactions' AND identifiant_ligne = :'transaction_id'
ORDER BY audit_id;
