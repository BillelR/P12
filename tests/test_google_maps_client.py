"""
Tests unitaires : google_maps_client.py

Les appels réseau réels vers l'API Google Maps sont mockés (unittest.mock) :
ces tests valident la LOGIQUE MÉTIER (seuils d'éligibilité, détection
d'anomalie de déclaration), pas la disponibilité de l'API elle-même.
"""

from unittest.mock import patch

import pytest

from google_maps_client import (
    calculer_trajet,
    SEUIL_KM_MARCHE_COURSE,
    SEUIL_KM_VELO_AUTRE,
    MULTIPLICATEUR_ANOMALIE,
)


def _reponse_google_ok(distance_metres: int, duree_secondes: int = 1800) -> dict:
    """Construit une réponse Google Distance Matrix simulée, statut OK."""
    return {
        "status": "OK",
        "rows": [{"elements": [{
            "status": "OK",
            "distance": {"value": distance_metres, "text": f"{distance_metres / 1000} km"},
            "duration": {"value": duree_secondes, "text": f"{duree_secondes // 60} min"},
        }]}],
    }


class TestModeDeTransportNonActif:
    def test_transports_en_commun_retourne_none(self):
        """Un salarié en transports en commun n'est pas concerné par le calcul
        (seuls marche/course et vélo/trottinette sont évalués)."""
        resultat = calculer_trajet(1, "10 rue Test, Paris", "Transports en commun", "fake_key")
        assert resultat is None

    def test_vehicule_retourne_none(self):
        resultat = calculer_trajet(1, "10 rue Test, Paris", "véhicule thermique/électrique", "fake_key")
        assert resultat is None


class TestEligibiliteMarcheCourse:
    @patch("google_maps_client._appeler_distance_matrix")
    def test_distance_sous_le_seuil_est_eligible(self, mock_appel):
        mock_appel.return_value = _reponse_google_ok(distance_metres=10_000)  # 10 km
        resultat = calculer_trajet(1, "adresse", "Marche/running", "fake_key")

        assert resultat["distance_km"] == 10.0
        assert resultat["distance_eligible"] is True
        assert resultat["anomalie_declaration"] is False

    @patch("google_maps_client._appeler_distance_matrix")
    def test_distance_juste_au_dessus_du_seuil_non_eligible(self, mock_appel):
        mock_appel.return_value = _reponse_google_ok(distance_metres=16_000)  # 16 km > 15 km
        resultat = calculer_trajet(1, "adresse", "Marche/running", "fake_key")

        assert resultat["distance_eligible"] is False
        # 16 km n'est pas encore une anomalie manifeste (seuil * 2 = 30 km)
        assert resultat["anomalie_declaration"] is False

    @patch("google_maps_client._appeler_distance_matrix")
    def test_distance_50km_en_marchant_est_une_anomalie(self, mock_appel):
        """Cas exact donné en exemple dans la note de cadrage : un salarié
        déclarant venir à pied alors qu'il habite à 50 km."""
        mock_appel.return_value = _reponse_google_ok(distance_metres=50_000)
        resultat = calculer_trajet(1, "adresse", "Marche/running", "fake_key")

        assert resultat["distance_eligible"] is False
        assert resultat["anomalie_declaration"] is True


class TestEligibiliteVelo:
    @patch("google_maps_client._appeler_distance_matrix")
    def test_distance_sous_le_seuil_velo_est_eligible(self, mock_appel):
        mock_appel.return_value = _reponse_google_ok(distance_metres=20_000)  # 20 km <= 25 km
        resultat = calculer_trajet(1, "adresse", "Vélo/Trottinette/Autres", "fake_key")

        assert resultat["distance_eligible"] is True

    @patch("google_maps_client._appeler_distance_matrix")
    def test_distance_60km_en_velo_est_une_anomalie(self, mock_appel):
        mock_appel.return_value = _reponse_google_ok(distance_metres=60_000)  # > 25*2=50
        resultat = calculer_trajet(1, "adresse", "Vélo/Trottinette/Autres", "fake_key")

        assert resultat["anomalie_declaration"] is True


class TestGestionErreursApi:
    @patch("google_maps_client._appeler_distance_matrix")
    def test_statut_request_denied_ne_leve_pas_exception(self, mock_appel):
        mock_appel.return_value = {"status": "REQUEST_DENIED", "rows": []}
        resultat = calculer_trajet(1, "adresse", "Marche/running", "fake_key")

        assert resultat["erreur"] == "REQUEST_DENIED"
        assert resultat["distance_eligible"] is False
        assert resultat["distance_km"] is None

    @patch("google_maps_client._appeler_distance_matrix")
    def test_adresse_introuvable_not_found(self, mock_appel):
        mock_appel.return_value = {
            "status": "OK",
            "rows": [{"elements": [{"status": "NOT_FOUND"}]}],
        }
        resultat = calculer_trajet(1, "adresse invalide", "Marche/running", "fake_key")

        assert resultat["erreur"] == "NOT_FOUND"


def test_seuils_conformes_a_la_note_de_cadrage():
    """Vérifie que les constantes de seuil n'ont pas été modifiées par erreur."""
    assert SEUIL_KM_MARCHE_COURSE == 15
    assert SEUIL_KM_VELO_AUTRE == 25
