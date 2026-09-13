"""
Contrôles qualité des données avec Great Expectations (API 1.x, "fluent").

Vérifie la cohérence des 3 jeux de données sources (salaries, sports_pratiques,
activites_sportives) AVANT leur chargement dans Supabase. Chaque échec est
loggé dans logs_monitoring et déclenche une alerte Slack si des anomalies
bloquantes sont détectées.

Usage : python src/quality_checks.py
Retourne un code de sortie non nul si des contrôles critiques échouent
(utilisable comme étape bloquante dans un pipeline Kestra).
"""

import sys
from datetime import datetime, timedelta

import great_expectations as gx
import pandas as pd

from db_utils import log_event
from etl import extraire_transformer_salaries, extraire_transformer_sports, extraire_activites

MOYENS_DEPLACEMENT_VALIDES = [
    "Transports en commun",
    "véhicule thermique/électrique",
    "Marche/running",
    "Vélo/Trottinette/Autres",
]


def _get_batch(df: pd.DataFrame, nom: str):
    context = gx.get_context()
    data_source = context.data_sources.add_pandas(f"src_{nom}")
    data_asset = data_source.add_dataframe_asset(name=nom)
    batch_definition = data_asset.add_batch_definition_whole_dataframe(f"batch_{nom}")
    return batch_definition.get_batch(batch_parameters={"dataframe": df})


def _valider(batch, expectation, libelle: str, resultats: list, critique: bool = True):
    result = batch.validate(expectation)
    resultats.append({
        "libelle": libelle,
        "success": result.success,
        "critique": critique,
        "details": result.result,
    })
    statut = "OK" if result.success else ("ÉCHEC CRITIQUE" if critique else "AVERTISSEMENT")
    print(f"  [{statut}] {libelle}")
    return result.success


def controler_salaries(df: pd.DataFrame) -> list:
    print("\n--- Contrôles : salaries ---")
    batch = _get_batch(df, "salaries")
    resultats = []

    _valider(batch, gx.expectations.ExpectColumnValuesToNotBeNull(column="id_salarie"),
              "id_salarie renseigné", resultats, critique=True)
    _valider(batch, gx.expectations.ExpectColumnValuesToBeUnique(column="id_salarie"),
              "id_salarie unique (pas de doublon)", resultats, critique=True)
    _valider(batch, gx.expectations.ExpectColumnValuesToNotBeNull(column="adresse_domicile"),
              "adresse_domicile renseignée", resultats, critique=True)
    _valider(batch, gx.expectations.ExpectColumnValuesToBeBetween(
                column="salaire_annuel", min_value=1000, max_value=500000),
              "salaire_annuel dans une plage plausible", resultats, critique=False)
    _valider(batch, gx.expectations.ExpectColumnValuesToBeBetween(
                column="jours_cp", min_value=0, max_value=60),
              "jours_cp dans une plage plausible", resultats, critique=False)
    _valider(batch, gx.expectations.ExpectColumnValuesToBeInSet(
                column="moyen_deplacement", value_set=MOYENS_DEPLACEMENT_VALIDES),
              "moyen_deplacement dans les catégories connues", resultats, critique=False)
    _valider(batch, gx.expectations.ExpectColumnValuesToNotBeNull(column="type_contrat"),
              "type_contrat renseigné", resultats, critique=False)

    return resultats


def controler_sports(df: pd.DataFrame) -> list:
    print("\n--- Contrôles : sports_pratiques ---")
    batch = _get_batch(df, "sports")
    resultats = []

    _valider(batch, gx.expectations.ExpectColumnValuesToNotBeNull(column="id_salarie"),
              "id_salarie renseigné", resultats, critique=True)
    _valider(batch, gx.expectations.ExpectColumnValuesToBeUnique(column="id_salarie"),
              "id_salarie unique (une ligne par salarié)", resultats, critique=True)

    return resultats


def controler_activites(df: pd.DataFrame) -> list:
    print("\n--- Contrôles : activites_sportives (données générées) ---")
    batch = _get_batch(df, "activites")
    resultats = []

    date_min = pd.Timestamp(datetime.now() - timedelta(days=366))
    date_max = pd.Timestamp(datetime.now())

    _valider(batch, gx.expectations.ExpectColumnValuesToNotBeNull(column="id_salarie"),
              "id_salarie renseigné", resultats, critique=True)
    _valider(batch, gx.expectations.ExpectColumnValuesToBeBetween(
                column="date_debut_activite", min_value=date_min, max_value=date_max),
              "date_debut_activite dans la fenêtre glissante de 12 mois", resultats, critique=True)
    _valider(batch, gx.expectations.ExpectColumnPairValuesAToBeGreaterThanB(
                column_A="date_fin_activite", column_B="date_debut_activite", or_equal=True),
              "date_fin_activite postérieure ou égale à date_debut_activite", resultats, critique=True)
    _valider(batch, gx.expectations.ExpectColumnValuesToBeBetween(
                column="distance_m", min_value=0, max_value=200_000),
              "distance_m non négative et plausible (0 à 200 km)", resultats, critique=True)
    _valider(batch, gx.expectations.ExpectColumnValuesToNotBeNull(column="sport"),
              "sport renseigné", resultats, critique=True)

    return resultats


def main() -> bool:
    """Exécute tous les contrôles. Retourne True si aucun échec critique."""
    print("Lancement des contrôles qualité (Great Expectations)...")

    df_salaries = extraire_transformer_salaries()
    df_sports = extraire_transformer_sports()
    df_activites = extraire_activites()

    tous_resultats = []
    tous_resultats += controler_salaries(df_salaries)
    tous_resultats += controler_sports(df_sports)
    tous_resultats += controler_activites(df_activites)

    nb_echecs_critiques = sum(1 for r in tous_resultats if not r["success"] and r["critique"])
    nb_avertissements = sum(1 for r in tous_resultats if not r["success"] and not r["critique"])
    nb_ok = sum(1 for r in tous_resultats if r["success"])

    resume = (f"{nb_ok}/{len(tous_resultats)} contrôles OK, "
              f"{nb_avertissements} avertissement(s), "
              f"{nb_echecs_critiques} échec(s) critique(s).")

    print(f"\n=== Résumé : {resume} ===")

    niveau = "ERROR" if nb_echecs_critiques > 0 else ("WARNING" if nb_avertissements > 0 else "INFO")
    log_event(niveau, "quality_check", resume,
              nb_lignes_traitees=len(df_salaries) + len(df_sports) + len(df_activites),
              alerter_slack=(niveau in ("ERROR", "WARNING")))

    return nb_echecs_critiques == 0


if __name__ == "__main__":
    succes = main()
    sys.exit(0 if succes else 1)
