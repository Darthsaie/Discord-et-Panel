import discord
from openai import OpenAI

async def generate_recap(interaction: discord.Interaction, client: OpenAI, persona_name: str, limit: int = 30):
    channel = interaction.channel
    
    # 1. Récupération de l'historique
    messages_content = []
    try:
        async for msg in channel.history(limit=limit):
            if not msg.author.bot and msg.content:
                # On nettoie un peu (pseudo + contenu)
                messages_content.append(f"{msg.author.display_name}: {msg.content}")
    except Exception as e:
        await interaction.followup.send(f"❌ Impossible de lire l'historique : {e}")
        return

    if not messages_content:
        await interaction.followup.send("❌ Pas assez de messages récents pour un flash info.")
        return

    # On inverse pour avoir l'ordre chronologique
    conversation_text = "\n".join(reversed(messages_content))

    # 2. Génération du Flash Info
    prompt = (
        f"Tu es {persona_name}, présentateur vedette du Journal TV. "
        "Voici les dernières discussions sur ce canal Discord :\n\n"
        f"{conversation_text}\n\n"
        "Tâche : Fais un 'Flash Info' court, drôle et sarcastique résumant ce qu'il s'est passé. "
        "Moque-toi gentiment des participants. Utilise un ton journalistique exagéré. "
        "Commence par '🔴 FLASH INFO !' et finis par une punchline."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=400
        )
        recap_text = response.choices[0].message.content.strip()
        
        # 3. Envoi
        embed = discord.Embed(title="📺 LE JOURNAL DU SERVEUR", description=recap_text, color=0xFF0000)
        embed.set_footer(text=f"Présenté par {persona_name}")
        await interaction.followup.send(embed=embed)

    except Exception as e:
        print(f"Erreur Recap: {e}")
        await interaction.followup.send("Le prompteur est cassé (Erreur IA).")