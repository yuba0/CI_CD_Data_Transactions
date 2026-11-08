-- Niveau 1.3 - Schéma relationnel des résultats de traitement
-- Idempotent : peut être rejoué sans erreur (IF NOT EXISTS / OR REPLACE)

-- Registre des fichiers déjà traités : garantit qu'un CSV n'est traité qu'une fois.
CREATE TABLE IF NOT EXISTS processed_files (
    file_key      TEXT PRIMARY KEY,               -- nom du fichier / clé S3
    checksum      CHAR(64) NOT NULL UNIQUE,       -- sha256 du contenu
    row_count     INTEGER NOT NULL CHECK (row_count >= 0),
    processed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS transactions (
    id                    BIGSERIAL PRIMARY KEY,
    file_key              TEXT NOT NULL REFERENCES processed_files(file_key) ON DELETE CASCADE,
    line_number           INTEGER NOT NULL,
    datetime_transaction  TIMESTAMP NOT NULL,
    iban_origine          VARCHAR(34) NOT NULL,
    pays_source           CHAR(2) NOT NULL,
    banque_source         TEXT NOT NULL,
    iban_destinataire     VARCHAR(34) NOT NULL,
    pays_destinataire     CHAR(2) NOT NULL,
    montant               NUMERIC(14, 2) NOT NULL CHECK (montant > 0),
    is_flagged            BOOLEAN NOT NULL,
    UNIQUE (file_key, line_number)              -- 2e garde-fou anti-doublon
);

-- Agrégats calculés par fichier (résultats du traitement Python)
CREATE TABLE IF NOT EXISTS sent_by_iban (
    file_key  TEXT NOT NULL REFERENCES processed_files(file_key) ON DELETE CASCADE,
    iban      VARCHAR(34) NOT NULL,
    total     NUMERIC(14, 2) NOT NULL,
    PRIMARY KEY (file_key, iban)
);

CREATE TABLE IF NOT EXISTS sent_by_bank (
    file_key  TEXT NOT NULL REFERENCES processed_files(file_key) ON DELETE CASCADE,
    bank      TEXT NOT NULL,
    total     NUMERIC(14, 2) NOT NULL,
    PRIMARY KEY (file_key, bank)
);

CREATE TABLE IF NOT EXISTS received_by_iban (
    file_key  TEXT NOT NULL REFERENCES processed_files(file_key) ON DELETE CASCADE,
    iban      VARCHAR(34) NOT NULL,
    total     NUMERIC(14, 2) NOT NULL,
    PRIMARY KEY (file_key, iban)
);

-- Vues "tous fichiers confondus", utilisées par le dashboard et les tests
CREATE OR REPLACE VIEW v_total_sent_by_iban AS
    SELECT iban, SUM(total) AS total FROM sent_by_iban GROUP BY iban;

CREATE OR REPLACE VIEW v_total_sent_by_bank AS
    SELECT bank, SUM(total) AS total FROM sent_by_bank GROUP BY bank;

CREATE OR REPLACE VIEW v_total_received_by_iban AS
    SELECT iban, SUM(total) AS total FROM received_by_iban GROUP BY iban;

CREATE OR REPLACE VIEW v_flagged_transactions AS
    SELECT * FROM transactions WHERE is_flagged;
