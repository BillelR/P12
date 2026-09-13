-- ============================================================================
-- Schéma de base de données - Projet "Avantages Sportifs" (Sport Data Solution)
-- ============================================================================
-- À exécuter dans Supabase : Database > SQL Editor > New query > coller > Run

-- ----------------------------------------------------------------------------
-- Table 1 : salaries
-- Source : Données RH (161 salariés)
-- ----------------------------------------------------------------------------
CREATE TABLE salaries (
    id_salarie          INTEGER PRIMARY KEY,
    nom                 TEXT NOT NULL,
    prenom              TEXT NOT NULL,
    date_naissance      DATE,
    bu                  TEXT,              -- Business Unit (Marketing, R&D, Ventes, Support, Finance...)
    type_contrat        TEXT,              -- CDI, CDD...
    date_embauche       DATE,
    salaire_annuel      NUMERIC(10, 2),
    jours_cp            INTEGER,
    adresse_domicile    TEXT,
    moyen_deplacement   TEXT,              -- Transports en commun, Véhicule, Marche/running, Vélo/Trottinette...
    created_at          TIMESTAMPTZ DEFAULT now()
);

-- ----------------------------------------------------------------------------
-- Table 2 : sports_pratiques
-- Source : Données Sportives brutes (sport déclaré par salarié)
-- ----------------------------------------------------------------------------
CREATE TABLE sports_pratiques (
    id_salarie   INTEGER PRIMARY KEY REFERENCES salaries(id_salarie),
    sport        TEXT,   -- NULL si le salarié ne pratique aucun sport
    created_at   TIMESTAMPTZ DEFAULT now()
);

-- ----------------------------------------------------------------------------
-- Table 3 : activites_sportives
-- Source : données générées (façon Strava), fenêtre glissante 12 mois
-- ----------------------------------------------------------------------------
CREATE TABLE activites_sportives (
    id_activite           SERIAL PRIMARY KEY,
    id_salarie            INTEGER REFERENCES salaries(id_salarie),
    date_debut_activite   TIMESTAMP NOT NULL,
    sport                 TEXT NOT NULL,
    distance_m            INTEGER,           -- en mètres, NULL si non pertinent (ex: escalade)
    date_fin_activite     TIMESTAMP NOT NULL,
    commentaire           TEXT,              -- commentaire optionnel façon Strava
    created_at            TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_activites_salarie ON activites_sportives(id_salarie);
CREATE INDEX idx_activites_date ON activites_sportives(date_debut_activite);

-- ----------------------------------------------------------------------------
-- Table 4 : trajets_domicile_travail
-- Résultat du calcul via l'API Google Maps (Distance Matrix)
-- ----------------------------------------------------------------------------
CREATE TABLE trajets_domicile_travail (
    id_trajet             SERIAL PRIMARY KEY,
    id_salarie            INTEGER REFERENCES salaries(id_salarie),
    mode_transport        TEXT NOT NULL,     -- walking, bicycling
    distance_km           NUMERIC(6, 2),
    duree_estimee_min     INTEGER,
    distance_eligible     BOOLEAN,           -- <=15km marche/course, <=25km vélo/autre
    date_calcul           TIMESTAMPTZ DEFAULT now()
);

-- ----------------------------------------------------------------------------
-- Table 5 : eligibilite_avantages
-- Table de résultats consolidés (calculée par l'ETL), utilisée par Power BI
-- ----------------------------------------------------------------------------
CREATE TABLE eligibilite_avantages (
    id_salarie                  INTEGER PRIMARY KEY REFERENCES salaries(id_salarie),
    eligible_prime_mobilite     BOOLEAN DEFAULT FALSE,   -- prime 5% salaire
    distance_trajet_km          NUMERIC(6, 2),
    mode_transport_retenu       TEXT,
    nb_activites_12_mois        INTEGER DEFAULT 0,
    eligible_jours_bien_etre    BOOLEAN DEFAULT FALSE,   -- >=15 activités/an -> 5 jours
    date_calcul                 TIMESTAMPTZ DEFAULT now()
);

-- ----------------------------------------------------------------------------
-- Table 6 : logs_monitoring
-- Table de logs pour le suivi qualité / exécution du pipeline (+ alertes Slack)
-- ----------------------------------------------------------------------------
CREATE TABLE logs_monitoring (
    id_log              SERIAL PRIMARY KEY,
    horodatage          TIMESTAMPTZ DEFAULT now(),
    niveau              TEXT NOT NULL,      -- INFO, WARNING, ERROR
    etape               TEXT NOT NULL,      -- ex: "generation_donnees", "etl_load", "quality_check"
    message              TEXT NOT NULL,
    nb_lignes_traitees   INTEGER,
    duree_secondes       NUMERIC(8, 2)
);

CREATE INDEX idx_logs_horodatage ON logs_monitoring(horodatage);
CREATE INDEX idx_logs_niveau ON logs_monitoring(niveau);
