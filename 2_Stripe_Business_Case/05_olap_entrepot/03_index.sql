-- Entrepôt analytique (OLAP) - Stripe Business Case
-- Index des clés de dimension de la table de faits (déclinés automatiquement sur chaque partition)

CREATE INDEX idx_fait_client     ON fait_transactions (client_cle);
CREATE INDEX idx_fait_marchand   ON fait_transactions (marchand_cle, date_cle);
CREATE INDEX idx_fait_produit    ON fait_transactions (produit_cle);
CREATE INDEX idx_fait_geographie ON fait_transactions (geographie_ip_cle, date_cle);
CREATE INDEX idx_fait_suspectes  ON fait_transactions (date_cle) WHERE score_anomalie >= 0.8;

CREATE INDEX idx_audit_date      ON fait_audit (date_cle);
CREATE INDEX idx_audit_table     ON fait_audit (table_cible, operation);
