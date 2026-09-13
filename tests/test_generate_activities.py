"""
Tests unitaires : generate_activities.py

Vérifie les propriétés statistiques et structurelles de la génération de
données simulées (fenêtre temporelle, cohérence des dates, commentaires).
"""

from datetime import datetime

import pytest

from generate_activities import (
    generer_commentaire,
    generer_activites_pour_salarie,
    DATE_DEBUT,
    DATE_FIN,
    SPORT_PROFILES,
    PROBA_COMMENTAIRE,
)


class TestGenererCommentaire:
    def test_frequence_commentaire_proche_de_la_probabilite_cible(self):
        """Sur un grand nombre de tirages, la proportion de commentaires
        générés doit être proche de PROBA_COMMENTAIRE (tolérance large pour
        éviter un test flaky)."""
        resultats = [generer_commentaire("Runing") for _ in range(2000)]
        proportion_avec_commentaire = sum(1 for r in resultats if r is not None) / len(resultats)

        assert abs(proportion_avec_commentaire - PROBA_COMMENTAIRE) < 0.05

    def test_commentaire_randonnee_est_thematique(self):
        """Force le tirage à toujours générer un commentaire pour vérifier
        que les randonnées ont bien un pool de commentaires dédié."""
        resultats = set()
        for _ in range(200):
            c = generer_commentaire("Randonnée")
            if c:
                resultats.add(c)
        # Au moins un commentaire spécifique randonnée doit être apparu
        assert any("spot" in c.lower() or "dénivelé" in c.lower() or "vue" in c.lower()
                   or "guilhem" in c.lower() for c in resultats)


class TestGenererActivitesPourSalarie:
    def test_toutes_les_dates_dans_la_fenetre_12_mois(self):
        activites = generer_activites_pour_salarie(id_salarie=1, sport="Runing")

        for activite in activites:
            date_debut = datetime.strptime(activite["date_debut_activite"], "%Y-%m-%d %H:%M:%S")
            assert DATE_DEBUT <= date_debut <= DATE_FIN

    def test_date_fin_toujours_apres_date_debut(self):
        activites = generer_activites_pour_salarie(id_salarie=1, sport="Football")

        for activite in activites:
            debut = datetime.strptime(activite["date_debut_activite"], "%Y-%m-%d %H:%M:%S")
            fin = datetime.strptime(activite["date_fin_activite"], "%Y-%m-%d %H:%M:%S")
            assert fin > debut

    def test_distance_none_pour_sport_sans_distance(self):
        """Ex: Football n'a pas de distance pertinente dans SPORT_PROFILES."""
        activites = generer_activites_pour_salarie(id_salarie=1, sport="Football")

        assert all(a["distance_m"] is None for a in activites)

    def test_distance_renseignee_pour_sport_avec_distance(self):
        activites = generer_activites_pour_salarie(id_salarie=1, sport="Runing")

        assert len(activites) > 0
        assert all(a["distance_m"] is not None for a in activites)
        profil = SPORT_PROFILES["Runing"]
        assert all(profil["distance_m"][0] <= a["distance_m"] <= profil["distance_m"][1]
                   for a in activites)

    def test_toutes_les_activites_ont_le_bon_id_salarie(self):
        activites = generer_activites_pour_salarie(id_salarie=42, sport="Tennis")
        assert all(a["id_salarie"] == 42 for a in activites)

    def test_sport_inconnu_leve_key_error(self):
        """Un sport absent de SPORT_PROFILES doit échouer explicitement
        plutôt que de générer silencieusement des données incohérentes."""
        with pytest.raises(KeyError):
            generer_activites_pour_salarie(id_salarie=1, sport="SportInexistant")


def test_tous_les_sports_profiles_ont_les_champs_requis():
    """Contrôle de cohérence de la table de configuration elle-même :
    chaque profil doit avoir freq_annuelle_moy, duree et distance_m."""
    for sport, profil in SPORT_PROFILES.items():
        assert "freq_annuelle_moy" in profil, f"{sport} : freq_annuelle_moy manquant"
        assert "duree" in profil, f"{sport} : duree manquant"
        assert "distance_m" in profil, f"{sport} : distance_m manquant"
        assert profil["freq_annuelle_moy"] > 0, f"{sport} : fréquence doit être positive"
