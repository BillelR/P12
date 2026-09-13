"""
Tests unitaires : etl.py — calculer_eligibilite()

Cette fonction est le cœur métier du projet : elle détermine qui a droit à
la prime de mobilité (5% du salaire) et aux 5 jours bien-être. On teste les
cas limites (exactement au seuil, aucune activité, salarié sans trajet actif).
"""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from etl import calculer_eligibilite, SEUIL_ACTIVITES_AN


@pytest.fixture
def df_salaries_simple():
    return pd.DataFrame({"id_salarie": [1, 2, 3]})


def _activite(id_salarie: int, jours_avant_aujourdhui: int) -> dict:
    date = datetime.now() - timedelta(days=jours_avant_aujourdhui)
    return {"id_salarie": id_salarie, "date_debut_activite": date}


class TestEligibiliteJoursBienEtre:
    def test_exactement_15_activites_est_eligible(self, df_salaries_simple):
        """Le seuil est >= 15, donc pile 15 doit être éligible (pas 14)."""
        activites = [_activite(1, jours_avant_aujourdhui=10) for _ in range(SEUIL_ACTIVITES_AN)]
        df_activites = pd.DataFrame(activites)

        resultat = calculer_eligibilite(df_salaries_simple, df_activites, [])
        ligne = resultat[resultat["id_salarie"] == 1].iloc[0]

        assert ligne["nb_activites_12_mois"] == 15
        assert ligne["eligible_jours_bien_etre"] == True

    def test_14_activites_non_eligible(self, df_salaries_simple):
        activites = [_activite(1, jours_avant_aujourdhui=10) for _ in range(14)]
        df_activites = pd.DataFrame(activites)

        resultat = calculer_eligibilite(df_salaries_simple, df_activites, [])
        ligne = resultat[resultat["id_salarie"] == 1].iloc[0]

        assert ligne["eligible_jours_bien_etre"] == False

    def test_activites_hors_fenetre_12_mois_ignorees(self, df_salaries_simple):
        """Une activité vieille de 400 jours (> 365) ne doit pas compter."""
        activites = (
            [_activite(1, jours_avant_aujourdhui=10) for _ in range(20)]
            + [_activite(1, jours_avant_aujourdhui=400) for _ in range(20)]  # hors fenêtre
        )
        df_activites = pd.DataFrame(activites)

        resultat = calculer_eligibilite(df_salaries_simple, df_activites, [])
        ligne = resultat[resultat["id_salarie"] == 1].iloc[0]

        assert ligne["nb_activites_12_mois"] == 20  # les 20 hors-fenêtre sont exclues

    def test_salarie_sans_aucune_activite(self, df_salaries_simple):
        df_activites = pd.DataFrame(columns=["id_salarie", "date_debut_activite"])

        resultat = calculer_eligibilite(df_salaries_simple, df_activites, [])
        ligne = resultat[resultat["id_salarie"] == 2].iloc[0]

        assert ligne["nb_activites_12_mois"] == 0
        assert ligne["eligible_jours_bien_etre"] == False


class TestEligibilitePrimeMobilite:
    def test_salarie_eligible_selon_trajet(self, df_salaries_simple):
        df_activites = pd.DataFrame(columns=["id_salarie", "date_debut_activite"])
        resultats_trajets = [
            {"id_salarie": 1, "distance_km": 5.0, "mode_transport": "walking",
             "distance_eligible": True, "erreur": None},
        ]

        resultat = calculer_eligibilite(df_salaries_simple, df_activites, resultats_trajets)
        ligne = resultat[resultat["id_salarie"] == 1].iloc[0]

        assert ligne["eligible_prime_mobilite"] == True
        assert ligne["distance_trajet_km"] == 5.0

    def test_salarie_sans_trajet_actif_non_eligible_par_defaut(self, df_salaries_simple):
        """Un salarié en transports en commun n'a pas d'entrée dans
        resultats_trajets (calculer_trajet retourne None pour lui) : il doit
        être considéré non éligible par défaut, sans planter."""
        df_activites = pd.DataFrame(columns=["id_salarie", "date_debut_activite"])
        resultats_trajets = [
            {"id_salarie": 1, "distance_km": 5.0, "mode_transport": "walking",
             "distance_eligible": True, "erreur": None},
        ]  # rien pour le salarié 2 ni 3

        resultat = calculer_eligibilite(df_salaries_simple, df_activites, resultats_trajets)
        ligne_2 = resultat[resultat["id_salarie"] == 2].iloc[0]

        assert ligne_2["eligible_prime_mobilite"] == False

    def test_trajet_en_erreur_exclu_du_calcul(self, df_salaries_simple):
        """Un trajet avec une erreur API ne doit pas être compté comme
        éligible, même s'il a une valeur distance_eligible résiduelle."""
        df_activites = pd.DataFrame(columns=["id_salarie", "date_debut_activite"])
        resultats_trajets = [
            {"id_salarie": 1, "distance_km": None, "mode_transport": "walking",
             "distance_eligible": False, "erreur": "REQUEST_DENIED"},
        ]

        resultat = calculer_eligibilite(df_salaries_simple, df_activites, resultats_trajets)
        ligne = resultat[resultat["id_salarie"] == 1].iloc[0]

        assert ligne["eligible_prime_mobilite"] == False

    def test_aucun_trajet_calcule_tous_non_eligibles(self, df_salaries_simple):
        """Cas où calculer_tous_les_trajets renvoie une liste vide (ex: aucun
        salarié en mode actif) : ne doit pas planter, tout le monde à False."""
        df_activites = pd.DataFrame(columns=["id_salarie", "date_debut_activite"])

        resultat = calculer_eligibilite(df_salaries_simple, df_activites, [])

        assert (resultat["eligible_prime_mobilite"] == False).all()
        assert len(resultat) == 3
