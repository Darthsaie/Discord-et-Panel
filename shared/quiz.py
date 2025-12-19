import os
import json
import asyncio
import re
import traceback
import discord
from openai import OpenAI

# Fichier de sauvegarde des scores
SCORE_FILE = "shared/leaderboard.json"

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

    try:
        # Prompt plus explicite sur le format
        prompt = (
            f"Tu es {persona_name}. Pose une question de culture générale (cinéma, littérature, histoire, geek) avec sa réponse. "
            "Format OBLIGATOIRE :\n"
            "Question: [Ta question ici]\n"
            "Réponse: [La réponse courte ici]"
        )
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9
        )
        
        text = response.choices[0].message.content.strip()
        print(f"[DEBUG QUIZ] Texte reçu de l'IA : \n{text}") 

        # --- PARSING INTELLIGENT (Multi-formats) ---
        # 1. On essaie le format "Question: ... Réponse: ..." (avec saut de ligne)
        pattern_newline = r"(?:Question|Q)\s*[:\.]\s*(.+?)\s*(?:\n|\|\||\|)\s*(?:Réponse|Reponse|R)\s*[:\.]\s*(.+)"
        match = re.search(pattern_newline, text, re.IGNORECASE | re.DOTALL)

        if match:
            question_part = match.group(1).strip()
            answer_part = match.group(2).strip()
        else:
            # 2. Fallback bourrin : on coupe au mot "Réponse"
            if "Réponse:" in text:
                parts = text.split("Réponse:")
                question_part = parts[0].replace("Question:", "").strip()
                answer_part = parts[1].strip()
            elif "Reponse:" in text:
                parts = text.split("Reponse:")
                question_part = parts[0].replace("Question:", "").strip()
                answer_part = parts[1].strip()
            elif "||" in text:
                parts = text.split("||")
                question_part = parts[0].strip()
                answer_part = parts[1].strip()
            else:
                # Échec total -> on annule pour ne pas bugger le jeu
                print("[QUIZ ERROR] Format non reconnu.")
                await interaction.followup.send("Mon cerveau a raté la question... Relance !")
                return

        # Sauvegarde
        quiz_sessions[channel_id] = {"answer": answer_part, "active": True}
        print(f"[DEBUG QUIZ] Q: {question_part} | A: {answer_part}") # Vérifie tes logs ici !

        embed = discord.Embed(
            title=f"🎙️ QUIZ avec {persona_name}", 
            description=f"❓ **{question_part}**", 
            color=0xFFA500
        )
        embed.set_footer(text="Répondez directement dans le chat !")
        
        await interaction.followup.send(embed=embed)

    except Exception as e:
        error_msg = f"⚠️ **ERREUR TECHNIQUE** : {str(e)}\n```python\n{traceback.format_exc()[-1900:]}```"
        print(error_msg)
        await interaction.followup.send(error_msg)

async def check_answer(message, client: OpenAI, persona_name):
    try:
        cid = message.channel.id
        if cid not in quiz_sessions or not quiz_sessions[cid]["active"]:
            return False

        if message.content.startswith(("!", "/")): return False

        session = quiz_sessions[cid]
        user_msg = message.content.strip()
        correct_answer = session["answer"] # C'est ici que ça doit être bon

        if len(user_msg) > 100: return False 

        # --- VALIDATION SOUPLE ---
        # J'ai retiré le "Sois strict" qui posait problème pour Camus/Albert Camus
        prompt = (
            f"Question : Est-ce que '{user_msg}' est une bonne réponse pour trouver '{correct_answer}' ?\n"
            "Contexte : C'est un quiz. On accepte les fautes d'orthographe légères et les noms partiels (ex: 'Camus' pour 'Albert Camus' est VALIDE).\n"
            "Si c'est clairement faux ou une insulte, réponds NON.\n"
            "Si c'est juste, réponds OUI."
        )

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=5,
            temperature=0.0 # Zéro pour être le plus logique possible
        )
        verdict = response.choices[0].message.content.strip().upper()
        
        # CAS 1 : GAGNÉ
        if "OUI" in verdict:
            quiz_sessions[cid]["active"] = False
            new_score = save_score(message.author.id, 10)
            
            congrats_prompt = f"Tu es {persona_name}. Félicite le joueur {message.author.display_name} pour la bonne réponse '{correct_answer}'."
            res = client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": congrats_prompt}])
            bravo = res.choices[0].message.content.strip()

            embed = discord.Embed(title="✅ BONNE RÉPONSE !", description=bravo, color=0x00FF00)
            embed.add_field(name="Score", value=f"🏆 {message.author.display_name} a **{new_score} points** !")
            await message.channel.send(embed=embed)
            return True 
            
        # CAS 2 : PERDU (Clash)
        else:
            # On loggue pour comprendre pourquoi ça refuse
            print(f"[QUIZ REFUS] Joueur: {user_msg} | Attendu: {correct_answer} | Verdict IA: {verdict}")
            
            roast_prompt = (
                f"Tu es {persona_name}. Le joueur {message.author.display_name} a répondu '{user_msg}' au lieu de la bonne réponse (ne la dis pas).\n"
                "C'est faux. Moque-toi de lui méchamment (mais drôle)."
            )
            res = client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": roast_prompt}])
            roast = res.choices[0].message.content.strip()
            
            await message.reply(f"❌ {roast}")
            return True 

    except Exception as e:
        print(f"Erreur check quiz: {e}")
    
    return False