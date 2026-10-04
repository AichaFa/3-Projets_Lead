-- Entrepôt analytique (OLAP) - Stripe Business Case
-- Partitionnement mensuel de la table de faits des transactions
-- Une requête filtrée sur une période ne lit que les partitions concernées (élagage de partitions)

CREATE FUNCTION fn_creer_partition_mensuelle(p_mois DATE) RETURNS TEXT
LANGUAGE plpgsql AS $$
DECLARE
    v_debut DATE := date_trunc('month', p_mois)::date;
    v_fin   DATE := (date_trunc('month', p_mois) + interval '1 month')::date;
    v_nom   TEXT := format('fait_transactions_%s', to_char(v_debut, 'YYYY_MM'));
BEGIN
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF fait_transactions FOR VALUES FROM (%s) TO (%s)',
        v_nom,
        to_char(v_debut, 'YYYYMMDD')::int,
        to_char(v_fin, 'YYYYMMDD')::int
    );
    RETURN v_nom;
END;
$$;

-- Partitions de janvier 2025 à décembre 2027
DO $$
BEGIN
    PERFORM fn_creer_partition_mensuelle(m::date)
    FROM generate_series(date '2025-01-01', date '2027-12-01', interval '1 month') AS m;
END;
$$;

-- Partition par défaut : reçoit toute ligne hors des périodes prévues, sans erreur de chargement
CREATE TABLE fait_transactions_defaut PARTITION OF fait_transactions DEFAULT;
