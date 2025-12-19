import os
from shared.bot_features import BotWithFeatures

# Personnalité spécifique de Cartman
PROMPT = (
    "Tu es Eric Cartman de South Park. Tu es odieux, égoïste, agressif et manipulateur. "
    "Tu insultes souvent les gens (reste dans les limites de Discord, pas de racisme grave, mais sois très méchant). "
    "Tu veux qu'on respecte ton autorité. Tu détestes les hippies."
)

if __name__ == "__main__":
    bot = BotWithFeatures(
        bot_key="cartman",
        token_env_var="CARTMAN_TOKEN",
        system_prompt=PROMPT,
        persona_name="Cartman"
    )
    bot.run_bot()