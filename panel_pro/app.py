import os
import secrets
import datetime as dt
import json
import logging
import requests
from flask import Flask, redirect, url_for, request, render_template, jsonify, flash, session, abort
from sqlalchemy import create_engine, select, Integer, String, DateTime, ForeignKey, Boolean, event, update
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, Session, selectinload
from dotenv import load_dotenv

load_dotenv()

# --- Logging structuré ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("panel")

SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(16))
PANEL_API_TOKEN = os.getenv("PANEL_API_TOKEN")
if not PANEL_API_TOKEN:
    raise ValueError("CRITICAL: PANEL_API_TOKEN is missing from .env configuration!")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///app/panel.db")
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", 5))
DEV_MODE = os.getenv("DEV_MODE", "1") == "1"
BASE_URL = os.getenv("BASE_URL", "http://localhost:5000")
LOG_WEBHOOK = os.getenv("LOG_WEBHOOK", "1") == "1"

try:
    import stripe
    STRIPE_AVAILABLE = True
except Exception:
    stripe = None
    STRIPE_AVAILABLE = False

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
PRICE_MAP = {
    "homer": os.getenv("PRICE_HOMER", ""),
    "cartman": os.getenv("PRICE_CARTMAN", ""),
    "deadpool": os.getenv("PRICE_DEADPOOL", ""),
    "yoda": os.getenv("PRICE_YODA", ""),
}

if STRIPE_AVAILABLE and STRIPE_SECRET_KEY:
    try:
        stripe.api_key = STRIPE_SECRET_KEY
    except Exception:
        pass

STRIPE_SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL") or f"{BASE_URL.rstrip('/')}/billing/success?session_id={{CHECKOUT_SESSION_ID}}"
STRIPE_CANCEL_URL = os.getenv("STRIPE_CANCEL_URL") or f"{BASE_URL.rstrip('/')}/dashboard"
STRIPE_PORTAL_RETURN_URL = os.getenv("STRIPE_PORTAL_RETURN_URL") or f"{BASE_URL.rstrip('/')}/dashboard"

HOMER_CLIENT_ID = os.getenv("HOMER_CLIENT_ID", "")
CARTMAN_CLIENT_ID = os.getenv("CARTMAN_CLIENT_ID", "")
DEADPOOL_CLIENT_ID = os.getenv("DEADPOOL_CLIENT_ID", "")
YODA_CLIENT_ID = os.getenv("YODA_CLIENT_ID", "")

HOMER_TOKEN = os.getenv("HOMER_TOKEN", "")
CARTMAN_TOKEN = os.getenv("CARTMAN_TOKEN", "")
DEADPOOL_TOKEN = os.getenv("DEADPOOL_TOKEN", "")
YODA_TOKEN = os.getenv("YODA_TOKEN", "")

BOT_DEFS = {
    "homer": {"name": "Homer", "client_id": HOMER_CLIENT_ID},
    "cartman": {"name": "Cartman", "client_id": CARTMAN_CLIENT_ID},
    "deadpool": {"name": "Deadpool", "client_id": DEADPOOL_CLIENT_ID},
    "yoda": {"name": "Yoda", "client_id": YODA_CLIENT_ID},
}

BOT_TOKENS = {
    "homer": HOMER_TOKEN,
    "cartman": CARTMAN_TOKEN,
    "deadpool": DEADPOOL_TOKEN,
    "yoda": YODA_TOKEN,
}


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String)
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False)


class Guild(Base):
    __tablename__ = "guilds"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discord_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    platform: Mapped[str] = mapped_column(String, default="discord")
    icon_url: Mapped[str] = mapped_column(String, nullable=True)


class BotType(Base):
    __tablename__ = "bot_types"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)


class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(ForeignKey("guilds.id"))
    bot_type_id: Mapped[int] = mapped_column(ForeignKey("bot_types.id"))
    status: Mapped[str] = mapped_column(String, default="trial")
    trial_until: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    current_period_end: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=lambda: dt.datetime.utcnow())

    guild: Mapped["Guild"] = relationship()
    bot_type: Mapped["BotType"] = relationship()

    @property
    def days_left(self):
        now = dt.datetime.utcnow()
        if self.current_period_end:
            return (self.current_period_end - now).days
        elif self.trial_until:
            return (self.trial_until - now).days
        return None


class TrialLock(Base):
    __tablename__ = "trial_locks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discord_user_id: Mapped[str] = mapped_column(String, index=True)
    bot_key: Mapped[str] = mapped_column(String)
    guild_discord_id: Mapped[str] = mapped_column(String)
    until: Mapped[dt.datetime] = mapped_column(DateTime)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=lambda: dt.datetime.utcnow())


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(ForeignKey("guilds.id"))
    bot_key: Mapped[str] = mapped_column(String)
    task_type: Mapped[str] = mapped_column(String)
    task_param: Mapped[str] = mapped_column(String, nullable=True)
    frequency: Mapped[str] = mapped_column(String)
    day_of_week: Mapped[str] = mapped_column(String, nullable=True)
    time_of_day: Mapped[str] = mapped_column(String)
    channel_id: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=lambda: dt.datetime.utcnow())

    guild: Mapped["Guild"] = relationship()


DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", f"{BASE_URL.rstrip('/')}/oauth/callback")
DISCORD_OAUTH_SCOPE = "identify guilds"
DISCORD_API_BASE = "https://discord.com/api"
PERM_ADMIN = 0x00000008
PERM_MANAGE_GUILD = 0x00000020
ADMIN_DISCORD_IDS = [s.strip() for s in os.getenv("ADMIN_DISCORD_IDS", "").split(",") if s.strip()]

# Configuration Twitch OAuth
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "")
TWITCH_REDIRECT_URI = os.getenv("TWITCH_REDIRECT_URI", f"{BASE_URL.rstrip('/')}/oauth/twitch/callback")
TWITCH_OAUTH_SCOPE = "user:read:email user:read:follows"
TWITCH_API_BASE = "https://id.twitch.tv/oauth2"
TWITCH_HELIX_API = "https://api.twitch.tv/helix"


def _check_api_token():
    """Vérifie le token API via header Authorization ou query param (fallback)."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and auth_header[7:] == PANEL_API_TOKEN:
        return True
    if request.args.get("token") == PANEL_API_TOKEN:
        return True
    return False


def make_app():
    app = Flask(__name__)
    app.secret_key = SECRET_KEY

    # --- CSRF Protection ---
    try:
        from flask_wtf.csrf import CSRFProtect
        csrf = CSRFProtect(app)
        # Exempter les endpoints API et webhooks du CSRF
        CSRF_EXEMPT_VIEWS = {
            "stripe_webhook",
            "api_bot_config",
            "api_bot_tasks",
            "api_auto_messages_config",
            "api_create_subscription",
            "api_get_bot_types",
        }

        @app.before_request
        def _csrf_exempt_api():
            if request.endpoint in CSRF_EXEMPT_VIEWS:
                request.csrf_valid = True

        for view_name in CSRF_EXEMPT_VIEWS:
            csrf.exempt(view_name)

        logger.info("CSRF protection enabled")
    except ImportError:
        logger.warning("flask-wtf not installed, CSRF protection disabled")

    # --- Rate Limiting ---
    try:
        from flask_limiter import Limiter
        from flask_limiter.util import get_remote_address
        limiter = Limiter(get_remote_address, app=app, default_limits=["200 per minute"])
        app.limiter = limiter
        logger.info("Rate limiting enabled")
    except ImportError:
        limiter = None
        logger.warning("flask-limiter not installed, rate limiting disabled")

    connect_args = {}
    if "sqlite" in DATABASE_URL:
        connect_args = {"check_same_thread": False, "timeout": 30}

    app.engine = create_engine(DATABASE_URL, future=True, connect_args=connect_args)

    if "sqlite" in DATABASE_URL:
        @event.listens_for(app.engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    Base.metadata.create_all(app.engine)

    app.config["BOT_AVATARS"] = None

    # --- Health Check ---
    @app.get("/health")
    def health_check():
        try:
            with Session(app.engine) as db:
                db.execute(select(BotType).limit(1))
            return jsonify({"status": "ok"}), 200
        except Exception as e:
            return jsonify({"status": "error", "detail": str(e)}), 500

    # --- Context processor: inject is_admin into all templates ---
    @app.context_processor
    def inject_globals():
        u = session.get("user") or {}
        uid = str(u.get("id") or "")
        return {"is_admin": uid in ADMIN_DISCORD_IDS if ADMIN_DISCORD_IDS else False}

    def calculate_trial_info(sub):
        if sub.status == "trial" and sub.trial_until:
            try:
                trial_end = sub.trial_until.replace(tzinfo=None) if sub.trial_until.tzinfo else sub.trial_until
                now = dt.datetime.utcnow().replace(tzinfo=None)
                remaining = trial_end - now
            except Exception:
                return None

            if remaining.total_seconds() > 0:
                days = remaining.days
                if remaining.seconds > 0:
                    days += 1
                if days > 1:
                    return f"Reste {days} jours"
                elif days == 1:
                    return "Reste 1 jour"
                else:
                    return "Reste < 1 jour"
            else:
                return "Expiré"
        return None

    def wlog(*args):
        if LOG_WEBHOOK:
            logger.info("WEBHOOK: %s", " ".join(str(a) for a in args))

    def login_required(view):
        from functools import wraps
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not session.get("user"):
                return redirect(url_for("login_discord"))
            return view(*args, **kwargs)
        return wrapper

    def admin_required(view):
        from functools import wraps
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not session.get("user"):
                if session.get("twitch_oauth"):
                    return redirect(url_for("login_twitch"))
                else:
                    return redirect(url_for("login_discord"))

            u = session.get("user") or {}
            uid = str(u.get("id") or "")

            if not uid:
                abort(403)

            # Seuls les IDs listés dans ADMIN_DISCORD_IDS sont admins
            if not ADMIN_DISCORD_IDS:
                logger.warning("ADMIN_DISCORD_IDS is empty - no admin access possible")
                abort(403)

            if uid in ADMIN_DISCORD_IDS:
                return view(*args, **kwargs)

            abort(403)
        return wrapper

    def oauth_authorize_url():
        params = {
            "client_id": DISCORD_CLIENT_ID,
            "redirect_uri": DISCORD_REDIRECT_URI,
            "response_type": "code",
            "scope": DISCORD_OAUTH_SCOPE,
        }
        return f"https://discord.com/api/oauth2/authorize?{requests.compat.urlencode(params)}"

    def twitch_oauth_authorize_url():
        params = {
            "client_id": TWITCH_CLIENT_ID,
            "redirect_uri": TWITCH_REDIRECT_URI,
            "response_type": "code",
            "scope": TWITCH_OAUTH_SCOPE,
        }
        return f"https://id.twitch.tv/oauth2/authorize?{requests.compat.urlencode(params)}"

    def has_admin_perms(perms_value, is_owner) -> bool:
        try:
            perms_int = int(perms_value)
        except Exception:
            perms_int = 0
        return bool(is_owner) or (perms_int & (PERM_ADMIN | PERM_MANAGE_GUILD))

    def sync_user_and_guilds(access_token: str):
        uh = {"Authorization": f"Bearer {access_token}"}
        u = requests.get(f"{DISCORD_API_BASE}/users/@me", headers=uh, timeout=15)
        g = requests.get(f"{DISCORD_API_BASE}/users/@me/guilds", headers=uh, timeout=15)
        u.raise_for_status()
        g.raise_for_status()

        u = u.json()
        guilds = g.json() if isinstance(g.json(), list) else []

        admin_ids = []
        guild_icons = {}
        for gg in guilds:
            is_owner = bool(gg.get("owner"))
            perms_val = gg.get("permissions") or gg.get("permissions_new") or 0
            if has_admin_perms(perms_val, is_owner):
                gid = str(gg.get("id"))
                admin_ids.append(gid)
                guild_icons[gid] = gg.get("icon")

        session["admin_guild_ids"] = admin_ids
        session["guild_icons"] = guild_icons

        with Session(app.engine) as db:
            user = db.scalar(select(User).where(User.username == u.get("username")))
            if not user:
                user = User(username=u.get("username"), is_owner=True if u.get("id") else False)
                db.add(user)
                db.commit()

            for gid in admin_ids:
                existing = db.scalar(select(Guild).where(Guild.discord_id == gid))
                if not existing:
                    name = next((x.get("name", "") for x in guilds if str(x.get("id")) == gid), "")
                    db.add(Guild(discord_id=gid, name=name, platform="discord"))
            db.commit()

        return u

    def file_exists(path: str) -> bool:
        try:
            return os.path.exists(path)
        except Exception:
            return False

    def _get_bot_avatar_urls() -> dict:
        if app.config.get("BOT_AVATARS"):
            return app.config["BOT_AVATARS"]

        avatars = dict[str, str | None]()

        for key, token in BOT_TOKENS.items():
            url = None
            if token:
                try:
                    r = requests.get(
                        f"{DISCORD_API_BASE}/users/@me",
                        headers={"Authorization": f"Bot {token}"},
                        timeout=10
                    )
                    if r.status_code == 200:
                        me = r.json()
                        uid = me.get("id")
                        av = me.get("avatar")
                        if uid and av:
                            url = f"https://cdn.discordapp.com/avatars/{uid}/{av}.png?size=64"
                        elif uid:
                            idx = int(uid) % 5
                            url = f"https://cdn.discordapp.com/embed/avatars/{idx}.png"
                except Exception:
                    pass

            if not url:
                static_path = os.path.join(app.static_folder or "static", "bots", f"{key}.png")
                if file_exists(static_path):
                    url = f"/static/bots/{key}.png"

            avatars[key] = url

        app.config["BOT_AVATARS"] = avatars
        return avatars

    def activate_subscription(db: Session, bot_key: str, guild_discord_id: str, current_period_end_ts: int | None):
        g = db.scalar(select(Guild).where(Guild.discord_id == guild_discord_id))
        b = db.scalar(select(BotType).where(BotType.key == bot_key))
        if not (g and b):
            return False

        s = db.scalar(select(Subscription).where(Subscription.guild_id == g.id, Subscription.bot_type_id == b.id))
        if not s:
            s = Subscription(guild_id=g.id, bot_type_id=b.id, status="active", trial_until=None)
            db.add(s)
        else:
            if s.status != "lifetime":
                s.status = "active"
                s.trial_until = None

        if current_period_end_ts:
            try:
                s.current_period_end = dt.datetime.utcfromtimestamp(current_period_end_ts)
            except Exception:
                pass

        db.commit()
        return True

    def cancel_subscription(db: Session, bot_key: str, guild_discord_id: str):
        g = db.scalar(select(Guild).where(Guild.discord_id == guild_discord_id))
        b = db.scalar(select(BotType).where(BotType.key == bot_key))
        if not (g and b):
            return False

        s = db.scalar(select(Subscription).where(Subscription.guild_id == g.id, Subscription.bot_type_id == b.id))
        if not s:
            return False

        if s.status != "lifetime":
            s.status = "canceled"
            s.trial_until = None
            s.current_period_end = None
            s.cancel_at_period_end = False

        db.commit()
        return True

    @app.get("/")
    def index():
        logged = bool(session.get("user"))
        bot_avatars = _get_bot_avatar_urls()
        return render_template("home.html", logged=logged, dev_mode=DEV_MODE, trial_days=TRIAL_DAYS, current_user=session.get("user"), bot_avatars=bot_avatars, bot_defs=BOT_DEFS)

    @app.get("/pricing")
    def pricing():
        logged = bool(session.get("user"))
        bot_avatars = _get_bot_avatar_urls()
        return render_template("pricing.html", logged=logged, trial_days=TRIAL_DAYS, bot_avatars=bot_avatars, bot_defs=BOT_DEFS, current_user=session.get("user"))

    @app.get("/bots/<bot_key>")
    def bot_page(bot_key):
        bot_def = BOT_DEFS.get(bot_key)
        if not bot_def:
            return redirect(url_for("index"))
        logged = bool(session.get("user"))
        bot_avatars = _get_bot_avatar_urls()
        return render_template("bot_page.html", bot_key=bot_key, bot_def=bot_def, logged=logged, trial_days=TRIAL_DAYS, bot_avatars=bot_avatars, bot_defs=BOT_DEFS, current_user=session.get("user"))

    @app.get("/faq")
    def faq():
        logged = bool(session.get("user"))
        return render_template("faq.html", logged=logged, current_user=session.get("user"))

    @app.get("/dashboard")
    @login_required
    def dashboard():
        logged = True
        ids = session.get("admin_guild_ids") or []
        guild_icons = session.get("guild_icons") or {}

        with Session(app.engine) as db:
            bots = db.scalars(select(BotType)).all()
            if not bots:
                for k, bd in BOT_DEFS.items():
                    db.add(BotType(key=k, name=bd["name"]))
                db.commit()
                bots = db.scalars(select(BotType)).all()

            guilds = []
            if ids:
                discord_guilds = db.scalars(select(Guild).where(Guild.discord_id.in_(ids))).all()
                guilds.extend(discord_guilds)
            
            if session.get("twitch_oauth"):
                user_id = session.get("user", {}).get("id")
                if user_id:
                    user_twitch_guild = db.scalar(select(Guild).where(Guild.discord_id == user_id, Guild.platform == "twitch"))
                    if user_twitch_guild:
                        guilds.append(user_twitch_guild)
            
            if session.get("twitch_oauth"):
                deadpool_bot = next((b for b in bots if b.key == "deadpool"), None)
                if deadpool_bot:
                    bots = [deadpool_bot]
            
            subs = db.scalars(select(Subscription)).all()

            submap: dict[str, dict[str, Subscription]] = {}
            for s in subs:
                submap.setdefault(s.bot_type.key, {})[s.guild.discord_id] = s
                s.trial_remaining_info = calculate_trial_info(s)

            has_any_active = any((s.status in ("active", "lifetime") and s.guild.discord_id in ids) for s in subs)
            bot_avatars = _get_bot_avatar_urls()

            active_lock = None
            trial_ever = False
            if logged:
                user_id = (session.get("user") or {}).get("id")
                now = dt.datetime.utcnow()
                with Session(app.engine) as db2:
                    active_lock = db2.scalar(
                        select(TrialLock).where(TrialLock.discord_user_id == user_id, TrialLock.until > now)
                    )
                    trial_ever = bool(db2.scalar(
                        select(TrialLock.id).where(TrialLock.discord_user_id == user_id)
                    ))

            return render_template(
                "dashboard.html",
                bots=bots,
                guilds=guilds,
                submap=submap,
                bot_defs=BOT_DEFS,
                trial_days=TRIAL_DAYS,
                dev_mode=DEV_MODE,
                now_utc=dt.datetime.utcnow(),
                guild_icons=guild_icons,
                bot_avatars=bot_avatars,
                active_lock=active_lock,
                trial_ever=trial_ever,
                logged=logged,
                has_any_active=has_any_active,
                current_user=session.get("user")
            )

    @app.get("/leaderboard")
    def leaderboard():
        leaderboard_file = "/app/shared/leaderboard.json"
        scores = []
        try:
            if os.path.exists(leaderboard_file):
                with open(leaderboard_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    bot_token = None
                    for token in BOT_TOKENS.values():
                        if token:
                            bot_token = token
                            break
                    
                    if isinstance(data, dict) and "scores" not in data:
                        for discord_id, score in data.items():
                            user_info = {
                                "name": f"Joueur {discord_id[-4:]}",
                                "score": score,
                                "avatar": None
                            }
                            if bot_token:
                                try:
                                    r = requests.get(
                                        f"{DISCORD_API_BASE}/users/{discord_id}",
                                        headers={"Authorization": f"Bot {bot_token}"},
                                        timeout=5
                                    )
                                    if r.status_code == 200:
                                        user = r.json()
                                        user_info["name"] = user.get("username", user_info["name"])
                                        avatar_hash = user.get("avatar")
                                        if avatar_hash:
                                            user_info["avatar"] = f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.png?size=128"
                                        else:
                                            discriminator = int(user.get("discriminator", "0"))
                                            if discriminator == 0:
                                                idx = (int(discord_id) >> 22) % 6
                                            else:
                                                idx = discriminator % 5
                                            user_info["avatar"] = f"https://cdn.discordapp.com/embed/avatars/{idx}.png"
                                except Exception as e:
                                    print(f"Erreur récupération profil {discord_id}: {e}")
                            scores.append(user_info)
                    
                    elif isinstance(data, dict) and "scores" in data:
                        scores = data.get("scores", [])
                    
                    scores = sorted(scores, key=lambda x: x.get("score", 0), reverse=True)[:20]
        except Exception as e:
            print(f"Erreur lecture leaderboard: {e}")
            import traceback
            traceback.print_exc()
        
        return render_template("leaderboard.html", scores=scores)

    @app.post("/trial/start/<bot_key>/<guild_id>")
    @login_required
    def trial_start(bot_key, guild_id):
        user_id = (session.get("user") or {}).get("id")
        if not user_id:
            flash("Tu dois être connecté.", "error")
            return redirect(url_for("dashboard"))

        now = dt.datetime.utcnow()
        with Session(app.engine) as db:
            any_lock = db.scalar(select(TrialLock).where(TrialLock.discord_user_id == user_id))
            if any_lock:
                flash("Tu as déjà consommé ton essai gratuit.", "error")
                return redirect(url_for("dashboard"))

            g = db.scalar(select(Guild).where(Guild.discord_id == guild_id))
            b = db.scalar(select(BotType).where(BotType.key == bot_key))
            if not (g and b):
                flash("Bot/serveur introuvable.", "error")
                return redirect(url_for("dashboard"))

            s = db.scalar(select(Subscription).where(Subscription.guild_id == g.id, Subscription.bot_type_id == b.id))
            if not s:
                s = Subscription(
                    guild_id=g.id,
                    bot_type_id=b.id,
                    status="trial",
                    trial_until=now + dt.timedelta(days=TRIAL_DAYS)
                )
                db.add(s)
            else:
                if s.status in ("active", "lifetime"):
                    flash("Abonnement déjà actif.", "info")
                    return redirect(url_for("dashboard"))

                if s.status == "trial" and s.trial_until and s.trial_until > now:
                    flash("Essai déjà en cours.", "info")
                    return redirect(url_for("dashboard"))

                s.status = "trial"
                s.trial_until = now + dt.timedelta(days=TRIAL_DAYS)
                s.current_period_end = None
                s.cancel_at_period_end = False

            lock = TrialLock(
                discord_user_id=user_id,
                bot_key=bot_key,
                guild_discord_id=guild_id,
                until=s.trial_until
            )
            db.add(lock)
            db.commit()

        flash("Essai activé.", "ok")
        return redirect(url_for("dashboard"))

    @app.post("/trial/cancel/<bot_key>/<guild_id>")
    @admin_required
    def trial_cancel(bot_key, guild_id):

        with Session(app.engine) as db:
            g = db.scalar(select(Guild).where(Guild.discord_id == guild_id))
            b = db.scalar(select(BotType).where(BotType.key == bot_key))
            if g and b:
                s = db.scalar(select(Subscription).where(Subscription.guild_id == g.id, Subscription.bot_type_id == b.id))
                if s:
                    s.status = "canceled"
                    s.trial_until = None
                    s.current_period_end = None
                    db.commit()
        flash("DEV: Essai annulé.", "ok")
        return redirect(url_for("dashboard"))

    @app.post("/subscribe/<bot_key>/<guild_id>")
    def subscribe(bot_key, guild_id):
        if not (STRIPE_AVAILABLE and STRIPE_SECRET_KEY.startswith("sk") and PRICE_MAP.get(bot_key)):
            flash("Stripe non configuré.", "error")
            return redirect(url_for("dashboard"))

        user = session.get("user")
        if not user:
            flash("Connecte-toi.", "error")
            return redirect(url_for("dashboard"))

        with Session(app.engine) as db:
            g = db.scalar(select(Guild).where(Guild.discord_id == guild_id))
            b = db.scalar(select(BotType).where(BotType.key == bot_key))
            if not (g and b):
                flash("Bot/serveur introuvable.", "error")
                return redirect(url_for("dashboard"))

            try:
                sess = stripe.checkout.Session.create(
                    mode="subscription",
                    line_items=[{"price": PRICE_MAP[bot_key], "quantity": 1}],
                    success_url=STRIPE_SUCCESS_URL,
                    cancel_url=STRIPE_CANCEL_URL,
                    allow_promotion_codes=True,
                    client_reference_id=f"{bot_key}:{guild_id}:{user.get('id')}",
                    subscription_data={"metadata": {"bot_key": bot_key, "guild_id": guild_id}},
                    metadata={"bot_key": bot_key, "guild_id": guild_id}
                )
                return redirect(sess.url, code=303)
            except Exception as e:
                flash(f"Erreur Stripe: {e}", "error")
                return redirect(url_for("dashboard"))

    @app.get("/billing/success")
    def billing_success():
        session_id = request.args.get("session_id")
        if STRIPE_AVAILABLE and session_id:
            try:
                sess = stripe.checkout.Session.retrieve(session_id)
                meta = sess.get("metadata") or {}
                bot_key, guild_id = meta.get("bot_key"), meta.get("guild_id")
                sub_id = sess.get("subscription")

                ts = None
                if sub_id:
                    if isinstance(sub_id, str):
                        sub_obj = stripe.Subscription.retrieve(sub_id)
                        try:
                            ts = sub_obj["items"]["data"][0]["current_period_end"]
                        except (KeyError, IndexError):
                            ts = None
                    else:
                        try:
                            ts = sub_id["items"]["data"][0]["current_period_end"]
                        except (KeyError, IndexError):
                            ts = None

                if bot_key and guild_id:
                    with Session(app.engine) as db:
                        activate_subscription(db, bot_key, guild_id, ts)
                flash("Abonnement activé avec succès !", "ok")
            except Exception as e:
                flash(f"Info: Paiement reçu, activation en cours... {e}", "info")

        return redirect(url_for("dashboard"))

    def find_customer_for(bot_key, guild_id):
        try:
            q = f'status:"active" AND metadata["bot_key"]:"{bot_key}" AND metadata["guild_id"]:"{guild_id}"'
            res = stripe.Subscription.search(query=q, limit=1)
            items = getattr(res, "data", []) or []
            if items:
                return items[0]["customer"]

            q2 = f'metadata["bot_key"]:"{bot_key}" AND metadata["guild_id"]:"{guild_id}"'
            res = stripe.Subscription.search(query=q2, limit=1)
            items = getattr(res, "data", []) or []
            if items:
                return items[0]["customer"]
        except Exception as e:
            print("portal error:", e)
        return None

    @app.post("/billing/portal/<bot_key>/<guild_id>")
    def billing_portal(bot_key, guild_id):
        if not (STRIPE_AVAILABLE and STRIPE_SECRET_KEY.startswith("sk")):
            flash("Billing Portal indisponible.", "error")
            return redirect(url_for("dashboard"))

        try:
            customer_id = find_customer_for(bot_key, guild_id)
            if not customer_id:
                flash("Impossible de retrouver l'abo Stripe.", "error")
                return redirect(url_for("dashboard"))

            ps = stripe.billing_portal.Session.create(customer=customer_id, return_url=STRIPE_PORTAL_RETURN_URL)
            return redirect(ps.url, code=303)
        except Exception as e:
            flash(f"Erreur Billing Portal: {e}", "error")
            return redirect(url_for("dashboard"))

    @app.post("/stripe/webhook")
    def stripe_webhook():
        if not (STRIPE_AVAILABLE and STRIPE_WEBHOOK_SECRET):
            return ("not configured", 400)

        payload = request.get_data(as_text=True)
        sig = request.headers.get("Stripe-Signature", "")
        try:
            event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
        except Exception as e:
            wlog(f"Webhook signature verification failed: {e}")
            return ("invalid signature", 400)

        event_type = event.get("type")
        data_obj = event["data"]["object"]
        wlog(f"✅ Stripe Event: {event_type} | ID: {data_obj.get('id')}")

        def sync_subscription_from_stripe(sub_id_or_obj):
            try:
                if isinstance(sub_id_or_obj, str):
                    stripe_sub = stripe.Subscription.retrieve(sub_id_or_obj)
                else:
                    stripe_sub = stripe.Subscription.retrieve(sub_id_or_obj.id)

                meta = stripe_sub.metadata or {}
                bot_key = meta.get("bot_key")
                guild_id = meta.get("guild_id")

                if not (bot_key and guild_id):
                    wlog(f"⚠ Sub {stripe_sub.id} n'a pas de metadata bot_key/guild_id")
                    return False

                wlog(f"🔄 Syncing {bot_key}:{guild_id} | Stripe Status: {stripe_sub.status}...")

                with Session(app.engine) as db:
                    g = db.scalar(select(Guild).where(Guild.discord_id == guild_id))
                    b = db.scalar(select(BotType).where(BotType.key == bot_key))

                    if not g:
                        wlog(f"➕ Guild {guild_id} pas trouvé, création...")
                        g = Guild(discord_id=guild_id, name=f"Guild {guild_id}", platform="discord")
                        db.add(g)
                        db.flush()

                    if not b:
                        wlog(f"➕ BotType {bot_key} pas trouvé, création...")
                        b = BotType(key=bot_key, name=bot_key.capitalize())
                        db.add(b)
                        db.flush()

                    s = db.scalar(
                        select(Subscription).where(
                            Subscription.guild_id == g.id,
                            Subscription.bot_type_id == b.id
                        )
                    )

                    if not s:
                        wlog(f"➕ Création nouvelle subscription")
                        s = Subscription(guild_id=g.id, bot_type_id=b.id)
                        db.add(s)

                    stripe_status = stripe_sub.status
                    if stripe_status in ("active", "trialing"):
                        s.status = "active"
                    elif stripe_status == "past_due":
                        s.status = "active"
                        wlog(f"⚠ Paiement en retard pour {guild_id}")
                    elif stripe_status in ("canceled", "unpaid", "incomplete_expired"):
                        s.status = "canceled"
                    else:
                        s.status = "canceled"

                    s.stripe_subscription_id = stripe_sub.id
                    s.stripe_customer_id = stripe_sub.customer

                    try:
                        period_end = stripe_sub["items"]["data"][0]["current_period_end"]
                        s.current_period_end = dt.datetime.utcfromtimestamp(period_end)
                        wlog(f"📅 Fin période: {s.current_period_end.strftime('%d/%m/%Y')}")
                    except (KeyError, IndexError, TypeError):
                        wlog(f"⚠ current_period_end non disponible")

                    if stripe_sub.trial_end:
                        s.trial_until = dt.datetime.utcfromtimestamp(stripe_sub.trial_end)

                    s.cancel_at_period_end = stripe_sub.cancel_at_period_end

                    db.commit()
                    wlog(f"✅ Sync OK {bot_key}:{guild_id} -> {s.status} expire {s.current_period_end}")
                    return True

            except Exception as e:
                wlog(f"❌ Erreur sync: {e}")
                import traceback
                traceback.print_exc()
                return False

        handled = False

        if event_type in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
            handled = sync_subscription_from_stripe(data_obj)

        elif event_type == "checkout.session.completed":
            sub_id = data_obj.get("subscription")
            if sub_id:
                handled = sync_subscription_from_stripe(sub_id)
            else:
                meta = data_obj.get("metadata", {})
                bot_key = meta.get("bot_key")
                guild_id = meta.get("guild_id")
                if bot_key and guild_id:
                    wlog(f"⚠ Checkout sans sub_id immédiat, activation manuelle")
                    with Session(app.engine) as db:
                        activate_subscription(db, bot_key, guild_id, None)
                    handled = True

        elif event_type in ("invoice.paid", "invoice.payment_succeeded"):
            sub_id = data_obj.get("subscription")
            if sub_id:
                handled = sync_subscription_from_stripe(sub_id)

        elif event_type == "invoice.payment_failed":
            sub_id = data_obj.get("subscription")
            if sub_id:
                handled = sync_subscription_from_stripe(sub_id)

        elif event_type == "customer.subscription.trial_will_end":
            wlog(f"⏰ Trial se termine bientôt: {data_obj.get('id')}")
            handled = True

        if handled:
            wlog(f"✅ Event {event_type} traité avec succès")
        else:
            wlog(f"⚠ Event {event_type} non géré ou échoué")

        return ("", 200)

    @app.get("/invite/<bot_key>/<guild_id>")
    def invite(bot_key, guild_id):
        bot_def = BOT_DEFS.get(bot_key)
        if not bot_def:
            return redirect(url_for("dashboard"))

        cid = bot_def["client_id"]
        # Permissions: Send Messages, Embed Links, Read Messages, Read Message History, Use Slash Commands
        perms = 277025770560
        oauth = f"https://discord.com/api/oauth2/authorize?client_id={cid}&permissions={perms}&scope=bot%20applications.commands&guild_id={guild_id}&disable_guild_select=true"
        return redirect(oauth)

    @app.get("/api/bot/config/<bot_key>")
    def api_bot_config(bot_key):
        if not _check_api_token():
            return jsonify({"error": "unauthorized"}), 401

        now = dt.datetime.utcnow()
        allowed_discord = []
        allowed_twitch = []

        with Session(app.engine) as db:
            subs = db.scalars(
                select(Subscription).options(
                    selectinload(Subscription.guild),
                    selectinload(Subscription.bot_type),
                )
            ).all()

            for s in subs:
                if s.bot_type.key == bot_key:
                    is_allowed = False

                    if s.status == "lifetime":
                        is_allowed = True
                    elif s.status == "active":
                        is_allowed = True
                    elif s.status == "trial" and s.trial_until and s.trial_until > now:
                        is_allowed = True
                    elif s.status == "canceled" and s.current_period_end and s.current_period_end > now:
                        is_allowed = True

                    if is_allowed:
                        if getattr(s.guild, "platform", "discord") == "twitch":
                            ch = (getattr(s.guild, "name", "") or "").strip().lower()
                            if ch:
                                allowed_twitch.append(ch)
                        else:
                            allowed_discord.append(int(s.guild.discord_id))

        return jsonify({
            "bot_key": bot_key, 
            "allowed_guild_ids": sorted(list(set(allowed_discord))),
            "allowed_twitch_channels": sorted(list(set(allowed_twitch)))
        })

    @app.get("/api/bot/tasks/<bot_key>")
    def api_bot_tasks(bot_key):
        if not _check_api_token():
            return jsonify({"error": "unauthorized"}), 401

        with Session(app.engine) as db:
            tasks = db.scalars(
                select(ScheduledTask).where(ScheduledTask.bot_key == bot_key, ScheduledTask.is_active == True)
            ).all()

            data = []
            for t in tasks:
                g = db.get(Guild, t.guild_id)
                if g:
                    data.append({
                        "id": t.id,
                        "guild_discord_id": g.discord_id,
                        "task_type": t.task_type,
                        "task_param": t.task_param,
                        "frequency": t.frequency,
                        "day_of_week": t.day_of_week,
                        "time_of_day": t.time_of_day,
                        "channel_id": t.channel_id
                    })

        return jsonify(data)

    @app.get("/admin/add-twitch-user")
    @admin_required
    def admin_add_twitch_user():
        return render_template("admin_add_twitch.html")
    
    @app.post("/admin/add-twitch-user")
    @admin_required
    def admin_add_twitch_user_post():
        twitch_id = request.form.get("twitch_id")
        twitch_login = request.form.get("twitch_login")
        
        if not twitch_id or not twitch_login:
            flash("ID et login requis", "error")
            return redirect(url_for("admin_add_twitch_user"))
        
        try:
            with Session(app.engine) as db:
                # Vérifier si la guild existe déjà
                existing_guild = db.scalar(select(Guild).where(Guild.discord_id == twitch_id, Guild.platform == "twitch"))
                if existing_guild:
                    flash(f"La guild Twitch pour {twitch_login} existe déjà", "info")
                    return redirect(url_for("admin_subs_v2"))
                
                # Créer la guild Twitch
                twitch_guild = Guild(
                    discord_id=twitch_id,
                    name=twitch_login.lower(),
                    platform="twitch"
                )
                db.add(twitch_guild)
                db.flush()
                
                # Créer la subscription pour deadpool
                deadpool_bot = db.scalar(select(BotType).where(BotType.key == "deadpool"))
                if deadpool_bot:
                    # Créer un essai gratuit de 7 jours
                    trial_until = dt.datetime.utcnow() + dt.timedelta(days=7)
                    subscription = Subscription(
                        guild_id=twitch_guild.id,
                        bot_type_id=deadpool_bot.id,
                        status="trial",
                        trial_until=trial_until,
                        created_at=dt.datetime.utcnow()
                    )
                    db.add(subscription)
                
                db.commit()
                flash(f"✅ Utilisateur Twitch {twitch_login} ajouté avec succès !", "ok")
                wlog(f"✅ Admin ajouté user Twitch: {twitch_login} (ID: {twitch_id})")
                
        except Exception as e:
            flash(f"Erreur: {e}", "error")
            wlog(f"❌ Erreur ajout user Twitch: {e}")
        
        return redirect(url_for("admin_subs_v2"))

    @app.post("/admin/locks/release/<int:lock_id>")
    @admin_required
    def admin_release_lock(lock_id):
        with Session(app.engine) as db:
            lock = db.get(TrialLock, lock_id)
            if lock:
                db.delete(lock)
                db.commit()
                wlog(f"✅ Admin released trial lock: {lock_id}")
            else:
                wlog(f"❌ Trial lock not found: {lock_id}")
        return redirect(url_for("admin_subs_v2"))

    @app.post("/logout")
    @app.get("/logout")
    def logout_discord():
        session.clear()
        flash("Déconnecté.", "ok")
        return redirect(url_for("index"))

    @app.get("/login")
    def login_discord():
        if session.get("twitch_oauth"):
            session.clear()
        url = oauth_authorize_url()
        # On spécifie le service Discord pour que auth_bouncer sache gérer le lien
        return render_template("auth_bouncer.html", auth_url=url, service="Discord")

    @app.get("/login/twitch")
    def login_twitch():
        if session.get("oauth"):
            session.clear()
        url = twitch_oauth_authorize_url()
        # On spécifie le service Twitch pour éviter le bug discord://
        return render_template("auth_bouncer.html", auth_url=url, service="Twitch")

    @app.get("/oauth/twitch/callback")
    @app.get("/oauth/callback/twitch")
    def twitch_oauth_callback():
        code = request.args.get("code")
        error = request.args.get("error")
        
        if error:
            flash(f"Erreur Twitch : {error} - {request.args.get('error_description')}", "error")
            return redirect(url_for("index"))

        if not code:
            flash("Code d'autorisation manquant.", "error")
            return redirect(url_for("index"))

        data = {
            "client_id": TWITCH_CLIENT_ID,
            "client_secret": TWITCH_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": TWITCH_REDIRECT_URI,
        }
        
        try:
            response = requests.post(f"{TWITCH_API_BASE}/token", data=data, timeout=15)
            response.raise_for_status()
            token_data = response.json()
        except Exception as e:
            print(f"ERREUR ECHANGE TOKEN TWITCH: {e}")
            flash("Échec de la connexion Twitch (Token).", "error")
            return redirect(url_for("index"))
        
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Client-Id": TWITCH_CLIENT_ID
        }
        
        try:
            user_response = requests.get(f"{TWITCH_HELIX_API}/users", headers=headers, timeout=15)
            user_response.raise_for_status()
            user_data = user_response.json()
        except Exception as e:
            flash("Impossible de récupérer le profil Twitch.", "error")
            return redirect(url_for("index"))
        
        if not user_data.get("data"):
            flash("Aucune donnée utilisateur trouvée.", "error")
            return redirect(url_for("dashboard"))
            
        user_info = user_data["data"][0]
        
        session["twitch_oauth"] = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": (dt.datetime.utcnow() + dt.timedelta(seconds=token_data.get("expires_in", 3600))).timestamp()
        }
        
        session["user"] = {
            "id": user_info["id"],
            "username": user_info["login"],
            "display_name": user_info["display_name"],
            "avatar": user_info.get("profile_image_url"),
            "platform": "twitch"
        }
        
        # Créer automatiquement la guild Twitch et la subscription pour deadpool
        with Session(app.engine) as db:
            # Vérifier si la guild Twitch existe déjà
            existing_guild = db.scalar(select(Guild).where(Guild.discord_id == user_info["id"], Guild.platform == "twitch"))
            if not existing_guild:
                # Créer la guild Twitch
                twitch_guild = Guild(
                    discord_id=user_info["id"],
                    name=user_info["login"],  # Utiliser le login comme nom de chaîne
                    platform="twitch",
                    icon_url=user_info.get("profile_image_url")
                )
                db.add(twitch_guild)
                db.flush()
                
                # Créer la subscription pour deadpool
                deadpool_bot = db.scalar(select(BotType).where(BotType.key == "deadpool"))
                if deadpool_bot:
                    # Vérifier si une subscription existe déjà
                    existing_sub = db.scalar(select(Subscription).where(
                        Subscription.guild_id == twitch_guild.id,
                        Subscription.bot_type_id == deadpool_bot.id
                    ))
                    if not existing_sub:
                        # Créer un essai gratuit de 7 jours pour les nouveaux utilisateurs Twitch
                        trial_until = dt.datetime.utcnow() + dt.timedelta(days=7)
                        subscription = Subscription(
                            guild_id=twitch_guild.id,
                            bot_type_id=deadpool_bot.id,
                            status="trial",
                            trial_until=trial_until,
                            created_at=dt.datetime.utcnow()
                        )
                        db.add(subscription)
                
                db.commit()
                print(f"✅ Création guild Twitch et essai 7j pour {user_info['login']}")
        
        flash(f"Connecté avec succès en tant que {user_info['display_name']} ! 🎁 Essai gratuit de 7 jours offert !", "ok")
        return redirect(url_for("dashboard"))

    @app.get("/oauth/callback")
    def oauth_callback():
        code = request.args.get("code")
        if not code:
            return redirect(url_for("dashboard"))

        data = {
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DISCORD_REDIRECT_URI,
        }

        r = requests.post(
            f"{DISCORD_API_BASE}/oauth2/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        if r.status_code != 200:
            return redirect(url_for("dashboard"))

        acc = r.json().get("access_token")
        session["oauth"] = {"access_token": acc}

        u = sync_user_and_guilds(acc)
        session["user"] = {
            "id": u.get("id"),
            "username": u.get("username"),
            "discord_id": u.get("id"),
            "avatar_hash": u.get("avatar")
        }

        flash("Connecté.", "ok")
        return redirect(url_for("dashboard"))

    @app.get("/guilds/sync")
    @login_required
    def guilds_sync():
        try:
            u = sync_user_and_guilds(session["oauth"]["access_token"])
            session["user"] = {
                "id": u.get("id"),
                "username": u.get("username"),
                "discord_id": u.get("id"),
                "avatar_hash": u.get("avatar")
            }
        except:
            return redirect(url_for("login_discord"))

        return redirect(url_for("dashboard"))

    @app.get("/stripe/status")
    @admin_required
    def stripe_status():
        with Session(app.engine) as db:
            subs = db.scalars(
                select(Subscription).options(selectinload(Subscription.guild), selectinload(Subscription.bot_type))
            ).all()

            by_bot = {}
            for s in subs:
                by_bot.setdefault(s.bot_type.key if s.bot_type else "?", []).append({
                    "guild": s.guild.discord_id if s.guild else "?",
                    "status": s.status,
                    "cancel_at_period_end": s.cancel_at_period_end,
                    "current_period_end": str(s.current_period_end)
                })

        return jsonify(by_bot)

    @app.get("/scheduler")
    @login_required
    def scheduler_list():
        ids = session.get("admin_guild_ids") or []
        with Session(app.engine) as db:
            guilds = db.scalars(select(Guild).where(Guild.discord_id.in_(ids))).all()
            guild_ids = [g.id for g in guilds]
            tasks = db.scalars(
                select(ScheduledTask).where(ScheduledTask.guild_id.in_(guild_ids))
                .options(selectinload(ScheduledTask.guild))
            ).all()

        return render_template("scheduler.html", tasks=tasks, guilds=guilds, current_user=session.get("user"))

    @app.post("/scheduler/create")
    @login_required
    def scheduler_create():
        guild_discord_id = request.form.get("guild_discord_id")
        bot_key = request.form.get("bot_key")
        task_type = request.form.get("task_type")
        task_param = request.form.get("task_param")
        day_of_week = request.form.get("day_of_week")
        time_of_day = request.form.get("time_of_day")
        channel_id = request.form.get("channel_id")

        ids = session.get("admin_guild_ids") or []
        user = session.get("user") or {}
        
        is_allowed = False
        
        # Check permissions Discord OU Twitch
        if guild_discord_id in ids:
            is_allowed = True
        elif user.get('platform') == 'twitch' and str(user.get('id')) == str(guild_discord_id):
            is_allowed = True
            
        if not is_allowed:
            flash("Erreur de permission (Serveur ou Chaîne inconnue).", "error")
            return redirect(url_for("scheduler_list"))

        with Session(app.engine) as db:
            g = db.scalar(select(Guild).where(Guild.discord_id == guild_discord_id))
            if not g:
                flash("Serveur inconnu.", "error")
                return redirect(url_for("scheduler_list"))

            t = ScheduledTask(
                guild_id=g.id,
                bot_key=bot_key,
                task_type=task_type,
                task_param=task_param,
                frequency="weekly",
                day_of_week=day_of_week,
                time_of_day=time_of_day,
                channel_id=channel_id
            )
            db.add(t)
            db.commit()

        flash("Tâche planifiée avec succès !", "ok")
        return redirect(url_for("scheduler_list"))

    @app.post("/scheduler/delete/<int:task_id>")
    @login_required
    def scheduler_delete(task_id: int):
        ids = session.get("admin_guild_ids") or []
        with Session(app.engine) as db:
            t = db.get(ScheduledTask, task_id)
            if t and t.guild.discord_id in ids:
                db.delete(t)
                db.commit()
                flash("Tâche supprimée.", "ok")
            else:
                flash("Erreur.", "error")

        return redirect(url_for("scheduler_list"))

    @app.get("/admin")
    @admin_required
    def admin_index():
        return redirect(url_for("admin_subs_v2"))

    @app.get("/admin/subs-v2")
    @admin_required
    def admin_subs_v2():
        with Session(app.engine) as db:
            query = select(Subscription).options(
                selectinload(Subscription.guild),
                selectinload(Subscription.bot_type)
            ).order_by(Subscription.id.desc())

            all_subs = db.scalars(query).all()
            
            twitch_guild_ids_with_subs = {s.guild.discord_id for s in all_subs if s.guild.platform == "twitch"}
            all_twitch_guilds = db.scalars(select(Guild).where(Guild.platform == "twitch")).all()
            
            twitch_connected = []
            for guild in all_twitch_guilds:
                if guild.discord_id not in twitch_guild_ids_with_subs:
                    virtual_sub = type('VirtualSub', (), {
                        'id': f"twitch_{guild.discord_id}",
                        'guild': guild,
                        'bot_type': type('VirtualBot', (), {'key': 'deadpool'})(),
                        'status': 'connected',
                        'days_left': None,
                        'current_period_end': None,
                        'trial_until': None,
                        'created_at': None
                    })()
                    twitch_connected.append(virtual_sub)
            
            discord_subs = [s for s in all_subs if s.guild.platform != "twitch"]
            twitch_subs = [s for s in all_subs if s.guild.platform == "twitch"]
            
            stats = {
                "total": len(all_subs),
                "active": len([s for s in all_subs if s.status in ("active", "lifetime")]),
                "trial": len([s for s in all_subs if s.status in ("trial", "trialing")]),
                "canceled": len([s for s in all_subs if s.status in ("canceled", "unpaid", "incomplete")])
            }
            
            platform_stats = {
                "discord": {
                    "total": len(discord_subs),
                    "active": len([s for s in discord_subs if s.status in ("active", "lifetime")]),
                    "trial": len([s for s in discord_subs if s.status in ("trial", "trialing")])
                },
                "twitch": {
                    "total": len(twitch_subs),
                    "active": len([s for s in twitch_subs if s.status in ("active", "lifetime")]),
                    "trial": len([s for s in twitch_subs if s.status in ("trial", "trialing")])
                }
            }

            bot_avatars = _get_bot_avatar_urls()
            all_guilds = db.scalars(select(Guild)).all()
            guild_map = {g.discord_id: g.name for g in all_guilds}
            
            # Récupérer les trial locks pour la gestion des essais
            locks = db.scalars(select(TrialLock).order_by(TrialLock.until.desc())).all()

        return render_template(
            "admin_subs.html",
            subs=all_subs,
            twitch_connected=twitch_connected,
            bot_defs=BOT_DEFS,
            bot_avatars=bot_avatars,
            guild_map=guild_map,
            now=dt.datetime.utcnow(),
            stats=stats,
            platform_stats=platform_stats,
            locks=locks,
            page=1,
            pages=1
        )

    @app.post("/admin/subs/create")
    @admin_required
    def admin_create_sub():
        bot_key = (request.form.get("bot_key") or "").strip()
        guild_id = (request.form.get("guild_discord_id") or "").strip()
        guild_name = (request.form.get("guild_name") or "").strip()

        try:
            days = int(request.form.get("days", 0))
        except:
            days = 0

        st = (request.form.get("status") or "active").strip().lower()
        if st not in ("active", "trial", "canceled", "lifetime"):
            return redirect(url_for("admin_subs_v2"))

        with Session(app.engine) as db:
            g = db.scalar(select(Guild).where(Guild.discord_id == guild_id))
            if not g:
                g = Guild(discord_id=guild_id, name=guild_name if guild_name else f"Guild {guild_id}", platform="discord")
                db.add(g)
                db.commit()

            b = db.scalar(select(BotType).where(BotType.key == bot_key))
            if not b:
                b = BotType(key=bot_key, name=bot_key.capitalize())
                db.add(b)
                db.commit()

            s = db.scalar(select(Subscription).where(Subscription.guild_id == g.id, Subscription.bot_type_id == b.id))
            if not s:
                s = Subscription(guild_id=g.id, bot_type_id=b.id)
                db.add(s)

            s.status = st

            if st == "trial":
                d = days if days > 0 else TRIAL_DAYS
                s.trial_until = dt.datetime.utcnow() + dt.timedelta(days=d)
            else:
                s.trial_until = None

            if st == "active":
                if days > 0:
                    s.current_period_end = dt.datetime.utcnow() + dt.timedelta(days=days)
                else:
                    s.current_period_end = None

            db.commit()

        return redirect(url_for("admin_subs_v2"))

    @app.post("/admin/subs/sync_stripe/<int:sub_id>")
    @admin_required
    def admin_sync_stripe(sub_id: int):
        if not (STRIPE_AVAILABLE and STRIPE_SECRET_KEY):
            return jsonify({"success": False, "error": "Stripe non configuré"}), 400

        with Session(app.engine) as db:
            s = db.get(Subscription, sub_id)
            if not s:
                return jsonify({"success": False, "error": "Subscription introuvable"}), 404

            try:
                if s.stripe_subscription_id:
                    stripe_sub = stripe.Subscription.retrieve(s.stripe_subscription_id)
                else:
                    query = f'metadata["bot_key"]:"{s.bot_type.key}" AND metadata["guild_id"]:"{s.guild.discord_id}"'
                    res = stripe.Subscription.search(query=query, limit=5)
                    items = getattr(res, "data", []) or []
                    if not items:
                        return jsonify({
                            "success": False,
                            "error": f"Aucune sub Stripe trouvée. Query: {query}"
                        }), 404

                    items.sort(key=lambda x: x.created, reverse=True)
                    stripe_sub = items[0]
                    s.stripe_subscription_id = stripe_sub.id

                stripe_status = stripe_sub.status
                if stripe_status in ("active", "trialing", "past_due"):
                    s.status = "active"
                elif stripe_status in ("canceled", "unpaid", "incomplete_expired"):
                    s.status = "canceled"

                s.stripe_customer_id = stripe_sub.customer
                s.cancel_at_period_end = stripe_sub.cancel_at_period_end

                try:
                    period_end = stripe_sub["items"]["data"][0]["current_period_end"]
                    s.current_period_end = dt.datetime.utcfromtimestamp(period_end)
                except (KeyError, IndexError, TypeError):
                    pass

                if stripe_sub.trial_end:
                    s.trial_until = dt.datetime.utcfromtimestamp(stripe_sub.trial_end)

                db.commit()

                return jsonify({
                    "success": True,
                    "status": s.status,
                    "period_end": s.current_period_end.isoformat() if s.current_period_end else None,
                    "stripe_id": s.stripe_subscription_id
                })

            except Exception as e:
                return jsonify({"success": False, "error": str(e)}), 400

    @app.post("/admin/subs/link_stripe/<int:sub_id>")
    @admin_required
    def admin_link_stripe(sub_id: int):
        stripe_id = (request.form.get("stripe_id") or "").strip()
        if not stripe_id.startswith("sub_"):
            flash("ID Stripe invalide", "error")
            return redirect(url_for("admin_subs_v2"))

        with Session(app.engine) as db:
            s = db.get(Subscription, sub_id)
            if not s:
                flash("Subscription introuvable", "error")
                return redirect(url_for("admin_subs_v2"))

            try:
                stripe_sub = stripe.Subscription.retrieve(stripe_id)
                s.stripe_subscription_id = stripe_id
                s.stripe_customer_id = stripe_sub.customer

                stripe_status = stripe_sub.status
                if stripe_status in ("active", "trialing", "past_due"):
                    s.status = "active"
                elif stripe_status in ("canceled", "unpaid", "incomplete_expired"):
                    s.status = "canceled"

                try:
                    period_end = stripe_sub["items"]["data"][0]["current_period_end"]
                    s.current_period_end = dt.datetime.utcfromtimestamp(period_end)
                except (KeyError, IndexError, TypeError):
                    pass

                s.cancel_at_period_end = stripe_sub.cancel_at_period_end
                db.commit()
                flash("✅ Stripe ID lié et synchronisé", "ok")

            except Exception as e:
                flash(f"❌ Erreur: {str(e)}", "error")

        return redirect(url_for("admin_subs_v2"))

    @app.post("/admin/subs/set_status/<int:sub_id>")
    @admin_required
    def admin_set_status(sub_id: int):
        new_status = request.form.get("status")

        with Session(app.engine) as db:
            s = db.get(Subscription, sub_id)
            if s:
                s.status = new_status
                if new_status == "canceled":
                    s.trial_until = None
                    s.current_period_end = None
                db.commit()

        return redirect(url_for("admin_subs_v2"))

    @app.post("/admin/subs/delete/<int:sub_id>")
    @admin_required
    def admin_delete_sub(sub_id: int):
        with Session(app.engine) as db:
            s = db.get(Subscription, sub_id)
            if s:
                db.delete(s)
                db.commit()

        return jsonify({"success": True})

    # --- Admin API routes (intégrées dans make_app) ---
    _register_admin_routes(app)

    return app


def _register_admin_routes(app):
    @app.post("/api/admin/subscription")
    def api_create_subscription():
        u = session.get("user") or {}
        uid = str(u.get("id") or "")
        if uid not in ADMIN_DISCORD_IDS:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        
        data = request.get_json()
        
        try:
            with Session(app.engine) as db:
                guild = db.scalar(select(Guild).where(Guild.discord_id == data['guild_id']))
                if not guild:
                    guild = Guild(
                        discord_id=data['guild_id'],
                        name=data['guild_name'],
                        platform=data['platform']
                    )
                    db.add(guild)
                    db.flush()
                
                subscription = Subscription(
                    guild_id=guild.id,
                    bot_type_id=data['bot_type_id'],
                    status=data['status']
                )
                db.add(subscription)
                db.commit()
                
                return jsonify({"success": True, "subscription_id": subscription.id})
                
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400

    @app.get("/api/bot-types")
    def api_get_bot_types():
        u = session.get("user") or {}
        uid = str(u.get("id") or "")
        if uid not in ADMIN_DISCORD_IDS:
            return jsonify({"error": "Unauthorized"}), 401
        
        try:
            with Session(app.engine) as db:
                bot_types = db.scalars(select(BotType)).all()
                return jsonify([{
                    "id": bt.id,
                    "key": bt.key,
                    "name": bt.name
                } for bt in bot_types])
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.get("/api/discord/channels/<guild_id>")
    def api_discord_channels(guild_id):
        """Récupère les salons d'un serveur Discord pour le planificateur"""
        if not session.get("user"):
            return jsonify({"error": "Unauthorized"}), 401

        # Vérifier que l'utilisateur a accès à ce guild
        admin_ids = session.get("admin_guild_ids") or []
        u = session.get("user") or {}
        if guild_id not in admin_ids and str(u.get("id")) != str(guild_id):
            return jsonify({"error": "Forbidden"}), 403
        
        try:
            # Utiliser le token du bot deadpool pour récupérer les salons
            deadpool_token = os.getenv("DEADPOOL_TOKEN")
            if not deadpool_token:
                print("❌ DEADPOOL_TOKEN non trouvé")
                return jsonify([])
            
            # Appel à l'API Discord pour récupérer les salons du serveur
            headers = {
                "Authorization": f"Bot {deadpool_token}",
                "Content-Type": "application/json"
            }
            
            # Récupérer les salons textuels uniquement
            url = f"https://discord.com/api/v10/guilds/{guild_id}/channels"
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                channels_data = response.json()
                # Filtrer uniquement les salons textuels (type 0)
                text_channels = [
                    {"id": str(ch["id"]), "name": ch["name"]}
                    for ch in channels_data 
                    if ch.get("type") == 0  # 0 = text channel
                ]
                print(f"✅ Récupéré {len(text_channels)} salons pour guild {guild_id}")
                return jsonify(text_channels)
            else:
                print(f"❌ Erreur API Discord: {response.status_code} - {response.text}")
                return jsonify([])
            
        except Exception as e:
            print(f"Erreur récupération salons Discord: {e}")
            return jsonify([])

    # --- AJOUT POUR CONFIGURATION TWITCH ---
    CONFIG_FILE = os.path.join(os.path.dirname(__file__), "bot_config.json")

    def load_bot_config():
        if not os.path.exists(CONFIG_FILE): return {}
        try:
            with open(CONFIG_FILE, 'r') as f: return json.load(f)
        except: return {}

    def save_bot_config(data):
        with open(CONFIG_FILE, 'w') as f: json.dump(data, f, indent=4)

    @app.route('/api/bot/auto-messages/<bot_key>', methods=['GET', 'POST'])
    def api_auto_messages_config(bot_key):
        config = load_bot_config()
        bot_config = config.get(bot_key, {"enabled": False, "interval": 30})

        if request.method == 'POST':
            if not session.get('user'):
                return jsonify({"error": "Unauthorized"}), 401
            data = request.json
            bot_config.update({
                "enabled": bool(data.get("enabled")),
                "interval": int(data.get("interval", 30))
            })
            config[bot_key] = bot_config
            save_bot_config(config)
            return jsonify({"success": True, "config": bot_config})

        # GET: bots use API token, users use session
        if not (_check_api_token() or session.get('user')):
            return jsonify({"error": "Unauthorized"}), 401

        return jsonify(bot_config)
    # ---------------------------------------


if __name__ == "__main__":
    app = make_app()
    app.run(debug=False, host="0.0.0.0", port=5000)

# Créer l'application globale pour gunicorn
app = make_app()