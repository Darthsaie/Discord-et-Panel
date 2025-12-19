import os
from shared.bot_features import BotWithFeatures

PROMPT = (
    "Tu es Deadpool. Tu brises le 4eme mur. Tu es sarcastique, violent et drôle. "
    "Tu te moques des gens tout en leur donnant l'info. Ne parle pas de chimichangas"
)

if __name__ == "__main__":
    bot = BotWithFeatures(
        bot_key="deadpool",
        token_env_var="DEADPOOL_TOKEN",
        system_prompt=PROMPT,
        persona_name="Deadpool"
    )
    bot.run_bot()