"""
Calcule la distance domicile-travail de chaque salarié via l'API Google Maps
Distance Matrix, pour les modes de transport actif (marche/course et vélo),
et détermine l'éligibilité à la prime de mobilité (5% du salaire) :
    - marche/course : éligible si distance <= 15 km
    - vélo/autre     : éligible si distance <= 25 km

Adresse de l'entreprise à définir dans ADRESSE_ENTREPRISE ci-dessous.

Gestion des cas limites :
  - erreurs réseau / timeout / HTTP 5xx : retry avec backoff exponentiel
  - clé API invalide/expirée ou quota épuisé (REQUEST_DENIED, OVER_DAILY_LIMIT) :
    considéré comme bloquant pour tout le batch -> exception GoogleMapsAuthError
  - rate limit (OVER_QUERY_LIMIT) / erreur serveur transitoire (UNKNOWN_ERROR) :
    retry avec backoff avant d'abandonner
  - adresse manquante, réponse vide, champ manquant/renommé dans le JSON :
    jamais d'exception qui plante tout le pipeline -> résultat "erreur"
    renseigné pour ce salarié, le traitement continue sur les suivants
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)

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

# --- Gestion des erreurs API -------------------------------------------------

# Statuts globaux/par élément qui indiquent un problème de clé/quota : on
# arrête tout le batch, ça ne sert à rien de continuer à appeler l'API pour
# les 160 salariés suivants avec une clé cassée.
STATUTS_BLOQUANTS = {
    "REQUEST_DENIED",    # clé API invalide, expirée, ou API non activée
    "OVER_DAILY_LIMIT",  # quota journalier épuisé / facturation désactivée
}

# Statuts transitoires : on retente avec un backoff avant d'abandonner.
# (La Distance Matrix API ne pagine pas ; le vrai risque sur 161 adresses
# est le rate limit, couvert ici.)
STATUTS_TRANSITOIRES = {
    "OVER_QUERY_LIMIT",  # rate limit dépassé (trop de requêtes/seconde)
    "UNKNOWN_ERROR",      # erreur serveur Google, généralement transitoire
}

NB_TENTATIVES_MAX = 4
BACKOFF_INITIAL_SECONDES = 1.0


class GoogleMapsAuthError(Exception):
    """Clé API invalide/expirée ou quota épuisé : inutile de continuer le batch."""


class GoogleMapsAPIError(Exception):
    """Erreur API non récupérable après plusieurs tentatives, pour un salarié donné."""


def _appeler_distance_matrix(adresse_domicile: str, mode: str, api_key: str) -> dict:
    """
    Appelle l'API Google Distance Matrix pour une adresse et un mode donnés,
    avec retry/backoff sur les erreurs réseau, les HTTP 5xx et les statuts
    transitoires (OVER_QUERY_LIMIT, UNKNOWN_ERROR).

    Lève GoogleMapsAuthError si la clé API est invalide/expirée ou le quota
    épuisé (erreur non récupérable, à remonter immédiatement à l'appelant).
    Lève GoogleMapsAPIError si toutes les tentatives échouent.
    """
    params = {
        "origins": adresse_domicile,
        "destinations": ADRESSE_ENTREPRISE,
        "mode": mode,  # "walking" ou "bicycling"
        "units": "metric",
        "key": api_key,
    }

    derniere_erreur = None

    for tentative in range(1, NB_TENTATIVES_MAX + 1):
        try:
            response = requests.get(DISTANCE_MATRIX_URL, params=params, timeout=10)
            response.raise_for_status()
        except requests.exceptions.Timeout as e:
            derniere_erreur = e
            logger.warning(
                "Timeout Google Maps (tentative %d/%d) pour %r",
                tentative, NB_TENTATIVES_MAX, adresse_domicile,
            )
        except requests.exceptions.HTTPError as e:
            statut_http = e.response.status_code if e.response is not None else None
            if statut_http is not None and statut_http < 500:
                # 4xx : erreur côté requête (hors quota, déjà géré par 'status'
                # JSON habituellement) -> pas la peine de retenter.
                raise GoogleMapsAPIError(
                    f"Erreur HTTP {statut_http} non récupérable pour {adresse_domicile!r} : {e}"
                ) from e
            derniere_erreur = e
            logger.warning(
                "Erreur HTTP %s Google Maps (tentative %d/%d) pour %r",
                statut_http, tentative, NB_TENTATIVES_MAX, adresse_domicile,
            )
        except requests.exceptions.RequestException as e:
            # Panne réseau, DNS, connexion refusée, etc.
            derniere_erreur = e
            logger.warning(
                "Erreur réseau Google Maps (tentative %d/%d) pour %r : %s",
                tentative, NB_TENTATIVES_MAX, adresse_domicile, e,
            )
        else:
            try:
                data = response.json()
            except ValueError as e:
                # Réponse 200 mais corps non-JSON (page d'erreur HTML, proxy...)
                raise GoogleMapsAPIError(
                    f"Réponse Google Maps illisible (JSON invalide) pour {adresse_domicile!r}"
                ) from e

            statut_global = data.get("status")

            if statut_global in STATUTS_BLOQUANTS:
                raise GoogleMapsAuthError(
                    f"Google Maps a renvoyé '{statut_global}' — clé API invalide/expirée "
                    f"ou quota épuisé. Arrêt du batch."
                )

            if statut_global in STATUTS_TRANSITOIRES:
                derniere_erreur = RuntimeError(f"Statut transitoire '{statut_global}'")
                logger.warning(
                    "Statut transitoire '%s' (tentative %d/%d) pour %r",
                    statut_global, tentative, NB_TENTATIVES_MAX, adresse_domicile,
                )
            else:
                # OK, ou statut d'erreur définitif (NOT_FOUND, ZERO_RESULTS,
                # INVALID_REQUEST...) : dans les deux cas on retourne la
                # réponse telle quelle, c'est à calculer_trajet de décider.
                return data

        # Backoff exponentiel avant la prochaine tentative (sauf après la dernière).
        if tentative < NB_TENTATIVES_MAX:
            time.sleep(BACKOFF_INITIAL_SECONDES * (2 ** (tentative - 1)))

    raise GoogleMapsAPIError(
        f"Échec après {NB_TENTATIVES_MAX} tentatives pour {adresse_domicile!r} : {derniere_erreur}"
    )


def _resultat_erreur(id_salarie: int, mode_api: str, code_erreur: str) -> dict:
    """Fabrique un résultat standardisé pour un cas d'erreur (pas d'exception levée)."""
    return {
        "id_salarie": id_salarie,
        "mode_transport": mode_api,
        "distance_km": None,
        "duree_estimee_min": None,
        "distance_eligible": False,
        "anomalie_declaration": False,
        "erreur": code_erreur,
    }


def calculer_trajet(id_salarie: int, adresse_domicile: str, moyen_deplacement: str,
                     api_key: str) -> dict | None:
    """
    Calcule la distance et l'éligibilité pour un salarié, selon son moyen de
    déplacement déclaré. Retourne None si le moyen de déplacement n'est pas
    un mode actif (ex: transports en commun, véhicule motorisé).

    Ne lève jamais d'exception pour un cas propre à un salarié (adresse
    manquante, adresse introuvable, format de réponse inattendu...) :
    retourne un dict avec "erreur" renseigné, pour que le pipeline continue
    sur les salariés suivants. Seule une erreur d'authentification/quota
    remonte sous forme d'exception GoogleMapsAuthError, car elle invalide
    tout le batch, pas un salarié isolé.
    """
    moyen = (moyen_deplacement or "").strip().lower()

    if not moyen:
        return None

    if "marche" in moyen or "running" in moyen or "course" in moyen:
        mode_api = "walking"
        seuil = SEUIL_KM_MARCHE_COURSE
    elif "vélo" in moyen or "velo" in moyen or "trottinette" in moyen:
        mode_api = "bicycling"
        seuil = SEUIL_KM_VELO_AUTRE
    else:
        # Transports en commun, véhicule thermique/électrique : non concerné
        return None

    adresse_domicile = (adresse_domicile or "").strip()
    if not adresse_domicile:
        return _resultat_erreur(id_salarie, mode_api, "ADRESSE_MANQUANTE")

    try:
        data = _appeler_distance_matrix(adresse_domicile, mode_api, api_key)
    except GoogleMapsAuthError:
        # Erreur bloquante pour tout le batch : on la laisse remonter telle
        # quelle, sans la transformer en simple résultat d'erreur.
        raise
    except GoogleMapsAPIError as e:
        logger.error("Échec définitif Google Maps pour salarié %s : %s", id_salarie, e)
        return _resultat_erreur(id_salarie, mode_api, "ERREUR_API_APRES_RETRY")

    if data.get("status") != "OK":
        return _resultat_erreur(id_salarie, mode_api, data.get("status", "STATUT_INCONNU"))

    try:
        rows = data.get("rows") or []
        if not rows or not rows[0].get("elements"):
            return _resultat_erreur(id_salarie, mode_api, "REPONSE_VIDE")

        element = rows[0]["elements"][0]
        statut_element = element.get("status")

        if statut_element != "OK":
            return _resultat_erreur(id_salarie, mode_api, statut_element or "STATUT_ELEMENT_INCONNU")

        distance_valeur = element["distance"]["value"]
        duree_valeur = element["duration"]["value"]
    except (KeyError, TypeError, IndexError) as e:
        # Format de réponse inattendu (champ manquant/renommé côté Google) :
        # on log et on renvoie une erreur plutôt que de laisser planter le pipeline.
        logger.error("Format de réponse Google Maps inattendu pour salarié %s : %s", id_salarie, e)
        return _resultat_erreur(id_salarie, mode_api, "FORMAT_REPONSE_INATTENDU")

    distance_km = round(distance_valeur / 1000, 2)
    duree_min = round(duree_valeur / 60)

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

    Si l'API renvoie une erreur d'authentification/quota (GoogleMapsAuthError),
    le batch s'arrête immédiatement : inutile d'enchaîner 160 appels avec une
    clé invalide, et ça laisse l'appelant (etl.py) décider quoi faire
    (alerte Slack, interruption propre du pipeline) plutôt que de planter
    en boucle sur chaque salarié.
    """
    resultats = []
    for _, row in df_salaries.iterrows():
        try:
            resultat = calculer_trajet(
                row["id_salarie"], row["adresse_domicile"], row["moyen_deplacement"], api_key
            )
        except GoogleMapsAuthError as e:
            logger.error(
                "Arrêt du calcul des trajets après %d salarié(s) traité(s) : %s",
                len(resultats), e,
            )
            raise

        if resultat is not None:
            resultats.append(resultat)
        time.sleep(pause_entre_appels)  # évite de saturer l'API sur 161 adresses

    return resultats
