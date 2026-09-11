"""
Génération de données d'activités sportives simulées (façon Strava).

Le fichier "Données Sportives" fourni ne contient qu'une ligne par salarié
(le sport pratiqué), sans historique d'activités. Ce script génère un
historique d'activités réaliste sur une fenêtre glissante de 12 mois
(aujourd'hui - 365 jours -> aujourd'hui), pour permettre le calcul
d'éligibilité au bénéfice "5 jours bien-être" (seuil : >= 15 activités/an).

Utilise Faker pour la génération des dates, identifiants d'activité et
métadonnées type "export Strava" (application source, ville de pratique),
avec un provider français pour rester cohérent avec les données RH.

Sortie : data/generated/activites_sportives_generees.csv
Colonnes : id_activite, id_salarie, sport, date_activite, duree_minutes,
           distance_km, application_source, ville_pratique
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

# Applications de tracking sportif "façon Strava" (données fictives, pour
# enrichir le jeu de données simulé — aucune de ces marques n'est réellement
# intégrée, c'est un champ purement descriptif du jeu de données synthétique)
APPLICATIONS_SOURCE = ["Strava", "Garmin Connect", "Apple Santé", "Suunto App", "Polar Flow"]

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_SPORT_FILE = BASE_DIR / "data" / "raw" / "donnees_sportives.xlsx"
OUTPUT_FILE = BASE_DIR / "data" / "generated" / "activites_sportives_generees.csv"

# Fenêtre glissante de 12 mois se terminant aujourd'hui
DATE_FIN = datetime.now()
DATE_DEBUT = DATE_FIN - timedelta(days=365)

# Profil par sport
# freq_annuelle_moy : nombre moyen d'activités par an pour un pratiquant "moyen"
#                      (volontairement calibré autour du seuil d'éligibilité de 15/an,
#                      pour obtenir un mix réaliste d'éligibles / non-éligibles)
# duree_min/max : durée d'une séance en minutes
# distance_min/max : distance en km si pertinent, sinon None
SPORT_PROFILES = {
    "Runing":          {"freq_annuelle_moy": 20, "duree": (25, 60),  "distance": (4, 12)},
    "Football":        {"freq_annuelle_moy": 10, "duree": (60, 90),  "distance": None},
    "Tennis":          {"freq_annuelle_moy": 15, "duree": (45, 90),  "distance": None},
    "Natation":        {"freq_annuelle_moy": 15, "duree": (30, 60),  "distance": (0.5, 2.5)},
    "Randonnée":       {"freq_annuelle_moy": 8,  "duree": (90, 240), "distance": (5, 18)},
    "Badminton":       {"freq_annuelle_moy": 12, "duree": (45, 75),  "distance": None},
    "Basketball":      {"freq_annuelle_moy": 10, "duree": (60, 90),  "distance": None},
    "Rugby":           {"freq_annuelle_moy": 8,  "duree": (75, 105), "distance": None},
    "Boxe":            {"freq_annuelle_moy": 15, "duree": (45, 75),  "distance": None},
    "Judo":            {"freq_annuelle_moy": 12, "duree": (60, 90),  "distance": None},
    "Escalade":        {"freq_annuelle_moy": 8,  "duree": (60, 120), "distance": None},
    "Équitation":      {"freq_annuelle_moy": 6,  "duree": (60, 90),  "distance": None},
    "Voile":           {"freq_annuelle_moy": 4,  "duree": (120, 240), "distance": None},
    "Tennis de table": {"freq_annuelle_moy": 10, "duree": (30, 60),  "distance": None},
    "Triathlon":       {"freq_annuelle_moy": 22, "duree": (40, 90),  "distance": (3, 20)},
}

# Variabilité individuelle : chaque salarié a un niveau d'assiduité propre,
# multiplicateur appliqué à la fréquence moyenne de son sport (certains sont
# plus réguliers que d'autres pour un même sport déclaré).
ASSIDUITE_MIN, ASSIDUITE_MAX = 0.4, 1.8


def generer_dates_activites(freq_annuelle: float) -> list:
    """Génère des dates d'activités sur 52 semaines via un processus de Poisson
    hebdomadaire (rate = freq_annuelle / 52). Ce modèle produit naturellement des
    semaines sans activité, sans biaiser artificiellement les petites fréquences.
    Les dates elles-mêmes sont tirées avec Faker (date_between), borné à la
    semaine courante pour respecter la fréquence hebdomadaire calculée."""
    rate_hebdo = freq_annuelle / 52
    dates = []
    for semaine in range(52):
        nb_activites_semaine = np.random.poisson(rate_hebdo)
        semaine_debut = DATE_DEBUT + pd.Timedelta(days=semaine * 7)
        semaine_fin = min(semaine_debut + pd.Timedelta(days=6), DATE_FIN)
        if semaine_debut > DATE_FIN:
            break
        for _ in range(nb_activites_semaine):
            date_activite = fake.date_between(start_date=semaine_debut.date(),
                                               end_date=semaine_fin.date())
            dates.append(date_activite)
    return dates


def generer_activites_pour_salarie(id_salarie: int, sport: str) -> list[dict]:
    """Génère toutes les activités d'un salarié pour son sport déclaré."""
    profil = SPORT_PROFILES[sport]
    # Assiduité individuelle : deux salariés pratiquant le même sport n'ont pas
    # forcément la même régularité.
    assiduite = random.uniform(ASSIDUITE_MIN, ASSIDUITE_MAX)
    freq_annuelle_individuelle = profil["freq_annuelle_moy"] * assiduite
    dates = generer_dates_activites(freq_annuelle_individuelle)

    activites = []
    for date_activite in dates:
        duree = fake.random_int(*profil["duree"])
        distance = None
        if profil["distance"] is not None:
            distance = round(fake.pyfloat(min_value=profil["distance"][0],
                                           max_value=profil["distance"][1]), 1)

        activites.append({
            "id_salarie": id_salarie,
            "sport": sport,
            "date_activite": date_activite.strftime("%Y-%m-%d"),
            "duree_minutes": duree,
            "distance_km": distance,
            "application_source": fake.random_element(APPLICATIONS_SOURCE),
            "ville_pratique": fake.city(),
        })

    return activites


def main():
    df_sport = pd.read_excel(RAW_SPORT_FILE)
    df_sport = df_sport.rename(columns={
        "ID salarié": "id_salarie",
        "Pratique d'un sport": "sport",
    })

    # Uniquement les salariés ayant déclaré un sport
    salaries_actifs = df_sport[df_sport["sport"].notna()]

    toutes_activites = []
    for _, row in salaries_actifs.iterrows():
        activites = generer_activites_pour_salarie(row["id_salarie"], row["sport"])
        toutes_activites.extend(activites)

    df_activites = pd.DataFrame(toutes_activites)
    df_activites.insert(0, "id_activite", range(1, len(df_activites) + 1))
    df_activites = df_activites.sort_values(["id_salarie", "date_activite"]).reset_index(drop=True)
    df_activites["id_activite"] = range(1, len(df_activites) + 1)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    df_activites.to_csv(OUTPUT_FILE, index=False)

    # Statistiques de contrôle
    print(f"Fenêtre : {DATE_DEBUT:%Y-%m-%d} -> {DATE_FIN:%Y-%m-%d}")
    print(f"Salariés actifs (avec sport déclaré) : {len(salaries_actifs)}")
    print(f"Total activités générées : {len(df_activites)}")
    print(f"Moyenne activités/salarié actif : {len(df_activites) / len(salaries_actifs):.1f}")
    print(f"\nFichier écrit : {OUTPUT_FILE}")

    print("\nRépartition par sport :")
    print(df_activites.groupby("sport").size().sort_values(ascending=False))

    print("\nSalariés éligibles au bénéfice (>= 15 activités/an) :")
    compte_par_salarie = df_activites.groupby("id_salarie").size()
    nb_eligibles = (compte_par_salarie >= 15).sum()
    print(f"{nb_eligibles} / {len(salaries_actifs)} salariés actifs "
          f"({nb_eligibles / len(salaries_actifs) * 100:.0f}%)")


if __name__ == "__main__":
    main()
