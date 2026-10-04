-- Base transactionnelle (OLTP) - Stripe Business Case
-- Index secondaires : clés étrangères et chemins d'accès les plus fréquents
-- Les clés primaires et contraintes UNIQUE disposent déjà d'un index automatique

-- Historique des paiements par marchand, par client, et repérage des modifications récentes
CREATE INDEX idx_transactions_marchand_date ON transactions (marchand_id, date_heure DESC);
CREATE INDEX idx_transactions_client_date   ON transactions (client_id, date_heure DESC);
CREATE INDEX idx_transactions_date_maj      ON transactions (date_maj);
CREATE INDEX idx_transactions_moyen         ON transactions (moyen_paiement_id);

-- Index partiels : seules les lignes concernées sont indexées
CREATE INDEX idx_transactions_produit       ON transactions (produit_id)    WHERE produit_id IS NOT NULL;
CREATE INDEX idx_transactions_abonnement    ON transactions (abonnement_id) WHERE abonnement_id IS NOT NULL;
CREATE INDEX idx_transactions_suspectes     ON transactions (score_anomalie DESC) WHERE score_anomalie >= 0.8;

CREATE INDEX idx_remboursements_transaction ON remboursements (transaction_id);
CREATE INDEX idx_moyens_paiement_client     ON moyens_paiement (client_id);
CREATE INDEX idx_produits_marchand          ON produits (marchand_id);
CREATE INDEX idx_abonnements_client         ON abonnements (client_id);
CREATE INDEX idx_abonnements_produit        ON abonnements (produit_id);
CREATE INDEX idx_journal_audit_table_date   ON journal_audit (table_cible, date_action);
