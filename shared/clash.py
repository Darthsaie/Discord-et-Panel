import discord
from openai import OpenAI

# Vérifie que le nom après "def" est bien "clash_user"
async def clash_user(interaction: discord.Interaction, client: OpenAI, persona_name: str, target: discord.User):
    # Sécurité
    if target.id == interaction.user.id:
        await interaction.followup.send("Tu veux te clasher toi-même ? T'es maso ou quoi ?")
        return

    if target.id == interaction.client.user.id:
        await interaction.followup.send("Moi ? Essaie même pas, je suis codé pour être intouchable.")
        return

    prompt = (
        f"Tu es {persona_name}. L'utilisateur {interaction.user.display_name} te demande de clasher "
        f"l'utilisateur {target.display_name}. "
        "Fais une attaque personnelle drôle, créative et cinglante. "
        "Reste dans les limites de l'humour. Fais court."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=150
        )
        roast = response.choices[0].message.content.strip()
        
        embed = discord.Embed(description=f"💥 **{target.mention}, {roast}**", color=0x000000)
        embed.set_footer(text=f"Une offrande de {interaction.user.display_name}")
        
        await interaction.followup.send(content=target.mention, embed=embed)

    except Exception as e:
        print(f"Erreur Clash: {e}")
        await interaction.followup.send(f"Désolé, j'ai bégayé en essayant de l'insulter.")