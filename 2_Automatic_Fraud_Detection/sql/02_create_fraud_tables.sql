-- Tables métier de la détection de fraude, dans la base fraud.
-- Exécuté manuellement via la connexion fraud (voir sous-étape 3b).

-- Registre principal : un paiement reçu, préparé, jugé par le modèle.
CREATE TABLE IF NOT EXISTS transactions (
    id                BIGSERIAL PRIMARY KEY,
    recu_le           TIMESTAMPTZ NOT NULL DEFAULT now(),
    cc_pseudo         TEXT,
    amt               NUMERIC(12, 2),
    category          TEXT,
    gender            TEXT,
    city_pop          INTEGER,
    distance_km       DOUBLE PRECISION,
    age               DOUBLE PRECISION,
    heure             SMALLINT,
    jour_semaine      SMALLINT,
    prediction        SMALLINT NOT NULL,
    is_fraud_reel     SMALLINT,
    trans_num         TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_transactions_recu_le ON transactions (recu_le);
CREATE INDEX IF NOT EXISTS idx_transactions_prediction ON transactions (prediction);

-- Paiements écartés par le contrôle qualité, conservés pour correction.
CREATE TABLE IF NOT EXISTS quarantaine (
    id                BIGSERIAL PRIMARY KEY,
    recu_le           TIMESTAMPTZ NOT NULL DEFAULT now(),
    motif             TEXT NOT NULL,
    charge_utile      JSONB
);

-- Journal d'exécution du pipeline : une ligne par passage du DAG.
CREATE TABLE IF NOT EXISTS suivi_executions (
    id                BIGSERIAL PRIMARY KEY,
    execute_le        TIMESTAMPTZ NOT NULL DEFAULT now(),
    recus             INTEGER NOT NULL DEFAULT 0,
    valides           INTEGER NOT NULL DEFAULT 0,
    rejetes           INTEGER NOT NULL DEFAULT 0,
    fraudes_detectees INTEGER NOT NULL DEFAULT 0,
    duree_ms          INTEGER
);
