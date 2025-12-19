import os
from shared.bot_features import BotWithFeatures

# Personnalité spécifique de Homer
PROMPT = (
    "Tu es Homer Simpson. Tu es bête, paresseux et gourmand. "
    "Tu penses tout le temps à la bière Duff et aux donuts. "
    "Tu fais souvent ton cri signature 'D'oh!'. Tu es sympathique mais incompétent."
)

if __name__ == "__main__":
    bot = BotWithFeatures(
        bot_key="homer",
        token_env_var="HOMER_TOKEN",
        system_prompt=PROMPT,
        persona_name="Homer"
    )
    bot.run_bot()