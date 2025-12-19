import os
import json
import random
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

quiz_state = {}  # {user_id: {"question": "...", "answer": "..."}}

def generate_quiz_question():
    prompt = (
        "Tu es le roi Arthur de Kaamelott. Génére une question originale et facile sur l’univers de Kaamelott, "
        "en gardant ton ton sarcastique et blasé. Formule juste la question. Ne donne pas la réponse."
    )
    messages = [
        {"role": "system", "content": "Tu es Arthur dans Kaamelott. Tu es sarcastique, blasé, et tu poses une question fidèle à l'univers."},
        {"role": "user", "content": prompt}
    ]
    response = client.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
    return response.choices[0].message.content.strip()

def start_quiz(user_id):
    question = generate_quiz_question()
    quiz_state[user_id] = {
        "question": question,
        "history": [{"role": "system", "content": "Tu es Arthur dans Kaamelott. Tu es fatigué, sarcastique et tu corriges les gens avec mauvaise foi."}]
    }
    quiz_state[user_id]["history"].append({"role": "user", "content": f"Pose une question : {question}"})
    return f"Très bien, écoute :\n{question}\n(Tu peux répondre avec !repond <ta réponse>)"

def evaluate_answer(user_id, user_answer):
    if user_id not in quiz_state:
        return "Tu veux répondre à quoi exactement ? Y’a même pas de question posée !"
    
    question = quiz_state[user_id]["question"]
    history = quiz_state[user_id]["history"]
    history.append({"role": "user", "content": f"Ma réponse : {user_answer}"})

    prompt = (
        f"Voici la question que tu as posée : '{question}'\n"
        f"Quelqu’un a répondu : '{user_answer}'\n"
        "Juge cette réponse. Si elle est correcte, dis-le à ta façon en faisant des réponses justes et courtes (sarcastique, moqueur). "
        "Si elle est fausse, dis-le aussi, avec une réplique courte et cinglante fidèle à ton style."
    )

    history.append({"role": "user", "content": prompt})
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=history
    )
    
    reply = response.choices[0].message.content.strip()
    del quiz_state[user_id]
    return reply
