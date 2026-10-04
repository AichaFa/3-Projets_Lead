-- Base transactionnelle (OLTP) - Stripe Business Case
-- Données de référence : pays, devises et taux de change
-- Taux de change : valeurs de démonstration générées autour d'un cours de base, sur 400 jours glissants

INSERT INTO pays (code_pays, nom, region) VALUES
    ('FR', 'France',          'Europe'),
    ('DE', 'Allemagne',       'Europe'),
    ('ES', 'Espagne',         'Europe'),
    ('IT', 'Italie',          'Europe'),
    ('NL', 'Pays-Bas',        'Europe'),
    ('BE', 'Belgique',        'Europe'),
    ('IE', 'Irlande',         'Europe'),
    ('CH', 'Suisse',          'Europe'),
    ('GB', 'Royaume-Uni',     'Europe'),
    ('US', 'États-Unis',      'Amérique du Nord'),
    ('CA', 'Canada',          'Amérique du Nord'),
    ('MX', 'Mexique',         'Amérique latine'),
    ('BR', 'Brésil',          'Amérique latine'),
    ('JP', 'Japon',           'Asie-Pacifique'),
    ('SG', 'Singapour',       'Asie-Pacifique'),
    ('AU', 'Australie',       'Asie-Pacifique'),
    ('IN', 'Inde',            'Asie-Pacifique');

INSERT INTO devises (code_devise, nom) VALUES
    ('EUR', 'Euro'),
    ('USD', 'Dollar américain'),
    ('GBP', 'Livre sterling'),
    ('CHF', 'Franc suisse'),
    ('CAD', 'Dollar canadien'),
    ('MXN', 'Peso mexicain'),
    ('BRL', 'Réal brésilien'),
    ('JPY', 'Yen japonais'),
    ('SGD', 'Dollar de Singapour'),
    ('AUD', 'Dollar australien'),
    ('INR', 'Roupie indienne');

INSERT INTO taux_change (code_devise, date_taux, taux_vers_eur)
SELECT b.code_devise,
       j::date,
       CASE WHEN b.code_devise = 'EUR' THEN 1
            ELSE round((b.cours_base * (1 + 0.02 * sin(extract(doy FROM j)::double precision / 15.0)))::numeric, 8)
       END
FROM (VALUES
        ('EUR', 1.0),
        ('USD', 0.90),
        ('GBP', 1.17),
        ('CHF', 1.05),
        ('CAD', 0.66),
        ('MXN', 0.05),
        ('BRL', 0.17),
        ('JPY', 0.0061),
        ('SGD', 0.68),
        ('AUD', 0.60),
        ('INR', 0.011)
     ) AS b (code_devise, cours_base)
CROSS JOIN generate_series(current_date - 399, current_date, interval '1 day') AS j;
