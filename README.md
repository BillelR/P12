# Sport Data Solution — POC "Avantages Sportifs"

POC pour un programme d'avantages sportifs en entreprise :
- **Prime de mobilité** (5% du salaire) pour les salariés venant au travail en mode actif
  (marche/course ≤15km, vélo/trottinette ≤25km), vérifiée via l'API Google Maps.
- **5 jours "bien-être"** pour les salariés ayant pratiqué ≥15 activités sportives sur les
  12 derniers mois glissants (données simulées façon Strava).

## Architecture

| Étape | Outil |
|---|---|
| Infra | Supabase (PostgreSQL cloud) |
| Génération de données | Python |
| ETL | Python / pandas / SQLAlchemy |
| Calcul distances | API Google Maps (Distance Matrix) |
| Monitoring | Table `logs_monitoring` + alertes Slack (webhook) |
| Reporting | Power BI Service |

## Installation

### 1. Prérequis
- Python 3.10+
- Un projet Supabase déjà créé, avec `sql/schema.sql` déjà exécuté (SQL Editor > coller > Run)
- Une clé API Google Maps avec la Distance Matrix API activée
- (Optionnel) Un webhook Slack pour les alertes de monitoring

### 2. Installer les dépendances

```bash
pip install -r requirements.txt --break-system-packages
```

### 3. Configurer les secrets

```bash
cp .env.example .env
```

Puis édite `.env` et renseigne :
- `SUPABASE_DB_URL` : ta connection string PostgreSQL (Supabase > Settings > Database > Connection string > Direct)
- `GOOGLE_MAPS_API_KEY` : ta clé API Google Maps
- `SLACK_WEBHOOK_URL` : ton webhook Slack (optionnel)

⚠️ Le fichier `.env` n'est **jamais** commité (voir `.gitignore`).

### 4. Vérifier l'adresse de l'entreprise

Dans `src/google_maps_client.py`, la constante `ADRESSE_ENTREPRISE` définit le lieu de
travail utilisé pour calculer les distances. Ajuste-la si besoin.

## Utilisation

### Étape 1 — Générer les activités sportives simulées

```bash
python src/generate_activities.py
```

Génère `data/generated/activites_sportives_generees.csv` (~1300 activités simulées avec
Faker, sur une fenêtre glissante de 12 mois, calibrées pour obtenir un mix réaliste de
salariés éligibles/non-éligibles au seuil de 15 activités/an).

### Étape 2 — Contrôler la qualité des données

```bash
python src/quality_checks.py
```

Exécute 13 contrôles Great Expectations (unicité des ID, plages de valeurs plausibles,
cohérence des dates...). Retourne un code d'erreur si un contrôle critique échoue —
bloque le pipeline avant tout chargement en base.

### Étape 3 — Lancer le pipeline ETL complet

```bash
python src/etl.py
```

Ce script :
1. Vide les tables Supabase (idempotence)
2. Charge les données RH, sportives et les activités générées
3. Calcule les trajets domicile-travail via Google Maps
4. Calcule la table d'éligibilité consolidée (`eligibilite_avantages`)
5. Log chaque étape dans `logs_monitoring` et envoie une alerte Slack en fin de run

### Étape 4 (optionnel) — CDC en temps réel avec Debezium + Redis

Démontre la capture des changements sur `salaries` et `eligibilite_avantages` en
temps réel, directement depuis le WAL de PostgreSQL (Supabase).

**4.1 — Préparer Supabase** (une seule fois) :

Dans le SQL Editor Supabase, exécute :
```sql
CREATE PUBLICATION dbz_publication FOR TABLE salaries, eligibilite_avantages;
```

**4.2 — Compléter la config Debezium** :

Édite `debezium/conf/application.properties` et remplace les valeurs `CHANGE_ME`
par tes vraies informations de connexion Supabase — utilise le **Session pooler**
ou la **connexion directe** (port 5432), PAS le "Transaction pooler" (port 6543)
qui ne supporte pas la réplication logique.

**4.3 — Lancer l'infra Docker** :

```bash
docker compose up -d redis debezium-server
docker compose logs -f debezium-server   # vérifier que la capture démarre sans erreur
```

**4.4 — Lancer le consommateur CDC** (dans un terminal séparé) :

```bash
python src/cdc_consumer.py
```

**4.5 — Démonstration live** : modifie une ligne dans la table `salaries` ou
`eligibilite_avantages` depuis le Table Editor Supabase → le changement apparaît
quasi instantanément dans le terminal du consommateur, et une alerte Slack part
automatiquement pour les changements d'éligibilité.

### Étape 5 (optionnel) — Orchestration complète avec Kestra

```bash
docker compose up -d kestra
```

Ouvre `http://localhost:8080` dans le navigateur, va dans **Flows**, tu devrais voir
le flow `sportdata.pipeline_sport_data` déjà chargé (monté depuis `kestra/flows/`).
Clique sur **Execute** pour lancer manuellement l'enchaînement complet
(génération → contrôle qualité → ETL), chaque étape tournant dans un conteneur
Python isolé.

⚠️ Chaque tâche réinstalle les dépendances à chaque exécution (`pip install` inline) —
c'est volontairement simplifié pour ce POC. En production, on construirait une image
Docker dédiée avec les dépendances déjà installées, pour des exécutions plus rapides.

## Budget mémoire (VM à 4 Go de RAM)

| Composant | RAM estimée |
|---|---|
| Redis | ~100 Mo |
| Debezium Server | ~700 Mo |
| Kestra (standalone) | ~1,2 Go |
| Scripts Python (ETL, quality checks) | ~200 Mo |
| **Total infra** | **~2,2 Go** |

Reste de marge pour l'OS et le navigateur (Power BI Service), mais prévoir du swap
en filet de sécurité et fermer les applications non nécessaires pendant la démo.

## Structure du projet

```
sport-data-solution/
├── data/
│   ├── raw/                    # fichiers Excel fournis (RH, sportif)
│   └── generated/              # activités simulées générées (Faker)
├── src/
│   ├── generate_activities.py  # génération des données sportives simulées (Faker)
│   ├── quality_checks.py       # contrôles qualité (Great Expectations)
│   ├── db_utils.py             # connexion Supabase + logging + Slack
│   ├── google_maps_client.py   # calcul des distances domicile-travail
│   ├── cdc_consumer.py         # consommateur des événements CDC (Redis)
│   └── etl.py                  # pipeline principal (orchestration)
├── sql/
│   └── schema.sql              # schéma des 6 tables Supabase
├── debezium/
│   └── conf/application.properties  # config CDC (source Supabase, sink Redis)
├── kestra/
│   └── flows/pipeline_sport_data.yml  # orchestration du pipeline complet
├── docs/
│   └── RGPD.md                 # cadrage conformité RGPD
├── docker-compose.yml          # infra Redis + Debezium Server + Kestra
├── .env.example                # template de configuration (sans secrets)
├── .gitignore
├── requirements.txt
└── README.md
```

## Schéma de données

- **salaries** : données RH (161 salariés)
- **sports_pratiques** : sport déclaré par salarié (donnée brute fournie)
- **activites_sportives** : historique d'activités simulé (façon Strava)
- **trajets_domicile_travail** : résultats des calculs Google Maps
- **eligibilite_avantages** : table consolidée utilisée par Power BI
- **logs_monitoring** : logs d'exécution du pipeline (niveau, étape, message, durée)

## Limites connues / axes d'amélioration

- Le fichier "Données Sportives" fourni ne contenait qu'une ligne par salarié (le sport
  pratiqué), sans historique d'activités : celui-ci a donc été simulé statistiquement
  (processus de Poisson par sport, avec variabilité individuelle d'assiduité, via Faker).
- La stack Debezium/Kestra a été calibrée pour une VM à 4 Go de RAM (sink Redis plutôt
  que Kafka, Kestra en mode standalone H2). En production à plus grande échelle, une
  vraie infrastructure Kafka apporterait une meilleure durabilité et un rejeu des
  événements plus robuste.
- Les tâches Kestra réinstallent leurs dépendances Python à chaque exécution (image
  générique `python:3.12-slim`) ; une image Docker dédiée pré-construite accélérerait
  les exécutions en production.
- Grafana n'a pas été retenu pour le monitoring : Power BI couvre déjà ce besoin
  (reporting business + page de suivi qualité/exécution), évitant la redondance de deux
  outils de dashboard pour un même périmètre.
