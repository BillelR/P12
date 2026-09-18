# Sport Data Solution — POC "Avantages Sportifs"

POC technique pour un programme d'avantages sportifs en entreprise, réalisé dans le cadre
du Projet 13 (parcours Data Engineer). Répond à la note de cadrage fournie : tester la
faisabilité technique, déterminer les données nécessaires, et calculer l'impact financier
sur l'entreprise des avantages proposés.

**Dépôt GitHub : https://github.com/BillelR/P12**

## Les deux avantages simulés

- **Prime de mobilité** (5% du salaire annuel brut) pour les salariés venant au travail en
  mode actif (marche/course ≤ 15 km, vélo/trottinette/autres ≤ 25 km), vérifié
  automatiquement via l'API Google Maps (Distance Matrix) à partir de l'adresse déclarée
  et de l'adresse de l'entreprise (1362 Av. des Platanes, 34970 Lattes).
- **5 jours "bien-être"** pour les salariés ayant pratiqué au moins 15 activités sportives
  sur les 12 derniers mois glissants (données simulées façon Strava, en l'absence
  d'intégration réelle à ce stade du POC).

## Résultats obtenus (dernier run)

| Indicateur | Valeur |
|---|---|
| Salariés éligibles à la prime mobilité | 68 / 161 (42,2%) |
| Salariés éligibles aux jours bien-être | 87 / 161 (54,0%) |
| Coût total de la prime | ≈ 172 480 € |
| Budget de référence communiqué | 172 000 € (écart de 0,28%) |
| Jours bien-être accordés au total | 435 |

## Architecture

| Étape | Outil |
|---|---|
| Stockage principal | Supabase (PostgreSQL cloud) |
| Génération de données simulées | Python + Faker |
| ETL | Python / pandas / SQLAlchemy |
| Calcul de distances | API Google Maps (Distance Matrix) |
| Détection d'anomalies | Règle métier (écart déclaration/distance réelle) |
| Tests de cohérence des données | Great Expectations |
| Tests unitaires | pytest |
| Change Data Capture (temps réel) | Debezium Server + Neon PostgreSQL + Redis Streams |
| Orchestration | Kestra (Docker) |
| Notifications | Slack (webhook) |
| Reporting | Power BI Desktop |

### Pourquoi Neon en plus de Supabase pour le CDC ?

Supabase réserve sa connexion directe (nécessaire pour la réplication logique PostgreSQL
utilisée par Debezium) à un add-on payant sur son offre gratuite — sa connexion "pooler"
gratuite ne supporte pas ce protocole. **Neon**, un service PostgreSQL serverless
équivalent, supporte nativement la réplication logique gratuitement. Le stockage principal
du projet reste Supabase ; Neon héberge uniquement une base de démonstration simplifiée
pour illustrer le mécanisme de CDC (capture des nouvelles activités sportives en temps
réel, déclenchement de messages de félicitation Slack).

### Pourquoi Redis plutôt que Kafka ?

L'architecture cible suggérée dans la note de cadrage utilise Kafka (Redpanda) et Spark.
Pour ce POC, exécuté sur une VM à ressources limitées, Redis Streams a été retenu comme
sink Debezium : il est officiellement supporté par Debezium Server, très léger (~100 Mo
contre plusieurs Go pour un cluster Kafka), et suffisant pour démontrer le principe du CDC
à cette échelle. Une migration vers Kafka serait recommandée en production à plus grande
échelle.

## Installation

### 1. Prérequis
- Python 3.10+
- Docker et Docker Compose (pour Debezium, Redis, Kestra)
- Un projet Supabase (stockage principal)
- Un projet Neon (démo CDC) avec la réplication logique activée
- Une clé API Google Maps avec la **Distance Matrix API activée** (pas seulement
  autorisée dans les restrictions de la clé — l'API doit aussi être activée au niveau
  du projet Google Cloud, dans APIs & Services > Library)
- Un webhook Slack (Incoming Webhook)

### 2. Installer les dépendances

```bash
pip install -r requirements.txt --break-system-packages
```

### 3. Configurer les secrets

```bash
cp .env.example .env
```

Édite `.env` et renseigne :
- `SUPABASE_DB_URL` : connection string PostgreSQL Supabase, via le **pooler** (Settings
  > Database > Connection string), port 5432
- `GOOGLE_MAPS_API_KEY` : ta clé API Google Maps
- `SLACK_WEBHOOK_URL` : ton URL de webhook Slack

⚠️ Le fichier `.env` n'est **jamais** commité (voir `.gitignore`), de même que
`debezium/conf/application.properties` et `kestra/flows/pipeline_sport_data.yml` une fois
remplis avec de vraies valeurs (utiliser les fichiers `.example` fournis comme modèles).

### 4. Adresse de l'entreprise

Définie dans `src/google_maps_client.py` (`ADRESSE_ENTREPRISE`), conforme à la note de
cadrage : `1362 Av. des Platanes, 34970 Lattes`.

## Utilisation

### Étape 1 — Générer les activités sportives simulées

```bash
python src/generate_activities.py
```

Génère `data/generated/activites_sportives_generees.csv` : plusieurs milliers de lignes
(~3800), sur une fenêtre glissante de 12 mois, avec les métadonnées demandées dans la note
de cadrage (ID, ID salarié, date de début, type, distance en mètres, date de fin,
commentaire optionnel).

### Étape 2 — Contrôler la qualité des données

```bash
python src/quality_checks.py
```

14 contrôles Great Expectations (cohérence des ID, dates, distances non négatives...).
Retourne un code d'erreur en cas d'échec critique, bloquant le pipeline avant chargement.

### Étape 3 — Lancer le pipeline ETL complet

```bash
python src/etl.py
```

1. Vide les tables Supabase (idempotence)
2. Charge les données RH, sportives et les activités générées
3. Calcule les trajets domicile-travail via Google Maps
4. **Détecte les anomalies de déclaration** (ex : salarié déclarant venir à pied en
   habitant à plus de 30 km — 2× le seuil légal de 15 km) et alerte sur Slack
5. Calcule la table d'éligibilité consolidée et le coût du programme
6. Log chaque étape dans `logs_monitoring`, alerte Slack en fin de run

### Étape 4 — Exécuter les tests

```bash
python -m pytest
```

36 tests unitaires couvrant : seuils d'éligibilité Google Maps, détection d'anomalies,
calcul d'éligibilité (cas limites), parsing des événements CDC, génération de données.

### Étape 5 (optionnel) — CDC en temps réel avec Debezium + Redis

Démontre la capture des changements sur Neon en temps réel, avec messages de félicitation
automatiques façon Strava (conformes à l'exemple de la note de cadrage).

**5.1 — Activer la réplication logique sur Neon**, puis créer la publication :
```sql
CREATE PUBLICATION dbz_publication FOR TABLE salaries, eligibilite_avantages, activites_sportives;
```

**5.2 — Compléter `debezium/conf/application.properties`** avec les identifiants Neon
(connexion directe, pas de pooler).

**5.3 — Lancer l'infra :**
```bash
docker compose up -d redis debezium-server
```

**5.4 — Lancer le consommateur** (terminal séparé) :
```bash
python src/cdc_consumer.py
```

**5.5 — Démonstration** : insère une activité dans Neon —
```sql
INSERT INTO activites_sportives (id_salarie, sport, duree_minutes, distance_km)
VALUES (1, 'Runing', 46, 10.8);
```
— le message `🎉 Bravo ... ! Tu viens de courir 10.8 km en 46 min !` apparaît en quelques
secondes dans le terminal et sur Slack.

### Étape 6 (optionnel) — Orchestration complète avec Kestra

```bash
docker compose up -d kestra
```

Ouvre `http://localhost:8080`, crée un compte admin local, importe
`kestra/flows/pipeline_sport_data.yml` (après y avoir renseigné tes clés), puis exécute le
flow `pipeline_sport_data` — génération, contrôle qualité et ETL s'enchaînent dans un
conteneur Docker dédié (image construite via `docker build -t sport-data-pipeline:latest .`).

## Dashboard Power BI

Fichier : `Rabouz_Billel_dashboard_avantages_sportifs.pbix` (Power BI Desktop, connexion
directe à Supabase via connecteur PostgreSQL).

**Page 1 — Vue d'ensemble** : KPIs (effectif, % éligibles), répartition par mode de
déplacement, coût total de la prime vs budget de référence (172 000 €, valeur communiquée
par le mentor du projet), jours bien-être accordés.

**Page 2 — Détail par salarié** : tableau nominatif complet, répartition des éligibilités
par BU.

**Page 3 — Monitoring pipeline** : historique des exécutions (table `logs_monitoring`),
répartition des logs par niveau (INFO/WARNING/ERROR).

## Structure du projet

```
sport-data-solution/
├── data/
│   ├── raw/                    # fichiers Excel fournis (RH, sportif) — données fictives
│   └── generated/              # activités simulées générées (Faker)
├── src/
│   ├── generate_activities.py  # génération des données sportives simulées
│   ├── quality_checks.py       # contrôles qualité (Great Expectations)
│   ├── db_utils.py             # connexion Supabase + logging + Slack
│   ├── google_maps_client.py   # calcul distances + détection d'anomalies
│   ├── cdc_consumer.py         # consommateur CDC (Redis) + messages de félicitation
│   └── etl.py                  # pipeline principal (orchestration)
├── tests/                      # tests unitaires pytest (36 tests)
├── sql/
│   ├── schema.sql                    # schéma des 6 tables Supabase
│   └── schema_neon_cdc_demo.sql      # schéma simplifié pour la démo CDC (Neon)
├── debezium/conf/              # config CDC (source Neon, sink Redis)
├── kestra/flows/                # orchestration du pipeline complet
├── docs/
│   └── RGPD.md                 # cadrage conformité RGPD
├── docker-compose.yml           # infra Redis + Debezium Server + Kestra
├── Dockerfile                   # image du pipeline pour Kestra
├── Rabouz_Billel_dashboard_avantages_sportifs.pbix
├── .env.example
├── pytest.ini
├── requirements.txt
└── README.md
```

## Schéma de données (Supabase)

- **salaries** : données RH (161 salariés, données fictives)
- **sports_pratiques** : sport déclaré par salarié (donnée brute fournie)
- **activites_sportives** : historique d'activités simulé (~3800 lignes, façon Strava,
  incluant date de début/fin, distance en mètres, commentaire optionnel)
- **trajets_domicile_travail** : résultats des calculs Google Maps, avec flag
  `anomalie_declaration` pour les écarts manifestes
- **eligibilite_avantages** : table consolidée utilisée par Power BI
- **logs_monitoring** : logs d'exécution du pipeline

## Conformité RGPD

Voir `docs/RGPD.md`. Les données RH et sportives utilisées sont **fictives** (fournies
dans un cadre pédagogique) ; le cadrage RGPD documenté couvre les garanties nécessaires
pour un déploiement avec de vraies données personnelles.

## Pistes pour la montée en charge

Ce POC est dimensionné pour 161 salariés et ~3 800 activités simulées, sur une VM à
ressources limitées. Voici les points qui mériteraient d'être revus pour un déploiement à
plus grande échelle (plusieurs milliers de salariés, exécution quotidienne en continu) :

| Composant | Limite actuelle (POC) | Piste à l'échelle |
|---|---|---|
| Appels Google Maps Distance Matrix | 1 requête HTTP par salarié (jusqu'à 161 appels séquentiels, pause de 50 ms entre chacun) | Regrouper plusieurs origines par requête — l'API Distance Matrix accepte jusqu'à 25 origines × 25 destinations par appel — pour diviser le nombre de requêtes par ~25 ; remplacer la pause fixe par un budget de rate limit explicite |
| Mise en cache des distances | Recalcul systématique des 161 trajets à chaque run | Mettre en cache la distance calculée par salarié (une adresse domicile change rarement) et ne recalculer que les nouveaux salariés ou les adresses modifiées — impact direct sur le coût API et le temps d'exécution |
| Chargement Supabase | `TRUNCATE` + rechargement complet à chaque run (idempotence simple mais coûteuse) | Passer à un chargement incrémental (upsert sur `id_salarie` / clé d'activité) une fois le volume trop important pour un full reload à chaque exécution ; vérifier la présence d'index sur les clés de jointure (`id_salarie`) |
| Orchestration Kestra | Un seul flow, une tâche Docker séquentielle (génération → contrôle qualité → ETL) | Découper le flow en tâches indépendantes (extraction / qualité / trajets / chargement) pour paralléliser ce qui peut l'être et isoler les reprises sur erreur ; Kestra supporte nativement l'exécution distribuée sur plusieurs workers |
| CDC (Debezium + Redis) | Choisi pour sa légèreté sur une VM de démo (~100 Mo vs plusieurs Go pour un cluster Kafka) | Migrer vers Kafka/Redpanda (architecture cible de la note de cadrage) si le volume d'événements dépasse ce que Redis Streams peut absorber, ou si une rétention/relecture longue durée est nécessaire |
| Great Expectations | 14 contrôles exécutés sur l'intégralité du DataFrame en mémoire à chaque run | Passer à des contrôles incrémentaux (uniquement sur les nouvelles lignes) et à un moteur out-of-core (Spark/Dask) si le volume d'activités dépasse la mémoire disponible sur une seule machine |
| Monitoring | Table `logs_monitoring` interrogée directement par Power BI, sans politique de purge | Ajouter une rétention/archivage sur `logs_monitoring` pour éviter une croissance non bornée ; envisager un outil dédié (Grafana/Prometheus) si le volume de logs dépasse ce qui reste lisible dans Power BI |

Le point le plus impactant à court terme serait la mise en cache des distances Google
Maps : c'est à la fois ce qui limite le coût API (facturation au-delà du quota gratuit
mensuel) et ce qui limite le temps d'exécution du pipeline, puisque l'adresse d'un
salarié change rarement d'un run à l'autre.

## Limites connues / axes d'amélioration

- Le volume d'activités simulées (~3800) reste inférieur à un historique réel Strava sur
  161 salariés ; le générateur est calibré pour un mix réaliste d'éligibles/non-éligibles
  plutôt que pour un volume maximal.
- La stack Debezium/Kafka/Spark suggérée dans la note de cadrage a été simplifiée
  (Redis au lieu de Kafka, pas de Spark/Delta Lake) pour tenir sur une VM à ressources
  limitées ; les mêmes principes (capture WAL, streaming, notification temps réel) sont
  démontrés à plus petite échelle.
- Le budget de 172 000 € utilisé comme référence de comparaison a été communiqué de
  mémoire et n'est pas un chiffre officiel confirmé par écrit.
- Les tâches Kestra reconstruisent leurs dépendances à chaque exécution dans l'image
  Docker du pipeline ; en production, une image versionnée et pré-construite serait
  préférable.
