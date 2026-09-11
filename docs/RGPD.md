# Conformité RGPD — Sport Data Solution

Ce POC traite des données personnelles de salariés (identité, adresse, salaire,
pratique sportive). Voici le cadrage RGPD retenu.

## 1. Finalité du traitement
Déterminer l'éligibilité des salariés à deux avantages (prime de mobilité, jours
bien-être) sur la base de données de trajet domicile-travail et d'activité sportive.

## 2. Base légale
Intérêt légitime de l'employeur (gestion d'un avantage social facultatif) +
consentement implicite du salarié qui choisit de déclarer son mode de transport
et sa pratique sportive. En production, un consentement explicite et une
information préalable (via la politique de confidentialité RH) seraient requis.

## 3. Minimisation des données
- L'adresse complète du domicile n'est utilisée que pour l'appel à l'API Google
  Maps (calcul de distance) ; elle n'est **pas dupliquée** dans la table de
  résultats `eligibilite_avantages`, qui ne conserve que la distance calculée
  (donnée dérivée, non identifiante en elle-même).
- Aucune donnée de santé n'est collectée : le type de sport pratiqué n'est pas
  une donnée de santé au sens RGPD (contrairement à une donnée médicale), mais
  reste traité avec la même rigueur de minimisation.

## 4. Durée de conservation
- Données RH et sportives : durée du contrat de travail + délai légal de
  conservation des données de paie (proposé : 5 ans après la fin du contrat).
- Table `logs_monitoring` : proposé 90 jours glissants (purge automatique à
  prévoir en production, non implémentée dans ce POC).

## 5. Droits des personnes
Dans un contexte de production, les salariés devraient pouvoir exercer leurs
droits d'accès, de rectification et d'opposition sur ces données via le service
RH. Non implémenté dans ce POC (hors périmètre technique), mais à documenter
dans la politique de confidentialité interne.

## 6. Sécurité
- Toutes les clés et connexions (Supabase, Google Maps, Slack) sont stockées
  dans un fichier `.env` non versionné (voir `.gitignore`).
- La connexion à Supabase se fait via une chaîne PostgreSQL chiffrée (SSL).
- Recommandation en production : activer Row Level Security (RLS) sur les
  tables contenant des données personnelles, désactivé ici uniquement pour
  simplifier le développement du POC.

## 7. Limites de ce POC
Ce document présente le cadrage RGPD attendu pour une mise en production réelle.
Le POC lui-même, à visée pédagogique, utilise des données réelles fournies dans
un cadre de formation : elles ne doivent pas être exposées publiquement (le
dépôt GitHub associé doit rester privé, ou les fichiers `data/raw/` doivent être
exclus si le dépôt est rendu public).
