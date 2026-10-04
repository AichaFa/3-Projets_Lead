-- Entrepôt analytique (OLAP) - Stripe Business Case
-- Données initiales : calendrier 2025-2027 et membres « inconnu » des dimensions

INSERT INTO dim_date (date_cle, date_complete, annee, trimestre, mois, nom_mois,
                      semaine_iso, jour_mois, jour_semaine, nom_jour, est_weekend)
SELECT to_char(j, 'YYYYMMDD')::int,
       j::date,
       extract(year FROM j),
       extract(quarter FROM j),
       extract(month FROM j),
       (ARRAY['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet',
              'août', 'septembre', 'octobre', 'novembre', 'décembre'])[extract(month FROM j)::int],
       extract(week FROM j),
       extract(day FROM j),
       extract(isodow FROM j),
       (ARRAY['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche'])[extract(isodow FROM j)::int],
       extract(isodow FROM j) IN (6, 7)
FROM generate_series(date '2025-01-01', date '2027-12-31', interval '1 day') AS j;

-- Membres « inconnu » (clé 0) : chargement possible des paiements sans produit ou sans pays d'IP
INSERT INTO dim_produit (produit_cle, produit_id, nom) VALUES (0, NULL, 'Sans produit');
INSERT INTO dim_geographie (geographie_cle, code_pays, nom_pays, region) VALUES (0, 'ZZ', 'Inconnu', 'Inconnue');
