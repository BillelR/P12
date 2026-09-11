"""
Utilitaires partagés : connexion Supabase, logging vers la table logs_monitoring,
et envoi d'alertes Slack pour les événements importants (erreurs, fin de pipeline).
"""

import os
import time
from contextlib import contextmanager

import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

SUPABASE_DB_URL = os.environ.get("SUPABASE_DB_URL")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")


def get_engine():
    """Crée (une seule fois par process) le moteur SQLAlchemy vers Supabase."""
    if not SUPABASE_DB_URL:
        raise RuntimeError(
            "SUPABASE_DB_URL manquant. Vérifie que ton fichier .env existe "
            "et contient bien cette variable (voir .env.example)."
        )
    return create_engine(SUPABASE_DB_URL)


def log_event(niveau: str, etape: str, message: str,
              nb_lignes_traitees: int = None, duree_secondes: float = None,
              alerter_slack: bool = False):
    """
    Écrit un événement dans la table logs_monitoring, et optionnellement
    envoie une alerte Slack (à utiliser pour les erreurs ou les fins de run).

    niveau : "INFO", "WARNING" ou "ERROR"
    """
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO logs_monitoring
                    (niveau, etape, message, nb_lignes_traitees, duree_secondes)
                VALUES
                    (:niveau, :etape, :message, :nb_lignes, :duree)
            """),
            {
                "niveau": niveau,
                "etape": etape,
                "message": message,
                "nb_lignes": nb_lignes_traitees,
                "duree": duree_secondes,
            },
        )

    print(f"[{niveau}] {etape} — {message}")

    if alerter_slack and SLACK_WEBHOOK_URL:
        send_slack_alert(niveau, etape, message)


def send_slack_alert(niveau: str, etape: str, message: str):
    """Envoie une notification Slack via le webhook configuré (best-effort)."""
    if not SLACK_WEBHOOK_URL:
        return

    emoji = {"INFO": ":white_check_mark:", "WARNING": ":warning:", "ERROR": ":x:"}.get(niveau, ":information_source:")
    payload = {
        "text": f"{emoji} *[{niveau}] {etape}*\n{message}"
    }
    try:
        requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=5)
    except requests.RequestException as e:
        # On ne bloque jamais le pipeline pour un échec de notification Slack
        print(f"(Slack non joignable : {e})")


@contextmanager
def timed_step(etape: str):
    """Context manager pratique pour chronométrer une étape et logger sa durée."""
    debut = time.time()
    yield
    duree = time.time() - debut
    print(f"⏱  {etape} terminé en {duree:.2f}s")
