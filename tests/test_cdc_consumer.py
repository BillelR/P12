"""
Tests unitaires : cdc_consumer.py

Vérifie le parsing des événements Debezium bruts (format Redis Streams) et
la génération des messages de félicitation, sans nécessiter de vraie
connexion Redis/Supabase.
"""

import json

import pytest

from cdc_consumer import formater_evenement, formater_felicitation


def _evenement_debezium(op: str, after: dict) -> dict:
    """Construit un événement Redis Stream tel que produit par le sink Redis
    de Debezium : un seul champ dont le NOM est la clé JSON sérialisée et la
    VALEUR est l'enveloppe {schema, payload}."""
    cle = json.dumps({"id_salarie": after.get("id_salarie")})
    valeur = json.dumps({
        "schema": {"type": "struct"},
        "payload": {"before": None, "after": after, "op": op, "ts_ms": 1_700_000_000_000},
    })
    return {cle: valeur}


class TestFormaterEvenementEligibilite:
    def test_mise_a_jour_eligibilite(self):
        event_data = _evenement_debezium("u", {
            "id_salarie": 42,
            "eligible_prime_mobilite": True,
            "eligible_jours_bien_etre": False,
        })
        message = formater_evenement("sportdata.public.eligibilite_avantages", event_data)

        assert "42" in message
        assert "True" in message
        assert "Mise à jour" in message

    def test_snapshot_initial_eligibilite(self):
        event_data = _evenement_debezium("r", {"id_salarie": 1, "eligible_prime_mobilite": False,
                                                  "eligible_jours_bien_etre": False})
        message = formater_evenement("sportdata.public.eligibilite_avantages", event_data)

        assert "Snapshot initial" in message


class TestFormaterFelicitation:
    def test_insertion_genere_message_de_felicitation(self):
        message = formater_felicitation("c", {
            "id_salarie": 2, "sport": "Running", "duree_minutes": 32, "distance_km": 5.2,
        }, id_salarie=2)

        assert message is not None
        assert "Bravo" in message
        assert "Running" in message
        assert "5.2 km" in message
        assert "32 min" in message

    def test_snapshot_initial_ne_genere_pas_de_felicitation(self):
        """Règle métier importante : on ne félicite pas rétroactivement sur
        les activités déjà existantes au démarrage de Debezium (évite le
        spam de notifications au premier lancement)."""
        message = formater_felicitation("r", {
            "id_salarie": 2, "sport": "Running", "duree_minutes": 32, "distance_km": 5.2,
        }, id_salarie=2)

        assert message is None

    def test_salarie_inconnu_utilise_libelle_generique(self):
        """Un id_salarie absent du mapping de démo doit quand même produire
        un message (pas de crash), avec un libellé générique."""
        message = formater_felicitation("c", {
            "id_salarie": 999, "sport": "Natation", "duree_minutes": 40, "distance_km": 1.5,
        }, id_salarie=999)

        assert message is not None
        assert "Salarié 999" in message

    def test_sport_sans_distance_omet_le_km(self):
        """Un sport sans distance pertinente (ex: musculation) ne doit pas
        afficher '0 km' ou une valeur incohérente : juste l'omettre."""
        message = formater_felicitation("c", {
            "id_salarie": 1, "sport": "Boxe", "duree_minutes": 45, "distance_km": None,
        }, id_salarie=1)

        assert "km" not in message
        assert "45 min" in message


class TestFormaterEvenementActivitesSportives:
    def test_nouvelle_activite_route_vers_felicitation(self):
        event_data = _evenement_debezium("c", {
            "id_salarie": 3, "sport": "Randonnée", "duree_minutes": 120, "distance_km": 8.0,
        })
        message = formater_evenement("sportdata.public.activites_sportives", event_data)

        assert "Bravo" in message
        assert "Randonnée" in message


def test_evenement_vide_ne_leve_pas_exception():
    message = formater_evenement("sportdata.public.salaries", {})
    assert "vide" in message.lower()


def test_json_invalide_ne_leve_pas_exception():
    message = formater_evenement("sportdata.public.salaries", {"cle": "pas du json valide {{{"})
    assert "non parsable" in message.lower()
