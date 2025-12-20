import os
import json
import asyncio
import re
import traceback
import discord
import random
from openai import OpenAI

# Fichier de sauvegarde des scores
SCORE_FILE = "shared/leaderboard.json"

# Liste de thèmes
THEMES = [
    "Cinéma & Séries", "Histoire de France", "Histoire du Monde", "Géographie", 
    "Sciences & Nature", "Jeux Vidéo (Rétro & Moderne)", "Technologie & Geek", 
    "Littérature & BD", "Musique", "Sport", "Animaux", "Astronomie", 
    "Culture Internet & Memes", "Mythologie", "Inventions"
]

DIFFICULTES = ["Facile", "Moyenne", "Difficile", "Expert", "Absurde"]

def load_scores():
    if not os.path.exists(SCORE_FILE): return {}
    try:
        with open(SCORE_FILE, "r") as f: return json.load(f)
    except: return {}

def save_score(user_id, points=1):
    scores = load_scores()
    uid = str(user_id)
    scores[uid] = scores.get(uid, 0) + points
    with open(SCORE_FILE, "w") as f: json.dump(scores, f)
    return scores[uid]

def get_top_scores(limit=5):
    scores = load_scores()
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
    return sorted_scores

# --- MOTEUR DU JEU ---
quiz_sessions = {} 

async def start_quiz(interaction, client: OpenAI, persona_name):
    channel_id = interaction.channel_id
    if channel_id in quiz_sessions and quiz_sessions[channel_id].get("active"):
        await interaction.followup.send("❌ Un quiz est déjà en cours !")
        return

    theme_du_jour = random.choice(THEMES)
    niveau = random.choice(DIFFICULTES)

    try:
        prompt = (
            f"Tu es {persona_name}. Pose une question de culture générale sur le thème : **{theme_du_jour}** (Niveau : {niveau}). "
            "Sois original. Donne la réponse juste après. "
            "Format OBLIGATOIRE :\n"
            "Question: [Ta question ici]\n"
            "Réponse: [La réponse courte ici]"
        )
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.95
        )
        
        text = response.choices[0].message.content.strip()
        print(f"[DEBUG QUIZ] Thème: {theme_du_jour} | Q/R: {text}") 

        # Parsing
        pattern_newline = r"(?:Question|Q)\s*[:\.]\s*(.+?)\s*(?:\n|\|\||\|)\s*(?:Réponse|Reponse|R)\s*[:\.]\s*(.+)"
        match = re.search(pattern_newline, text, re.IGNORECASE | re.DOTALL)

        if match:
            question_part = match.group(1).strip()
            answer_part = match.group(2).strip()
        else:
            if "Réponse:" in text:
                parts = text.split("Réponse:")
                question_part = parts[0].replace("Question:", "").strip()
                answer_part = parts[1].strip()
            else:
                await interaction.followup.send("J'ai bégayé... Relance !")
                return

        # On sauvegarde aussi la question pour le contexte du clash
        quiz_sessions[channel_id] = {
            "question": question_part,
            "answer": answer_part,
            "active": True
        }

        embed = discord.Embed(
            title=f"🎙️ QUIZ : {theme_du_jour}", 
            description=f"❓ **{question_part}**", 
            color=0xFFA500
        )
        embed.set_footer(text=f"Niveau : {niveau} | Répondez dans le chat !")
        
        await interaction.followup.send(embed=embed)

    except Exception as e:
        print(f"Erreur Quiz : {e}")
        await interaction.followup.send("Oups, mon cerveau a grillé.")

async def check_answer(message, client: OpenAI, persona_name):
    try:
        cid = message.channel.id
        if cid not in quiz_sessions or not quiz_sessions[cid]["active"]:
            return False

        if message.content.startswith(("!", "/")): return False

        session = quiz_sessions[cid]
        user_msg = message.content.strip()
        correct_answer = session["answer"]
        original_question = session.get("question", "Question inconnue")

        if len(user_msg) > 100: return False 

        # --- VALIDATION STRICTE (Juge) ---
        # On sépare le rôle : ici c'est un Juge Impartial, pas le persona du bot.
        prompt = (
            f"Tu es un juge de quiz impartial.\n"
            f"Question posée : '{original_question}'\n"
            f"Réponse attendue : '{correct_answer}'\n"
            f"Réponse du joueur : '{user_msg}'\n\n"
            "Tâche : La réponse du joueur est-elle correcte ?\n"
            "Règles :\n"
            "1. Accepte les fautes d'orthographe légères.\n"
            "2. Accepte les réponses partielles si elles sont sans équivoque (ex: 'Bonaparte' pour 'Napoléon Bonaparte').\n"
            "3. REFUSE catégoriquement les mauvaises réponses ou les réponses proches mais fausses (ex: 'Louis 16' pour 'Louis 14' est NON).\n"
            "4. REFUSE si le joueur répond à côté.\n\n"
            "Réponds uniquement par 'OUI' ou 'NON'."
        )

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=5,
            temperature=0.0 # Zéro créativité, pure logique
        )
        verdict = response.choices[0].message.content.strip().upper()
        
        # --- CAS 1 : GAGNÉ ---
        if "OUI" in verdict:
            quiz_sessions[cid]["active"] = False
            new_score = save_score(message.author.id, 10)
            
            congrats_prompt = f"Tu es {persona_name}. Félicite {message.author.display_name} pour la bonne réponse '{correct_answer}'."
            res = client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": congrats_prompt}])
            bravo = res.choices[0].message.content.strip()

            embed = discord.Embed(title="✅ BONNE RÉPONSE !", description=bravo, color=0x00FF00)
            embed.add_field(name="Score Total", value=f"🏆 **{new_score} pts**")
            embed.add_field(name="Classement", value="[Voir le Leaderboard](https://panel.4ubot.fr/leaderboard)", inline=False)
            
            await message.channel.send(embed=embed)
            return True 
            
        # --- CAS 2 : RATÉ (Avec Clash sécurisé) ---
        else:
            if len(user_msg) > 2:
                # On ne donne PAS la bonne réponse à l'IA pour le clash pour éviter le spoil
                roast_prompt = (
                    f"Tu es {persona_name}. Le joueur {message.author.display_name} a répondu '{user_msg}' à la question '{original_question}'. "
                    "C'est faux. Moque-toi de lui gentiment sur sa bêtise ou son ignorance. "
                    "ATTENTION : Tu ne connais pas la vraie réponse, donc ne la donne surtout pas !"
                )
                try:
                    res = client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[{"role": "user", "content": roast_prompt}],
                        max_tokens=80
                    )
                    roast = res.choices[0].message.content.strip()
                    await message.reply(f"❌ {roast}")
                except:
                    pass
            
            return False 

    except Exception as e:
        print(f"Erreur check quiz: {e}")
    
    return False