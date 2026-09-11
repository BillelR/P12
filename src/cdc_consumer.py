"""
Consommateur des événements CDC (Change Data Capture) capturés par Debezium
Server et publiés dans Redis Streams.
"""

import json
import os

import redis
from dotenv import load_dotenv

from db_utils import log_event

load_dotenv()

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))

STREAMS_SURVEILLES = [
    "sportdata.public.salaries",
    "sportdata.public.eligibilite_avantages",
    "sportdata.public.activites_sportives",
]

PRENOMS_DEMO = {1: "Julie", 2: "Karim", 3: "Sophie"}


def formater_evenement(nom_stream: str, event_data: dict) -> str:
    try:
        if not event_data:
            return f"Événement vide reçu sur {nom_stream}"

        value_json = next(iter(event_data.values()))
        enveloppe = json.loads(value_json)
        payload = enveloppe.get("payload", {})

        op = payload.get("op")
        after = payload.get("after") or {}
        id_salarie = after.get("id_salarie", "?")

        libelles_op = {"c": "Nouvelle ligne", "u": "Mise à jour", "d": "Suppression", "r": "Snapshot initial"}
        libelle = libelles_op.get(op, op)

        if "eligibilite_avantages" in nom_stream:
            eligible_bien_etre = after.get("eligible_jours_bien_etre")
            eligible_prime = after.get("eligible_prime_mobilite")
            return (f"{libelle} — salarié {id_salarie} : "
                    f"éligible prime mobilité = {eligible_prime}, "
                    f"éligible jours bien-être = {eligible_bien_etre}")

        if "activites_sportives" in nom_stream:
            return formater_felicitation(op, after, id_salarie)

        return f"{libelle} — salarié {id_salarie} sur {nom_stream}"

    except (json.JSONDecodeError, AttributeError, StopIteration) as e:
        return f"Événement reçu sur {nom_stream} (non parsable : {e})"


def formater_felicitation(op: str, after: dict, id_salarie) -> str:
    if op == "r":
        return None

    prenom = PRENOMS_DEMO.get(id_salarie, f"Salarié {id_salarie}")
    sport = after.get("sport", "une activité")
    duree = after.get("duree_minutes")
    distance = after.get("distance_km")

    details = []
    if distance:
        details.append(f"{distance} km")
    if duree:
        details.append(f"{duree} min")
    details_str = f" ({', '.join(details)})" if details else ""

    return f"🎉 Bravo {prenom} ! Nouvelle activité enregistrée : {sport}{details_str}."


def ecouter_streams():
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True,
                     socket_timeout=10, socket_connect_timeout=10)

    print(f"Connexion à Redis {REDIS_HOST}:{REDIS_PORT}...")
    print(f"Écoute des streams : {STREAMS_SURVEILLES}")

    dernieres_positions = {stream: "$" for stream in STREAMS_SURVEILLES}

    log_event("INFO", "cdc_consumer", "Démarrage de l'écoute des événements CDC (Debezium/Redis).")

    try:
        while True:
            try:
                resultats = r.xread(dernieres_positions, block=5000, count=10)
            except redis.exceptions.TimeoutError:
                continue

            for nom_stream, evenements in resultats:
                for event_id, event_data in evenements:
                    message = formater_evenement(nom_stream, event_data)
                    dernieres_positions[nom_stream] = event_id

                    if message is None:
                        continue

                    print(f"[CDC] {message}")

                    if "eligibilite_avantages" in nom_stream or "activites_sportives" in nom_stream:
                        log_event("INFO", "cdc_eligibilite", message, alerter_slack=True)

    except KeyboardInterrupt:
        print("\nArrêt du consommateur CDC.")
        log_event("INFO", "cdc_consumer", "Arrêt de l'écoute des événements CDC.")


if __name__ == "__main__":
    ecouter_streams()