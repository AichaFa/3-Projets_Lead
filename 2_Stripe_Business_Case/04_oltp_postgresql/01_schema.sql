-- Base transactionnelle (OLTP) - Stripe Business Case
-- Structure normalisée en troisième forme normale (3FN)
-- Intégrité garantie par clés primaires, clés étrangères (simples et composées) et contraintes CHECK

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Référentiels

CREATE TABLE pays (
    code_pays  CHAR(2) PRIMARY KEY CHECK (code_pays ~ '^[A-Z]{2}$'),
    nom        TEXT    NOT NULL,
    region     TEXT    NOT NULL
);

CREATE TABLE devises (
    code_devise CHAR(3) PRIMARY KEY CHECK (code_devise ~ '^[A-Z]{3}$'),
    nom         TEXT    NOT NULL
);

CREATE TABLE taux_change (
    code_devise   CHAR(3)       NOT NULL REFERENCES devises (code_devise),
    date_taux     DATE          NOT NULL,
    taux_vers_eur NUMERIC(18,8) NOT NULL CHECK (taux_vers_eur > 0),
    PRIMARY KEY (code_devise, date_taux)
);

-- Acteurs

CREATE TABLE marchands (
    marchand_id    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    raison_sociale TEXT        NOT NULL,
    code_pays      CHAR(2)     NOT NULL REFERENCES pays (code_pays),
    categorie      TEXT        NOT NULL,
    date_creation  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE clients (
    client_id     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email_chiffre BYTEA       NOT NULL,
    code_pays     CHAR(2)     NOT NULL REFERENCES pays (code_pays),
    date_creation TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE moyens_paiement (
    moyen_paiement_id UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id         UUID    NOT NULL REFERENCES clients (client_id),
    type              TEXT    NOT NULL CHECK (type IN ('carte', 'prelevement', 'portefeuille')),
    marque            TEXT,
    quatre_derniers   CHAR(4) CHECK (quatre_derniers ~ '^[0-9]{4}$'),
    jeton             TEXT    NOT NULL UNIQUE,
    CONSTRAINT uq_moyen_client UNIQUE (moyen_paiement_id, client_id),
    CONSTRAINT ck_carte_complete CHECK (type <> 'carte' OR (marque IS NOT NULL AND quatre_derniers IS NOT NULL))
);

CREATE TABLE produits (
    produit_id  UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    marchand_id UUID          NOT NULL REFERENCES marchands (marchand_id),
    nom         TEXT          NOT NULL,
    prix        NUMERIC(12,2) NOT NULL CHECK (prix > 0),
    code_devise CHAR(3)       NOT NULL REFERENCES devises (code_devise),
    CONSTRAINT uq_produit_marchand UNIQUE (produit_id, marchand_id)
);

-- Opérations

CREATE TABLE abonnements (
    abonnement_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id     UUID NOT NULL REFERENCES clients (client_id),
    produit_id    UUID NOT NULL REFERENCES produits (produit_id),
    statut        TEXT NOT NULL CHECK (statut IN ('actif', 'suspendu', 'resilie')),
    date_debut    DATE NOT NULL,
    date_fin      DATE,
    CONSTRAINT ck_dates_abonnement CHECK (date_fin IS NULL OR date_fin >= date_debut),
    CONSTRAINT uq_abonnement_client UNIQUE (abonnement_id, client_id)
);

CREATE TABLE transactions (
    transaction_id    UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    marchand_id       UUID          NOT NULL REFERENCES marchands (marchand_id),
    client_id         UUID          NOT NULL REFERENCES clients (client_id),
    moyen_paiement_id UUID          NOT NULL,
    produit_id        UUID,
    abonnement_id     UUID,
    montant           NUMERIC(12,2) NOT NULL CHECK (montant > 0),
    code_devise       CHAR(3)       NOT NULL REFERENCES devises (code_devise),
    statut            TEXT          NOT NULL CHECK (statut IN ('reussie', 'echouee', 'remboursee', 'contestee')),
    date_heure        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    adresse_ip        INET,
    pays_ip           CHAR(2)       REFERENCES pays (code_pays),
    type_appareil     TEXT          NOT NULL CHECK (type_appareil IN ('mobile', 'ordinateur', 'tablette')),
    score_anomalie    NUMERIC(5,4)  CHECK (score_anomalie BETWEEN 0 AND 1),
    date_maj          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT fk_transaction_moyen_client
        FOREIGN KEY (moyen_paiement_id, client_id) REFERENCES moyens_paiement (moyen_paiement_id, client_id),
    CONSTRAINT fk_transaction_produit_marchand
        FOREIGN KEY (produit_id, marchand_id) REFERENCES produits (produit_id, marchand_id),
    CONSTRAINT fk_transaction_abonnement_client
        FOREIGN KEY (abonnement_id, client_id) REFERENCES abonnements (abonnement_id, client_id)
);

CREATE TABLE remboursements (
    remboursement_id   UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id     UUID          NOT NULL REFERENCES transactions (transaction_id),
    montant            NUMERIC(12,2) NOT NULL CHECK (montant > 0),
    motif              TEXT          NOT NULL CHECK (motif IN ('demande_client', 'doublon', 'fraude', 'produit_non_conforme')),
    date_remboursement TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE litiges (
    litige_id      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID        NOT NULL UNIQUE REFERENCES transactions (transaction_id),
    motif          TEXT        NOT NULL CHECK (motif IN ('fraude', 'produit_non_recu', 'produit_non_conforme', 'debit_duplique', 'autre')),
    statut         TEXT        NOT NULL CHECK (statut IN ('ouvert', 'gagne', 'perdu')),
    date_ouverture TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Traçabilité

CREATE TABLE journal_audit (
    audit_id          BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    table_cible       TEXT        NOT NULL,
    operation         TEXT        NOT NULL CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE')),
    identifiant_ligne TEXT,
    utilisateur_bd    TEXT        NOT NULL DEFAULT current_user,
    date_action       TIMESTAMPTZ NOT NULL DEFAULT now(),
    anciennes_valeurs JSONB,
    nouvelles_valeurs JSONB
);

-- Dictionnaire de données

COMMENT ON TABLE pays            IS 'Référentiel des pays (ISO 3166-1 alpha-2) et de leur région commerciale';
COMMENT ON TABLE devises         IS 'Référentiel des devises (ISO 4217)';
COMMENT ON TABLE taux_change     IS 'Taux de conversion quotidiens vers l''euro';
COMMENT ON TABLE marchands       IS 'Entreprises clientes de Stripe qui encaissent des paiements';
COMMENT ON TABLE clients         IS 'Acheteurs finaux ; adresse e-mail stockée chiffrée (RGPD)';
COMMENT ON TABLE moyens_paiement IS 'Moyens de paiement tokenisés ; aucun numéro de carte complet conservé (PCI-DSS)';
COMMENT ON TABLE produits        IS 'Catalogue des produits proposés par les marchands';
COMMENT ON TABLE abonnements     IS 'Souscriptions récurrentes d''un client à un produit';
COMMENT ON TABLE transactions    IS 'Paiements traités ; table centrale de la base transactionnelle';
COMMENT ON TABLE remboursements  IS 'Remboursements totaux ou partiels ; enregistrements non modifiables';
COMMENT ON TABLE litiges         IS 'Contestations de paiement (chargebacks), au plus une par transaction';
COMMENT ON TABLE journal_audit   IS 'Journal d''audit des modifications ; enregistrements non modifiables';

COMMENT ON COLUMN moyens_paiement.jeton        IS 'Jeton de substitution du numéro de carte, émis par le coffre-fort de tokenisation';
COMMENT ON COLUMN transactions.score_anomalie  IS 'Probabilité de fraude (0 à 1) calculée par le modèle en temps réel';
COMMENT ON COLUMN transactions.date_maj        IS 'Date de dernière modification, utilisée pour le chargement incrémental de l''entrepôt';
COMMENT ON COLUMN transactions.pays_ip         IS 'Pays déduit de l''adresse IP (géolocalisation)';
