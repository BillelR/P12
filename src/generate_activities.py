"""
Génération de données d'activités sportives simulées (façon Strava).

Conforme à la note de cadrage (section 5.2/5.3) :
- Historique sur les 12 derniers mois glissants
- Plusieurs milliers de lignes (~4000 visées)
- Colonnes attendues : ID, ID salarié, Date de début, Type, Distance (en
  mètres, vide si non pertinent), Date de fin, Commentaire

Le fichier "Données Sportives" fourni ne contient qu'une ligne par salarié
(le sport pratiqué), sans historique d'activités : cet historique est donc
simulé statistiquement à partir de cette déclaration, avec Faker pour les
dates, durées et commentaires.

Sortie : data/generated/activites_sportives_generees.csv
"""

import random
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

# Reproductibilité
random.seed(42)
np.random.seed(42)
fake = Faker("fr_FR")
Faker.seed(42)

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_SPORT_FILE = BASE_DIR / "data" / "raw" / "donnees_sportives.xlsx"
OUTPUT_FILE = BASE_DIR / "data" / "generated" / "activites_sportives_generees.csv"

# Fenêtre glissante de 12 mois se terminant aujourd'hui
DATE_FIN = datetime.now()
DATE_DEBUT = DATE_FIN - timedelta(days=365)

# Profil par sport. freq_annuelle_moy calibrée pour obtenir ~4000 lignes au
# total sur les 95 salariés sportifs (cf. note de cadrage : "plusieurs
# milliers de lignes").
# distance : en mètres si pertinent, sinon None (ex: escalade, cf. spec)
SPORT_PROFILES = {
    "Runing":          {"freq_annuelle_moy": 60, "duree": (25, 60),  "distance_m": (4000, 12000)},
    "Football":        {"freq_annuelle_moy": 30, "duree": (60, 90),  "distance_m": None},
    "Tennis":          {"freq_annuelle_moy": 45, "duree": (45, 90),  "distance_m": None},
    "Natation":        {"freq_annuelle_moy": 45, "duree": (30, 60),  "distance_m": (500, 2500)},
    "Randonnée":       {"freq_annuelle_moy": 24, "duree": (90, 240), "distance_m": (5000, 18000)},
    "Badminton":       {"freq_annuelle_moy": 36, "duree": (45, 75),  "distance_m": None},
    "Basketball":      {"freq_annuelle_moy": 30, "duree": (60, 90),  "distance_m": None},
    "Rugby":           {"freq_annuelle_moy": 24, "duree": (75, 105), "distance_m": None},
    "Boxe":            {"freq_annuelle_moy": 45, "duree": (45, 75),  "distance_m": None},
    "Judo":            {"freq_annuelle_moy": 36, "duree": (60, 90),  "distance_m": None},
    "Escalade":        {"freq_annuelle_moy": 24, "duree": (60, 120), "distance_m": None},
    "Équitation":      {"freq_annuelle_moy": 18, "duree": (60, 90),  "distance_m": None},
    "Voile":           {"freq_annuelle_moy": 12, "duree": (120, 240), "distance_m": None},
    "Tennis de table": {"freq_annuelle_moy": 30, "duree": (30, 60),  "distance_m": None},
    "Triathlon":       {"freq_annuelle_moy": 66, "duree": (40, 90),  "distance_m": (3000, 20000)},
}

# Variabilité individuelle d'assiduité (certains salariés sont plus réguliers
# que d'autres pour un même sport déclaré)
ASSIDUITE_MIN, ASSIDUITE_MAX = 0.4, 1.8

# Commentaires optionnels (façon export Strava), inspirés des exemples de la
# note de cadrage. Probabilité qu'une activité ait un commentaire : ~15%.
PROBA_COMMENTAIRE = 0.15
COMMENTAIRES_GENERIQUES = [
    "Reprise du sport :)",
    "Petite forme aujourd'hui",
    "Nouveau record personnel !",
    "Séance difficile mais satisfaisante",
    "Belle météo pour sortir",
    "Avec des collègues, bonne ambiance",
]
COMMENTAIRES_RANDONNEE = [
    "Un nouveau spot à découvrir !",
    "Randonnée de St Guilhem le désert, je vous la conseille c'est top",
    "Beau dénivelé aujourd'hui",
    "Vue magnifique en haut",
]


def generer_dates_activites(freq_annuelle: float) -> list:
    """Génère des dates/heures de début d'activités sur 52 semaines via un
    processus de Poisson hebdomadaire (rate = freq_annuelle / 52)."""
    rate_hebdo = freq_annuelle / 52
    dates = []
    for semaine in range(52):
        nb_activites_semaine = np.random.poisson(rate_hebdo)
        semaine_debut = DATE_DEBUT + pd.Timedelta(days=semaine * 7)
        semaine_fin = min(semaine_debut + pd.Timedelta(days=6), DATE_FIN)
        if semaine_debut > DATE_FIN:
            break
        for _ in range(nb_activites_semaine):
            jour = fake.date_between(start_date=semaine_debut.date(), end_date=semaine_fin.date())
            heure = fake.time_object(end_datetime=None)  # heure aléatoire réaliste
            date_debut = datetime.combine(jour, heure)
            dates.append(date_debut)
    return dates


def generer_commentaire(sport: str) -> str | None:
    if random.random() > PROBA_COMMENTAIRE:
        return None
    if sport == "Randonnée":
        return random.choice(COMMENTAIRES_RANDONNEE)
    return random.choice(COMMENTAIRES_GENERIQUES)


def generer_activites_pour_salarie(id_salarie: int, sport: str) -> list[dict]:
    """Génère toutes les activités d'un salarié pour son sport déclaré."""
    profil = SPORT_PROFILES[sport]
    assiduite = random.uniform(ASSIDUITE_MIN, ASSIDUITE_MAX)
    freq_annuelle_individuelle = profil["freq_annuelle_moy"] * assiduite
    dates_debut = generer_dates_activites(freq_annuelle_individuelle)

    activites = []
    for date_debut in dates_debut:
        duree_minutes = fake.random_int(*profil["duree"])
        date_fin = date_debut + timedelta(minutes=duree_minutes)

        distance_m = None
        if profil["distance_m"] is not None:
            distance_m = fake.random_int(*profil["distance_m"])

        activites.append({
            "id_salarie": id_salarie,
            "date_debut_activite": date_debut.strftime("%Y-%m-%d %H:%M:%S"),
            "sport": sport,
            "distance_m": distance_m,
            "date_fin_activite": date_fin.strftime("%Y-%m-%d %H:%M:%S"),
            "commentaire": generer_commentaire(sport),
        })

    return activites


def main():
    df_sport = pd.read_excel(RAW_SPORT_FILE)
    df_sport = df_sport.rename(columns={
        "ID salarié": "id_salarie",
        "Pratique d'un sport": "sport",
    })

    salaries_actifs = df_sport[df_sport["sport"].notna()]

    toutes_activites = []
    for _, row in salaries_actifs.iterrows():
        activites = generer_activites_pour_salarie(row["id_salarie"], row["sport"])
        toutes_activites.extend(activites)

    df_activites = pd.DataFrame(toutes_activites)
    df_activites = df_activites.sort_values(["id_salarie", "date_debut_activite"]).reset_index(drop=True)
    df_activites.insert(0, "id_activite", range(1, len(df_activites) + 1))

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    df_activites.to_csv(OUTPUT_FILE, index=False)

    print(f"Fenêtre : {DATE_DEBUT:%Y-%m-%d} -> {DATE_FIN:%Y-%m-%d}")
    print(f"Salariés actifs (avec sport déclaré) : {len(salaries_actifs)}")
    print(f"Total activités générées : {len(df_activites)}")
    print(f"Moyenne activités/salarié actif : {len(df_activites) / len(salaries_actifs):.1f}")
    print(f"\nFichier écrit : {OUTPUT_FILE}")

    print("\nRépartition par sport :")
    print(df_activites.groupby("sport").size().sort_values(ascending=False))

    compte_par_salarie = df_activites.groupby("id_salarie").size()
    nb_eligibles = (compte_par_salarie >= 15).sum()
    print(f"\nSalariés éligibles au bénéfice (>= 15 activités/an) : "
          f"{nb_eligibles} / {len(salaries_actifs)} "
          f"({nb_eligibles / len(salaries_actifs) * 100:.0f}%)")

    nb_avec_commentaire = df_activites["commentaire"].notna().sum()
    print(f"Activités avec commentaire : {nb_avec_commentaire} "
          f"({nb_avec_commentaire / len(df_activites) * 100:.0f}%)")


if __name__ == "__main__":
    main()
