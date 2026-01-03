import sqlite3
import os

# Chemin vers ta base de données
DB_PATH = "panel.db"

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"❌ Base de données introuvable à : {DB_PATH}")
        return

    print(f"🔄 Connexion à {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 1. Ajout de la colonne 'platform'
    try:
        c.execute("ALTER TABLE guilds ADD COLUMN platform VARCHAR DEFAULT 'discord'")
        print("✅ Colonne 'platform' ajoutée (par défaut: 'discord').")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("ℹ️  Colonne 'platform' existe déjà.")
        else:
            print(f"❌ Erreur platform: {e}")

    # 2. Ajout de la colonne 'icon_url'
    try:
        c.execute("ALTER TABLE guilds ADD COLUMN icon_url VARCHAR")
        print("✅ Colonne 'icon_url' ajoutée.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("ℹ️  Colonne 'icon_url' existe déjà.")
        else:
            print(f"❌ Erreur icon_url: {e}")

    conn.commit()
    conn.close()
    print("🚀 Migration terminée ! Tes données sont sauves.")

if __name__ == "__main__":
    migrate()