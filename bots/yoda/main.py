import os
from shared.bot_features import BotWithFeatures

# Personnalité spécifique de Yoda
PROMPT = (
    "Tu es Maître Yoda. Tu parles en inversant l'ordre des mots (Sujet-Objet-Verbe). "
    "Tu es sage, énigmatique mais bienveillant. Tu donnes des conseils aux utilisateurs. "
    "Tu utilises souvent des métaphores sur la Force."
)

if __name__ == "__main__":
    bot = BotWithFeatures(
        bot_key="yoda",               # Clé pour le panel
        token_env_var="YODA_TOKEN",   # Token dans le .env
        system_prompt=PROMPT,
        persona_name="Maître Yoda"    # Nom pour l'affichage (Météo Yoda...)
    )
    bot.run_bot()