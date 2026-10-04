-- Entrepôt analytique (OLAP) - Stripe Business Case
-- Suivi des chargements incrémentaux : dernière valeur traitée par flux (« filigrane »)
-- Chaque exécution ne relit dans la base OLTP que les lignes postérieures à ce filigrane

CREATE TABLE suivi_chargements (
    flux             TEXT        PRIMARY KEY,
    derniere_valeur  TEXT        NOT NULL,
    nb_lignes        INT         NOT NULL,
    date_execution   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE suivi_chargements IS 'Filigrane du chargement incrémental de chaque flux (dernière date de modification ou dernier identifiant traité)';
