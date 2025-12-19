from openai import OpenAI
import os
import time
import asyncio
import discord
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

fights = {}
results = {}

# Petit utilitaire pour répondre aux Slash Commands
async def smart_reply(interaction, text):
    # On utilise toujours followup car on fera un "defer" avant
    await interaction.followup.send(text)

def generate_fight_prompt():
    prompt = (
        "Génère un combat épique entre deux personnages célèbres ou fictifs, "
        "dans un style sérieux mais spectaculaire. Ne donne que le nom des deux combattants séparés par ' VS ', "
        "sans autre texte. Exemples : 'John Wick VS Arya Stark' ou 'Geralt de Riv VS Kratos'."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Erreur génération combat : {e}")
        return "Batman VS Iron Man"

async def start_fight(interaction, custom_fight=None):
    channel = interaction.channel
    channel_id = channel.id
    
    if channel_id in fights:
        await smart_reply(interaction, "Un combat est déjà en cours dans ce salon. Patiente.")
        return

    fight_text = custom_fight if custom_fight else generate_fight_prompt()
    
    fights[channel_id] = {
        "fight": fight_text,
        "votes": {},
        "start_time": time.time(),
        "channel": channel
    }

    # --- CHANGEMENT ICI : On ne parle plus que de /vote ---
    txt_annonce = (
        f"⚔️ **FIGHT CLUB** ⚔️\n"
        f"**{fight_text}**\n"
        f"👇 Pour voter, utilisez la commande :\n"
        f"### `/vote choix:<nom>`\n"
        f"⏳ Résultat dans 60 secondes..."
    )
    
    await smart_reply(interaction, txt_annonce)
    
    await asyncio.sleep(60)
    await announce_result(channel_id)

def register_vote(channel_id, voter, vote):
    if channel_id not in fights:
        return "Aucun combat en cours ici."

    fight = fights[channel_id]
    combatants = fight["fight"].lower().split(" vs ")
    vote_cleaned = vote.strip().lower()

    valid = False
    for c in combatants:
        if vote_cleaned in c or c in vote_cleaned:
            valid = True
            vote_cleaned = c 
            break
            
    if not valid:
        return f"Choix invalide. Le combat est : **{fight['fight']}**"

    fight["votes"][voter.id] = vote_cleaned
    return f"✅ Vote enregistré pour **{vote_cleaned.title()}** !"

async def announce_result(channel_id):
    if channel_id not in fights: return

    fight = fights[channel_id]
    channel = fight["channel"]
    votes = fight["votes"]

    if not votes:
        await channel.send("Aucun vote... Combat annulé par manque d'intérêt. 😒")
        del fights[channel_id]
        return

    count = {}
    for v in votes.values():
        count[v] = count.get(v, 0) + 1

    max_votes = max(count.values())
    winners = [name for name, v in count.items() if v == max_votes]
    fight_text = fight['fight']

    if len(winners) > 1:
        await channel.send(f"🤷 Égalité parfaite ! Pas de vainqueur aujourd'hui.")
        del fights[channel_id]
        return

    winner = winners[0]
    
    try:
        prompt = (
            f"Raconte la fin d'un combat entre {fight_text}. "
            f"Le gagnant est **{winner.title()}**. "
            f"Fais un récit court (3 phrases max), drôle et épique."
        )
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        result_text = response.choices[0].message.content.strip()
    except Exception:
        result_text = f"Le gagnant est **{winner.title()}** !"

    await channel.send(f"🏆 **RÉSULTAT** 🏆\n{result_text}")
    del fights[channel_id]