"""
Calcule la distance domicile-travail de chaque salarié via l'API Google Maps
Distance Matrix, pour les modes de transport actif (marche/course et vélo),
et détermine l'éligibilité à la prime de mobilité (5% du salaire) :
    - marche/course : éligible si distance <= 15 km
    - vélo/autre     : éligible si distance <= 25 km

Adresse de l'entreprise à définir dans ADRESSE_ENTREPRISE ci-dessous.
"""

import os
import time

import requests

# Adresse réelle de l'entreprise, précisée dans la note de cadrage (section 5.1)
ADRESSE_ENTREPRISE = "1362 Av. des Platanes, 34970 Lattes"

SEUIL_KM_MARCHE_COURSE = 15
SEUIL_KM_VELO_AUTRE = 25

# Au-delà de ce multiplicateur du seuil, on considère que ce n'est plus une
# question de "limite un peu dépassée" mais une probable erreur de
# déclaration (cf. note de cadrage : salarié qui déclare venir à pied en
# habitant à 50 km, alors que le seuil est 15 km -> ratio > 3).
MULTIPLICATEUR_ANOMALIE = 2

DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"


def _appeler_distance_matrix(adresse_domicile: str, mode: str, api_key: str) -> dict:
    """Appelle l'API Google Distance Matrix pour une adresse et un mode donnés."""
    params = {
        "origins": adresse_domicile,
        "destinations": ADRESSE_ENTREPRISE,
        "mode": mode,  # "walking" ou "bicycling"
        "units": "metric",
        "key": api_key,
    }
    response = requests.get(DISTANCE_MATRIX_URL, params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def calculer_trajet(id_salarie: int, adresse_domicile: str, moyen_deplacement: str,
                     api_key: str) -> dict | None:
    """
    Calcule la distance et l'éligibilité pour un salarié, selon son moyen de
    déplacement déclaré. Retourne None si le moyen de déplacement n'est pas
    un mode actif (ex: transports en commun, véhicule motorisé).
    """
    moyen = moyen_deplacement.lower()

    if "marche" in moyen or "running" in moyen or "course" in moyen:
        mode_api = "walking"
        seuil = SEUIL_KM_MARCHE_COURSE
    elif "vélo" in moyen or "velo" in moyen or "trottinette" in moyen:
        mode_api = "bicycling"
        seuil = SEUIL_KM_VELO_AUTRE
    else:
        # Transports en commun, véhicule thermique/électrique : non concerné
        return None

    data = _appeler_distance_matrix(adresse_domicile, mode_api, api_key)

    if data.get("status") != "OK":
        return {
            "id_salarie": id_salarie,
            "mode_transport": mode_api,
            "distance_km": None,
            "duree_estimee_min": None,
            "distance_eligible": False,
            "anomalie_declaration": False,
            "erreur": data.get("status"),
        }

    element = data["rows"][0]["elements"][0]
    if element.get("status") != "OK":
        return {
            "id_salarie": id_salarie,
            "mode_transport": mode_api,
            "distance_km": None,
            "duree_estimee_min": None,
            "distance_eligible": False,
            "anomalie_declaration": False,
            "erreur": element.get("status"),
        }

    distance_km = round(element["distance"]["value"] / 1000, 2)
    duree_min = round(element["duration"]["value"] / 60)

    return {
        "id_salarie": id_salarie,
        "mode_transport": mode_api,
        "distance_km": distance_km,
        "duree_estimee_min": duree_min,
        "distance_eligible": distance_km <= seuil,
        "anomalie_declaration": distance_km > seuil * MULTIPLICATEUR_ANOMALIE,
        "erreur": None,
    }


def calculer_tous_les_trajets(df_salaries, api_key: str,
                                pause_entre_appels: float = 0.05) -> list[dict]:
    """
    Calcule le trajet pour tous les salariés ayant un mode de déplacement actif.
    df_salaries doit contenir les colonnes : id_salarie, adresse_domicile, moyen_deplacement
    """
    resultats = []
    for _, row in df_salaries.iterrows():
        resultat = calculer_trajet(
            row["id_salarie"], row["adresse_domicile"], row["moyen_deplacement"], api_key
        )
        if resultat is not None:
            resultats.append(resultat)
        time.sleep(pause_entre_appels)  # évite de saturer l'API sur 161 adresses

    return resultats