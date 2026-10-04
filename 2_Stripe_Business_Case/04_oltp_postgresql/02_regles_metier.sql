-- Base transactionnelle (OLTP) - Stripe Business Case
-- Règles métier appliquées par déclencheurs (triggers)

-- Mise à jour automatique de la date de dernière modification des transactions

CREATE FUNCTION fn_maj_date_transaction() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.date_maj := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_transactions_date_maj
    BEFORE UPDATE ON transactions
    FOR EACH ROW EXECUTE FUNCTION fn_maj_date_transaction();

-- Cohérence entre un paiement d'abonnement et le produit souscrit
-- Le produit est déduit de l'abonnement s'il n'est pas renseigné ; toute contradiction est refusée

CREATE FUNCTION fn_controle_abonnement() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_produit UUID;
BEGIN
    IF NEW.abonnement_id IS NOT NULL THEN
        SELECT produit_id INTO v_produit FROM abonnements WHERE abonnement_id = NEW.abonnement_id;
        IF NEW.produit_id IS NULL THEN
            NEW.produit_id := v_produit;
        ELSIF NEW.produit_id <> v_produit THEN
            RAISE EXCEPTION 'Produit % incohérent avec l''abonnement % (produit attendu : %)',
                NEW.produit_id, NEW.abonnement_id, v_produit;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_transactions_abonnement
    BEFORE INSERT OR UPDATE OF abonnement_id, produit_id ON transactions
    FOR EACH ROW EXECUTE FUNCTION fn_controle_abonnement();

-- Remboursements : uniquement sur un paiement réussi, cumul plafonné au montant payé,
-- passage au statut « remboursee » lorsque le remboursement est total

CREATE FUNCTION fn_controle_remboursement() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_statut  TEXT;
    v_montant NUMERIC(12,2);
    v_cumul   NUMERIC(12,2);
BEGIN
    SELECT statut, montant INTO v_statut, v_montant
    FROM transactions WHERE transaction_id = NEW.transaction_id
    FOR UPDATE;

    IF v_statut <> 'reussie' THEN
        RAISE EXCEPTION 'Remboursement refusé : la transaction % a le statut %', NEW.transaction_id, v_statut;
    END IF;

    SELECT COALESCE(SUM(montant), 0) INTO v_cumul
    FROM remboursements WHERE transaction_id = NEW.transaction_id;

    IF v_cumul > v_montant THEN
        RAISE EXCEPTION 'Remboursement refusé : cumul % supérieur au montant payé %', v_cumul, v_montant;
    END IF;

    IF v_cumul = v_montant THEN
        UPDATE transactions SET statut = 'remboursee' WHERE transaction_id = NEW.transaction_id;
    END IF;

    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_remboursements_controle
    AFTER INSERT ON remboursements
    FOR EACH ROW EXECUTE FUNCTION fn_controle_remboursement();

-- Litiges : uniquement sur un paiement réussi ; la transaction passe au statut « contestee »

CREATE FUNCTION fn_controle_litige() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_statut TEXT;
BEGIN
    SELECT statut INTO v_statut
    FROM transactions WHERE transaction_id = NEW.transaction_id
    FOR UPDATE;

    IF v_statut <> 'reussie' THEN
        RAISE EXCEPTION 'Litige refusé : la transaction % a le statut %', NEW.transaction_id, v_statut;
    END IF;

    UPDATE transactions SET statut = 'contestee' WHERE transaction_id = NEW.transaction_id;
    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_litiges_controle
    AFTER INSERT ON litiges
    FOR EACH ROW EXECUTE FUNCTION fn_controle_litige();

-- Enregistrements financiers et journal d'audit non modifiables

CREATE FUNCTION fn_interdire_modification() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Opération % interdite sur la table % : enregistrements non modifiables', TG_OP, TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER trg_remboursements_immuables
    BEFORE UPDATE OR DELETE ON remboursements
    FOR EACH ROW EXECUTE FUNCTION fn_interdire_modification();

CREATE TRIGGER trg_journal_audit_immuable
    BEFORE UPDATE OR DELETE ON journal_audit
    FOR EACH ROW EXECUTE FUNCTION fn_interdire_modification();

-- Journal d'audit : trace de toute insertion, modification ou suppression sur les tables sensibles
-- SECURITY DEFINER : l'écriture dans le journal ne dépend pas des droits de l'utilisateur à l'origine de l'action

CREATE FUNCTION fn_journaliser() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_cle TEXT := TG_ARGV[0];
BEGIN
    INSERT INTO journal_audit (table_cible, operation, identifiant_ligne, utilisateur_bd,
                               anciennes_valeurs, nouvelles_valeurs)
    VALUES (
        TG_TABLE_NAME,
        TG_OP,
        CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ->> v_cle ELSE to_jsonb(NEW) ->> v_cle END,
        session_user,
        CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN to_jsonb(OLD) END,
        CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN to_jsonb(NEW) END
    );
    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_audit_marchands       AFTER INSERT OR UPDATE OR DELETE ON marchands       FOR EACH ROW EXECUTE FUNCTION fn_journaliser('marchand_id');
CREATE TRIGGER trg_audit_clients         AFTER INSERT OR UPDATE OR DELETE ON clients         FOR EACH ROW EXECUTE FUNCTION fn_journaliser('client_id');
CREATE TRIGGER trg_audit_moyens_paiement AFTER INSERT OR UPDATE OR DELETE ON moyens_paiement FOR EACH ROW EXECUTE FUNCTION fn_journaliser('moyen_paiement_id');
CREATE TRIGGER trg_audit_abonnements     AFTER INSERT OR UPDATE OR DELETE ON abonnements     FOR EACH ROW EXECUTE FUNCTION fn_journaliser('abonnement_id');
CREATE TRIGGER trg_audit_transactions    AFTER INSERT OR UPDATE OR DELETE ON transactions    FOR EACH ROW EXECUTE FUNCTION fn_journaliser('transaction_id');
CREATE TRIGGER trg_audit_remboursements  AFTER INSERT OR UPDATE OR DELETE ON remboursements  FOR EACH ROW EXECUTE FUNCTION fn_journaliser('remboursement_id');
CREATE TRIGGER trg_audit_litiges         AFTER INSERT OR UPDATE OR DELETE ON litiges         FOR EACH ROW EXECUTE FUNCTION fn_journaliser('litige_id');
