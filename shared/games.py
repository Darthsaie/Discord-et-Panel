import random

games = {}

def start_guessing_game(user_id):
    number = random.randint(1, 10)
    games[user_id] = {"number": number, "tries": 0}
    return "Bon, devine un nombre entre 1 et 10, abruti. Tape `!propose <nombre>`. Et essaie pas de tricher."

def make_guess(user_id, guess):
    if user_id not in games:
        return "Tu crois que le jeu a commencé, connard ? Tape `!devine` d'abord."

    number = games[user_id]["number"]
    games[user_id]["tries"] += 1

    if guess < number:
        return "Trop bas, sombre débile. Essaie encore, mais franchement t’as l’air paumé."
    elif guess > number:
        return "Trop haut, espèce de raté. C’est pas compliqué pourtant."
    else:
        tries = games[user_id]["tries"]
        del games[user_id]
        if tries == 1:
            return f"Coup de bol ou cerveau ? T’as trouvé en 1 essai, espèce de petite merde chanceuse."
        elif tries <= 3:
            return f"Pas mal, t’as trouvé en {tries} essais. T’es moins con que prévu."
        else:
            return f"Enfin ! {tries} essais pour un truc aussi simple... Bravo l’artiste, t’es une vraie lumière."
