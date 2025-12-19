import asyncio
import discord
import re
from openai import OpenAI

# Personas avec instructions renforcées
PERSONAS = {
    "homer": {
        "name": "Homer Simpson",
        "prompt": "Tu es Homer Simpson. Tu es bête, paresseux et gourmand. Tu parles TOUJOURS en français. Ne mets JAMAIS ton nom au début de la réponse. Tu penses à la bière Duff et aux donuts. Fais ton cri 'D'oh!'.",
        "color": 0xFFD700,
    },
    "cartman": {
        "name": "Eric Cartman",
        "prompt": "Tu es Eric Cartman de South Park. Tu es odieux, agressif et manipulateur. Tu parles TOUJOURS en français. Ne mets JAMAIS ton nom au début de la réponse. Tu insultes les gens (reste dans les limites Discord). Respecte mon autorité !",
        "color": 0xFF0000,
    },
    "deadpool": {
        "name": "Deadpool",
        "prompt": "Tu es Deadpool. Tu brises le 4eme mur. Tu es sarcastique, violent et drôle. Tu parles TOUJOURS en français. Ne mets JAMAIS ton nom au début de la réponse. Pas de chimichangas.",
        "color": 0x8B0000,
    },
    "yoda": {
        "name": "Maître Yoda",
        "prompt": "Tu es Maître Yoda. Tu parles en inversant l'ordre des mots (Sujet-Objet-Verbe). Tu parles TOUJOURS en français. Ne mets JAMAIS ton nom au début de la réponse. Tu es sage.",
        "color": 0x00FF00,
    }
}

async def generate_reply(client: OpenAI, model_name, system_prompt, history, context_instruction, bot_name):
    """Génère une réplique et nettoie le résultat."""
    messages = [{"role": "system", "content": system_prompt + " IMPÉRATIF : Ne commence PAS ta phrase par ton nom."}] + history
    messages.append({"role": "user", "content": context_instruction})
    
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.9,
            max_tokens=300,        # <-- AUGMENTÉ pour éviter les phrases coupées
            presence_penalty=0.6,  # Évite de répéter les mêmes sujets
            frequency_penalty=0.3  # Évite de répéter les mêmes mots
        )
        content = response.choices[0].message.content.strip()
        
        # --- NETTOYAGE PUISSANT DU NOM ---
        # Enlève "Name:", "**Name**:", "Name :", etc.
        pattern = r"^[\*]*" + re.escape(bot_name) + r"[\*]*\s*:\s*"
        content = re.sub(pattern, "", content, flags=re.IGNORECASE).strip()
        
        return content
    except Exception as e:
        print(f"Erreur OpenAI Debate: {e}")
        return "Grmmbll... (Bug cerveau)"

async def run_debate(interaction: discord.Interaction, client: OpenAI, model_name: str, topic: str, bot1_key: str, bot2_key: str, rounds: int = 3):
    b1 = PERSONAS.get(bot1_key)
    b2 = PERSONAS.get(bot2_key)
    
    if not b1 or not b2:
        await interaction.followup.send("❌ Bots invalides.")
        return

    # Annonce
    embed_intro = discord.Embed(title="🥊 CLASH DE TITANS", description=f"Sujet : **{topic}**", color=0x99AAB5)
    embed_intro.add_field(name="Coin Gauche", value=b1['name'], inline=True)
    embed_intro.add_field(name="Coin Droit", value=b2['name'], inline=True)
    await interaction.followup.send(embed=embed_intro)

    shared_history = [] 
    
    for i in range(rounds):
        is_last_round = (i == rounds - 1)
        
        # --- TOUR DU BOT 1 ---
        async with interaction.channel.typing():
            await asyncio.sleep(4)
            
            if i == 0:
                instruction = f"Le débat commence sur : '{topic}'. Donne ton avis tranché. Sois court et percutant. Ne mets pas ton nom au début."
            elif is_last_round:
                last_reply = shared_history[-1]['content']
                instruction = f"{b2['name']} a dit : \"{last_reply}\". C'est ta dernière chance ! Lance une punchline finale pour clore le débat. Ne mets pas ton nom au début."
            else:
                last_reply = shared_history[-1]['content']
                instruction = f"{b2['name']} a dit : \"{last_reply}\". Contredis-le avec un nouvel argument absurde ou une attaque personnelle. Ne répète pas ce que tu as déjà dit."

            reply = await generate_reply(client, model_name, b1['prompt'], shared_history, instruction, b1['name'])
            
            embed = discord.Embed(description=reply, color=b1['color'])
            embed.set_author(name=b1['name'])
            await interaction.channel.send(embed=embed)
            shared_history.append({"role": "assistant", "content": f"{b1['name']}: {reply}"})

        # --- TOUR DU BOT 2 ---
        async with interaction.channel.typing():
            await asyncio.sleep(4)
            
            last_reply = shared_history[-1]['content']
            
            if is_last_round:
                instruction = f"{b1['name']} vient de conclure par : \"{last_reply}\". Avoir le dernier mot, tu dois ! Finis ce débat avec une phrase culte ou une insulte finale. Ne mets pas ton nom au début."
            else:
                instruction = f"{b1['name']} a dit : \"{last_reply}\". Réponds-lui sur le sujet '{topic}'. Il a tort ! Trouve un angle d'attaque différent."
            
            reply = await generate_reply(client, model_name, b2['prompt'], shared_history, instruction, b2['name'])
            
            embed = discord.Embed(description=reply, color=b2['color'])
            embed.set_author(name=b2['name'])
            await interaction.channel.send(embed=embed)
            shared_history.append({"role": "assistant", "content": f"{b2['name']}: {reply}"})

    await interaction.channel.send(f"🏁 **Fin du débat !** Qui a gagné ? Réagissez !")