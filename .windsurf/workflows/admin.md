---
description: Accès rapide au panel admin
---

# Accès Panel Admin

## URL d'accès
- **URL principale**: `http://localhost:5000/admin` (recommandé)
- **URL directe**: `http://localhost:5000/admin/subs-v2`

## Fonctionnalités
- Gestion des abonnements Discord et Twitch
- Création, modification, suppression d'abonnements
- Filtres par statut (actifs, essais, inactifs, VIP)
- Export CSV
- Synchronisation Stripe
- Graphiques et statistiques en temps réel

## Actions rapides
- Redémarrage du service: `sudo docker-compose restart panel`
- Logs du service: `sudo docker-compose logs panel --tail=20`