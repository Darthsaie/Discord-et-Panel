# Darthsaie Bots — Panel PRO + NO‑AUTO

Ce pack modifie les 4 bots (Arthur, Cartman, Deadpool, Yoda) pour **ne plus envoyer de messages spontanés** :
- pas de message dans #général
- pas de message d’accueil automatique
- réponse **uniquement** quand ils sont **mentionnés** (`@Bot`) ou lorsqu’une **commande/mini‑jeu** est déclenché (`!quiz`, `!duel`, etc.).

Il ajoute aussi un **panel web professionnel** avec connexion **Discord OAuth2**, **essai 15 jours**, et **abonnement par bot et par serveur**. Les bots respectent le panel : ils **ignorent** les serveurs **non abonnés**.

---

## 1) Dossiers ajoutés
- `panel_pro/` — nouvelle application Flask (auth Discord, base SQLite, API pour les bots)
- `README_PANEL_PRO.md` — ce fichier

## 2) Variables d’environnement
Ajoute/complète ces variables dans `.env` (ou crée un `.env` à partir de l’exemple) :

```
# Panel (sécurité)
SECRET_KEY=remplace_moi
PANEL_API_TOKEN=remplace_moi_long_et_random

# Discord OAuth (connexion au panel)
DISCORD_CLIENT_ID=...
DISCORD_CLIENT_SECRET=...
OAUTH_REDIRECT_URI=http://localhost:5000/callback
TRIAL_DAYS=15

# Bots -> Panel (déjà injecté par docker-compose)
# BOT_KEY, PANEL_API_URL, PANEL_API_TOKEN
```

> ⚠️ **Sécurité** : Ne partage jamais ton `.env`. Pense à **rotater** les tokens Discord affichés dans l’archive originale si elle a circulé.

Un `.env.example` a été généré dans `panel_pro` pour référence.

## 3) Lancer avec Docker
Pré‑requis : Docker & Docker Compose.

```bash
docker compose up -d --build
```

- Panel accessible sur **http://localhost:5000**
- Connecte‑toi avec Discord → va au **Dashboard** → **Active un essai 15 jours** pour un bot et un serveur.
- Les bots vont automatiquement **rafraîchir la liste des serveurs autorisés** toutes les 5 minutes.

## 4) Comment ça marche côté bots
Chaque bot récupère périodiquement :
```
GET /api/bot/config/<bot_key>?token=PANEL_API_TOKEN
→ { "allowed_guild_ids": [1234567890, ...] }
```
Si un message provient d’un serveur **non autorisé**, il est **ignoré** (sauf en **DM**, toujours autorisé).

## 5) Front‑office (Panel)
- **Login Discord** (scopes: `identify`, `guilds`, `email`)
- **Dashboard** : liste tes guilds & les bots
- Bots **grisés** si non actifs, **activer l’essai** en 1 clic (15 jours par défaut)
- API sécurisée par `PANEL_API_TOKEN` pour les bots

## 6) Paiement mensuel
Le squelette est prêt pour brancher un provider (Stripe, LemonSqueezy, Paddle). Pour aller vite, on a **essai + activation manuelle** :
- À la fin de l’essai, passe l’abonnement à `active` en BDD (ou branche un vrai paiement).
- Table `subscriptions` : `status` = `trial|active|canceled`, avec `trial_until`.

## 7) Ajout de nouveaux personnages
- Ajoute un bot (dossier + image + Dockerfile)
- Ajoute une entrée dans la table `bot_types` (ou laisse le panel la créer)
- La logique d’autorisation est **générique** (clé du bot = nom du dossier).

## 8) Migration sans Docker (dev)
```bash
cd panel_pro
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export FLASK_APP=app.py
python app.py
```

---

**Fait pour toi, Darthsaie 🫶 — NO‑AUTO activé partout.**
