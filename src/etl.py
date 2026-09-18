"""
Pipeline ETL principal du projet "Avantages Sportifs".

Étapes :
    1. Extraction : lecture des fichiers RH, sportifs (bruts) et activités (générées)
    2. Transformation : nettoyage, renommage des colonnes vers le schéma SQL
    3. Chargement : insertion dans Supabase (salaries, sports_pratiques, activites_sportives)
    4. Calcul des trajets domicile-travail via Google Maps
    5. Calcul de la table d'éligibilité consolidée (prime mobilité + jours bien-être)

Prérequis : avoir exécuté sql/schema.sql dans Supabase au préalable,
et avoir un fichier .env valide (voir .env.example).

Usage : python src/etl.py
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db_utils import get_engine, log_event, timed_step, GOOGLE_MAPS_API_KEY
from google_maps_client import (
    calculer_tous_les_trajets,
    MULTIPLICATEUR_ANOMALIE,
    GoogleMapsAuthError,
)

BASE_DIR = Path(__file__).resolve().parent.parent
RH_FILE = BASE_DIR / "data" / "raw" / "donnees_rh.xlsx"
SPORT_FILE = BASE_DIR / "data" / "raw" / "donnees_sportives.xlsx"
ACTIVITES_FILE = BASE_DIR / "data" / "generated" / "activites_sportives_generees.csv"

SEUIL_ACTIVITES_AN = 15

# Colonnes attendues après renommage, pour chaque source. pandas.rename()
# n'échoue jamais silencieusement si un intitulé Excel a changé — la colonne
# est juste absente du DataFrame, et l'erreur (KeyError) ne remonte que
# beaucoup plus tard, au moment du chargement en base. On valide donc tout
# de suite, avec un message qui pointe vers le fichier et la colonne en cause.
COLONNES_SALARIES_ATTENDUES = [
    "id_salarie", "nom", "prenom", "date_naissance", "bu", "date_embauche",
    "salaire_annuel", "type_contrat", "jours_cp", "adresse_domicile",
    "moyen_deplacement",
]
COLONNES_SPORTS_ATTENDUES = ["id_salarie", "sport"]
COLONNES_ACTIVITES_ATTENDUES = [
    "id_salarie", "date_debut_activite", "sport", "distance_m",
    "date_fin_activite", "commentaire",
]


def _valider_dataframe(df: pd.DataFrame, colonnes_attendues: list[str], source: Path):
    """
    Vérifie qu'un DataFrame fraîchement lu n'est pas vide et contient bien
    toutes les colonnes attendues (après renommage). Lève ValueError avec un
    message actionnable plutôt que de laisser une KeyError obscure survenir
    plus tard, au milieu du chargement en base.
    """
    if df.empty:
        raise ValueError(f"Fichier vide ou sans lignes exploitables : {source}")

    manquantes = [c for c in colonnes_attendues if c not in df.columns]
    if manquantes:
        raise ValueError(
            f"Colonne(s) manquante(s) dans {source} après renommage : {manquantes}. "
            f"Le fichier source a probablement changé d'intitulés de colonnes."
        )


# ----------------------------------------------------------------------------
# 1. EXTRACTION + TRANSFORMATION
# ----------------------------------------------------------------------------

def extraire_transformer_salaries() -> pd.DataFrame:
    if not RH_FILE.exists():
        raise FileNotFoundError(
            f"Fichier RH introuvable : {RH_FILE}. Vérifie data/raw/donnees_rh.xlsx."
        )
    df = pd.read_excel(RH_FILE)
    df = df.rename(columns={
        "ID salarié": "id_salarie",
        "Nom": "nom",
        "Prénom": "prenom",
        "Date de naissance": "date_naissance",
        "BU": "bu",
        "Date d'embauche": "date_embauche",
        "Salaire brut": "salaire_annuel",
        "Type de contrat": "type_contrat",
        "Nombre de jours de CP": "jours_cp",
        "Adresse du domicile": "adresse_domicile",
        "Moyen de déplacement": "moyen_deplacement",
    })
    _valider_dataframe(df, COLONNES_SALARIES_ATTENDUES, RH_FILE)
    return df


def extraire_transformer_sports() -> pd.DataFrame:
    if not SPORT_FILE.exists():
        raise FileNotFoundError(
            f"Fichier sportif introuvable : {SPORT_FILE}. Vérifie data/raw/donnees_sportives.xlsx."
        )
    df = pd.read_excel(SPORT_FILE)
    df = df.rename(columns={
        "ID salarié": "id_salarie",
        "Pratique d'un sport": "sport",
    })
    _valider_dataframe(df, COLONNES_SPORTS_ATTENDUES, SPORT_FILE)
    return df


def extraire_activites() -> pd.DataFrame:
    if not ACTIVITES_FILE.exists():
        raise FileNotFoundError(
            f"Fichier d'activités introuvable : {ACTIVITES_FILE}. "
            f"As-tu lancé src/generate_activities.py avant le pipeline ?"
        )
    df = pd.read_csv(ACTIVITES_FILE, parse_dates=["date_debut_activite", "date_fin_activite"])
    _valider_dataframe(df, COLONNES_ACTIVITES_ATTENDUES, ACTIVITES_FILE)
    return df


# ----------------------------------------------------------------------------
# 2. CHARGEMENT
# ----------------------------------------------------------------------------

def charger_table(df: pd.DataFrame, nom_table: str, engine, if_exists: str = "append"):
    df.to_sql(nom_table, engine, if_exists=if_exists, index=False, method="multi", chunksize=200)


def vider_tables(engine):
    """Vide les tables avant un nouveau run complet (idempotence du pipeline)."""
    with engine.begin() as conn:
        for table in ["eligibilite_avantages", "trajets_domicile_travail",
                      "activites_sportives", "sports_pratiques", "salaries"]:
            conn.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))


# ----------------------------------------------------------------------------
# 3. CALCUL D'ÉLIGIBILITÉ
# ----------------------------------------------------------------------------

def calculer_eligibilite(df_salaries: pd.DataFrame, df_activites: pd.DataFrame,
                          resultats_trajets: list[dict]) -> pd.DataFrame:
    date_limite = datetime.now() - timedelta(days=365)

    # Nombre d'activités sur 12 mois glissants, par salarié
    activites_recentes = df_activites[df_activites["date_debut_activite"] >= date_limite]
    nb_activites = activites_recentes.groupby("id_salarie").size().rename("nb_activites_12_mois")

    df_eligibilite = df_salaries[["id_salarie"]].merge(
        nb_activites, on="id_salarie", how="left"
    )
    df_eligibilite["nb_activites_12_mois"] = df_eligibilite["nb_activites_12_mois"].fillna(0).astype(int)
    df_eligibilite["eligible_jours_bien_etre"] = df_eligibilite["nb_activites_12_mois"] >= SEUIL_ACTIVITES_AN

    df_trajets = pd.DataFrame(resultats_trajets)
    if not df_trajets.empty:
        df_trajets = df_trajets[df_trajets["erreur"].isna()]
        df_eligibilite = df_eligibilite.merge(
            df_trajets[["id_salarie", "distance_km", "mode_transport", "distance_eligible"]],
            on="id_salarie", how="left"
        )
        df_eligibilite = df_eligibilite.rename(columns={
            "distance_km": "distance_trajet_km",
            "mode_transport": "mode_transport_retenu",
            "distance_eligible": "eligible_prime_mobilite",
        })
    else:
        df_eligibilite["distance_trajet_km"] = None
        df_eligibilite["mode_transport_retenu"] = None
        df_eligibilite["eligible_prime_mobilite"] = False

    df_eligibilite["eligible_prime_mobilite"] = df_eligibilite["eligible_prime_mobilite"].fillna(False)

    return df_eligibilite


# ----------------------------------------------------------------------------
# PIPELINE PRINCIPAL
# ----------------------------------------------------------------------------

def main():
    engine = get_engine()

    try:
        with timed_step("Extraction + transformation"):
            df_salaries = extraire_transformer_salaries()
            df_sports = extraire_transformer_sports()
            df_activites = extraire_activites()
        log_event("INFO", "extraction", f"{len(df_salaries)} salariés, "
                  f"{len(df_sports)} entrées sport, {len(df_activites)} activités lues.")

        with timed_step("Nettoyage des tables Supabase"):
            vider_tables(engine)
        log_event("INFO", "nettoyage", "Tables vidées avant rechargement complet.")

        with timed_step("Chargement salaries"):
            charger_table(df_salaries, "salaries", engine)
        log_event("INFO", "chargement", "Table salaries chargée.",
                  nb_lignes_traitees=len(df_salaries))

        with timed_step("Chargement sports_pratiques"):
            charger_table(df_sports, "sports_pratiques", engine)
        log_event("INFO", "chargement", "Table sports_pratiques chargée.",
                  nb_lignes_traitees=len(df_sports))

        with timed_step("Chargement activites_sportives"):
            charger_table(df_activites[["id_salarie", "date_debut_activite", "sport",
                                         "distance_m", "date_fin_activite", "commentaire"]],
                          "activites_sportives", engine)
        log_event("INFO", "chargement", "Table activites_sportives chargée.",
                  nb_lignes_traitees=len(df_activites))

        with timed_step("Calcul des trajets Google Maps"):
            if not GOOGLE_MAPS_API_KEY:
                raise RuntimeError("GOOGLE_MAPS_API_KEY manquant dans .env")
            try:
                resultats_trajets = calculer_tous_les_trajets(df_salaries, GOOGLE_MAPS_API_KEY)
            except GoogleMapsAuthError as e:
                # Erreur bloquante (clé invalide/expirée ou quota épuisé) :
                # on ne tente pas de continuer sans distances, on interrompt
                # le pipeline avant le chargement des trajets/éligibilité.
                # L'alerte Slack est envoyée une seule fois, par le handler
                # global ci-dessous — on se contente ici de tracer le contexte.
                log_event(
                    "ERROR", "google_maps_auth",
                    f"Clé API Google Maps invalide/expirée ou quota épuisé : {e}",
                )
                raise
            if resultats_trajets:
                df_trajets_ok = pd.DataFrame(
                    [r for r in resultats_trajets if r["erreur"] is None]
                )
                if not df_trajets_ok.empty:
                    charger_table(
                        df_trajets_ok[["id_salarie", "mode_transport", "distance_km",
                                        "duree_estimee_min", "distance_eligible",
                                        "anomalie_declaration"]],
                        "trajets_domicile_travail", engine
                    )
        nb_erreurs = sum(1 for r in resultats_trajets if r["erreur"] is not None)
        log_event(
            "WARNING" if nb_erreurs else "INFO",
            "google_maps",
            f"{len(resultats_trajets)} trajets calculés, {nb_erreurs} erreurs.",
            nb_lignes_traitees=len(resultats_trajets),
        )

        # Détection des anomalies de déclaration (cf. note de cadrage :
        # ex. salarié déclarant venir à pied en habitant à 50 km). On alerte
        # explicitement sur Slack, avec le détail des salariés concernés.
        with timed_step("Détection des anomalies de déclaration"):
            anomalies = [r for r in resultats_trajets
                         if r["erreur"] is None and r.get("anomalie_declaration")]
            if anomalies:
                df_anomalies = pd.DataFrame(anomalies).merge(
                    df_salaries[["id_salarie", "nom", "prenom"]], on="id_salarie", how="left"
                )
                details = "\n".join(
                    f"- {row['prenom']} {row['nom']} (id {row['id_salarie']}) : "
                    f"déclare \"{row['mode_transport']}\" mais habite à {row['distance_km']} km "
                    f"(seuil dépassé de plus de {int((MULTIPLICATEUR_ANOMALIE - 1) * 100)}%)"
                    for _, row in df_anomalies.iterrows()
                )
                message = (f"{len(anomalies)} déclaration(s) de mode de transport suspecte(s) "
                           f"détectée(s) :\n{details}")
                log_event("WARNING", "anomalie_declaration", message, alerter_slack=True)
            else:
                log_event("INFO", "anomalie_declaration",
                          "Aucune anomalie de déclaration détectée.")

        with timed_step("Calcul de l'éligibilité"):
            df_eligibilite = calculer_eligibilite(df_salaries, df_activites, resultats_trajets)
            charger_table(df_eligibilite, "eligibilite_avantages", engine)

        nb_eligibles_prime = df_eligibilite["eligible_prime_mobilite"].sum()
        nb_eligibles_bien_etre = df_eligibilite["eligible_jours_bien_etre"].sum()

        log_event(
            "INFO", "pipeline_termine",
            f"Pipeline terminé avec succès. "
            f"{nb_eligibles_prime} salariés éligibles à la prime mobilité, "
            f"{nb_eligibles_bien_etre} éligibles aux jours bien-être.",
            alerter_slack=True,
        )

    except GoogleMapsAuthError as e:
        log_event(
            "ERROR", "pipeline_erreur",
            f"Pipeline interrompu : clé API Google Maps invalide/expirée ou quota "
            f"épuisé ({e}). Vérifie GOOGLE_MAPS_API_KEY dans .env et le quota sur "
            f"la console Google Cloud.",
            alerter_slack=True,
        )
        raise
    except FileNotFoundError as e:
        log_event(
            "ERROR", "pipeline_erreur",
            f"Pipeline interrompu : fichier source introuvable ({e}).",
            alerter_slack=True,
        )
        raise
    except ValueError as e:
        log_event(
            "ERROR", "pipeline_erreur",
            f"Pipeline interrompu : données source invalides ({e}).",
            alerter_slack=True,
        )
        raise
    except SQLAlchemyError as e:
        log_event(
            "ERROR", "pipeline_erreur",
            f"Pipeline interrompu : erreur base de données ({e}). Vérifie que "
            f"sql/schema.sql a bien été exécuté et que Supabase est joignable.",
            alerter_slack=True,
        )
        raise
    except Exception as e:
        log_event("ERROR", "pipeline_erreur", f"Le pipeline a échoué : {e}", alerter_slack=True)
        raise


if __name__ == "__main__":
    main()