"""
Watcher léger (polling) sur la table activites_sportives de Supabase.

Contrairement au CDC "bas niveau" (Debezium sur Neon, voir cdc_consumer.py),
ce script interroge Supabase à intervalle régulier pour détecter les
nouvelles activités insérées, et envoie un message de félicitation sur
Slack. Choisi pour la démo live de soutenance car connecté à la MÊME base
que Power BI (contrairement à Neon) : une seule insertion suffit à
démontrer la notification Slack ET la mise à jour du reporting (après
actualisation manuelle de Power BI).

Le vrai CDC bas niveau (capture depuis le WAL PostgreSQL via Debezium) reste
démontré séparément sur Neon (cdc_consumer.py), pour illustrer une
architecture de production plus avancée.

Usage : python src/watch_activites_supabase.py
"""

import time

import pandas as pd
from sqlalchemy import text

from db_utils import get_engine, log_event

INTERVALLE_SECONDES = 5


def recuperer_dernier_id(engine) -> int:
    with engine.connect() as conn:
        resultat = conn.execute(text("SELECT COALESCE(MAX(id_activite), 0) FROM activites_sportives"))
        return resultat.scalar()


def recuperer_nouvelles_activites(engine, dernier_id_connu: int) -> pd.DataFrame:
    query = text("""
        SELECT a.id_activite, a.id_salarie, a.sport, a.date_debut_activite,
               a.date_fin_activite, a.distance_m, a.commentaire,
               s.nom, s.prenom
        FROM activites_sportives a
        JOIN salaries s ON s.id_salarie = a.id_salarie
        WHERE a.id_activite > :dernier_id
        ORDER BY a.id_activite
    """)
    with engine.connect() as conn:
        return pd.read_sql(query, conn, params={"dernier_id": dernier_id_connu})


def formater_felicitation(row) -> str:
    """Construit un message façon 'Bravo Juliette Mendes ! Tu viens de
    courir 10,8 km en 46 min !', conforme à l'exemple de la note de
    cadrage."""
    duree_min = None
    if pd.notna(row["date_debut_activite"]) and pd.notna(row["date_fin_activite"]):
        delta = row["date_fin_activite"] - row["date_debut_activite"]
        duree_min = round(delta.total_seconds() / 60)

    distance_km = round(row["distance_m"] / 1000, 1) if pd.notna(row["distance_m"]) else None

    details = []
    if distance_km:
        details.append(f"{distance_km} km")
    if duree_min:
        details.append(f"{duree_min} min")
    details_str = f" ({', '.join(details)})" if details else ""

    message = f"🎉 Bravo {row['prenom']} {row['nom']} ! Nouvelle activité : {row['sport']}{details_str} !"

    commentaire = row.get("commentaire")
    if pd.notna(commentaire) and commentaire:
        message += f' ("{commentaire}")'

    return message


def surveiller():
    engine = get_engine()
    dernier_id = recuperer_dernier_id(engine)
    print(f"Surveillance de activites_sportives (Supabase) à partir de l'id {dernier_id}...")
    print(f"Intervalle de vérification : {INTERVALLE_SECONDES}s")

    log_event("INFO", "watch_supabase",
              "Démarrage de la surveillance des nouvelles activités (Supabase).")

    try:
        while True:
            nouvelles = recuperer_nouvelles_activites(engine, dernier_id)
            for _, row in nouvelles.iterrows():
                message = formater_felicitation(row)
                print(f"[NOUVELLE ACTIVITE] {message}")
                log_event("INFO", "nouvelle_activite", message, alerter_slack=True)
                dernier_id = max(dernier_id, row["id_activite"])

            time.sleep(INTERVALLE_SECONDES)

    except KeyboardInterrupt:
        print("\nArrêt de la surveillance.")
        log_event("INFO", "watch_supabase",
                  "Arrêt de la surveillance des nouvelles activités.")


if __name__ == "__main__":
    surveiller()
