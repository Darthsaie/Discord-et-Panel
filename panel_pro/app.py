import os
import secrets
import datetime as dt

from flask import Flask, redirect, url_for, request, render_template, jsonify, flash, session, abort
from sqlalchemy import create_engine, select, Integer, String, DateTime, ForeignKey, Boolean, event, update
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, Session, selectinload
import requests

from dotenv import load_dotenv
load_dotenv()

# =========================
#   ENV & CONFIG
# =========================
SECRET_KEY       = os.getenv("SECRET_KEY", secrets.token_hex(16))

PANEL_API_TOKEN = os.getenv("PANEL_API_TOKEN")
if not PANEL_API_TOKEN:
    raise ValueError("CRITICAL: PANEL_API_TOKEN is missing from .env configuration!")

DATABASE_URL     = os.getenv("DATABASE_URL", "sqlite:////app/panel.db")
TRIAL_DAYS       = int(os.getenv("TRIAL_DAYS", "5"))
DEV_MODE         = os.getenv("DEV_MODE", "1") == "1"
BASE_URL         = os.getenv("BASE_URL", "http://localhost:5000")

LOG_WEBHOOK      = os.getenv("LOG_WEBHOOK", "1") == "1"

# ===== Stripe =====
try:
    import stripe
    STRIPE_AVAILABLE = True
except Exception:
    stripe = None
    STRIPE_AVAILABLE = False

STRIPE_SECRET_KEY     = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

PRICE_MAP = {
    "homer":    os.getenv("PRICE_HOMER", ""),
    "cartman":  os.getenv("PRICE_CARTMAN", ""),
    "deadpool": os.getenv("PRICE_DEADPOOL", ""),
    "yoda":     os.getenv("PRICE_YODA", ""),
}

if STRIPE_AVAILABLE and STRIPE_SECRET_KEY:
    try:
        stripe.api_key = STRIPE_SECRET_KEY
    except Exception:
        pass

STRIPE_SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL") or f"{BASE_URL.rstrip('/')}/billing/success?session_id={{CHECKOUT_SESSION_ID}}"
STRIPE_CANCEL_URL  = os.getenv("STRIPE_CANCEL_URL")  or f"{BASE_URL.rstrip('/')}/dashboard"
STRIPE_PORTAL_RETURN_URL = os.getenv("STRIPE_PORTAL_RETURN_URL") or f"{BASE_URL.rstrip('/')}/dashboard"

# =========================
#   DISCORD BOTS
# =========================
HOMER_CLIENT_ID    = os.getenv("HOMER_CLIENT_ID", "")
CARTMAN_CLIENT_ID  = os.getenv("CARTMAN_CLIENT_ID", "")
DEADPOOL_CLIENT_ID = os.getenv("DEADPOOL_CLIENT_ID", "")
YODA_CLIENT_ID     = os.getenv("YODA_CLIENT_ID", "")

HOMER_TOKEN    = os.getenv("HOMER_TOKEN", "")
CARTMAN_TOKEN  = os.getenv("CARTMAN_TOKEN", "")
DEADPOOL_TOKEN = os.getenv("DEADPOOL_TOKEN", "")
YODA_TOKEN     = os.getenv("YODA_TOKEN", "")

BOT_DEFS = {
    "homer":    {"name": "Homer",    "client_id": HOMER_CLIENT_ID},
    "cartman":  {"name": "Cartman",  "client_id": CARTMAN_CLIENT_ID},
    "deadpool": {"name": "Deadpool", "client_id": DEADPOOL_CLIENT_ID},
    "yoda":     {"name": "Yoda",     "client_id": YODA_CLIENT_ID},
}
BOT_TOKENS = {
    "homer":    HOMER_TOKEN,
    "cartman":  CARTMAN_TOKEN,
    "deadpool": DEADPOOL_TOKEN,
    "yoda":     YODA_TOKEN,
}

# =========================
#   DB MODELS
# =========================
class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int]       = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String)
    is_owner: Mapped[bool]= mapped_column(Boolean, default=False)

class Guild(Base):
    __tablename__ = "guilds"
    id: Mapped[int]         = mapped_column(Integer, primary_key=True)
    discord_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str]       = mapped_column(String)

class BotType(Base):
    __tablename__ = "bot_types"
    id: Mapped[int]       = mapped_column(Integer, primary_key=True)
    key: Mapped[str]      = mapped_column(String, unique=True)
    name: Mapped[str]     = mapped_column(String)

class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[int]         = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int]   = mapped_column(ForeignKey("guilds.id"))
    bot_type_id: Mapped[int]= mapped_column(ForeignKey("bot_types.id"))
    
    status: Mapped[str]     = mapped_column(String, default="trial")
    trial_until: Mapped[dt.datetime|None] = mapped_column(DateTime, nullable=True)
    
    # Stripe dates
    current_period_end: Mapped[dt.datetime|None] = mapped_column(DateTime, nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=lambda: dt.datetime.utcnow())

    guild: Mapped["Guild"]      = relationship()
    bot_type: Mapped["BotType"] = relationship()

class TrialLock(Base):
    __tablename__ = "trial_locks"
    id: Mapped[int]              = mapped_column(Integer, primary_key=True)
    discord_user_id: Mapped[str] = mapped_column(String, index=True)
    bot_key: Mapped[str]         = mapped_column(String)
    guild_discord_id: Mapped[str]= mapped_column(String)
    until: Mapped[dt.datetime]   = mapped_column(DateTime)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=lambda: dt.datetime.utcnow())

class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"
    id: Mapped[int]           = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int]     = mapped_column(ForeignKey("guilds.id"))
    bot_key: Mapped[str]      = mapped_column(String)
    task_type: Mapped[str]    = mapped_column(String)
    task_param: Mapped[str]   = mapped_column(String, nullable=True)
    frequency: Mapped[str]    = mapped_column(String)
    day_of_week: Mapped[str]  = mapped_column(String, nullable=True)
    time_of_day: Mapped[str]  = mapped_column(String)
    channel_id: Mapped[str]   = mapped_column(String)
    is_active: Mapped[bool]   = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=lambda: dt.datetime.utcnow())
    guild: Mapped["Guild"]    = relationship()

# =========================
#   DISCORD OAuth2
# =========================
DISCORD_CLIENT_ID     = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI  = os.getenv("DISCORD_REDIRECT_URI", BASE_URL.rstrip("/") + "/oauth/callback")
DISCORD_OAUTH_SCOPE   = "identify guilds"
DISCORD_API_BASE      = "https://discord.com/api"

PERM_ADMIN        = 0x00000008
PERM_MANAGE_GUILD = 0x00000020

ADMIN_DISCORD_IDS = {s.strip() for s in (os.getenv("ADMIN_DISCORD_IDS","").split(",")) if s.strip()}

def make_app():
    app = Flask(__name__)
    app.secret_key = SECRET_KEY

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

    def calculate_trial_info(sub):
        if sub.status == 'trial' and sub.trial_until:
            try:
                trial_end = sub.trial_until.replace(tzinfo=None) if sub.trial_until.tzinfo else sub.trial_until
                now = dt.datetime.utcnow().replace(tzinfo=None)
                remaining = trial_end - now
            except Exception:
                return None
            if remaining.total_seconds() > 0:
                days = remaining.days
                if remaining.seconds > 0: days += 1
                if days > 1: return f"Reste {days} jours"
                elif days == 1: return "Reste 1 jour"
                else: return "Reste < 1 jour"
            else:
                return "Expiré"
        return None

    def wlog(*args):
        if LOG_WEBHOOK:
            print("[WEBHOOK]", *args, flush=True)

    def login_required(view):
        from functools import wraps
        @wraps(view)
        def wrapper(*args, **kwargs):
            if DEV_MODE:
                return view(*args, **kwargs)
            if not session.get("user"):
                return redirect(url_for("login_discord"))
            return view(*args, **kwargs)
        return wrapper

    def admin_required(view):
        from functools import wraps
        @wraps(view)
        def wrapper(*args, **kwargs):
            if DEV_MODE:
                return view(*args, **kwargs)
            u = session.get("user") or {}
            uid = str(u.get("id") or "")
            if not ADMIN_DISCORD_IDS:
                if uid:
                    return view(*args, **kwargs)
                return redirect(url_for("login_discord"))
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
        q = "&".join([f"{k}={requests.utils.quote(v)}" for k,v in params.items()])
        return f"{DISCORD_API_BASE}/oauth2/authorize?{q}"

    def _has_admin(perms_value, is_owner: bool) -> bool:
        try:
            perms_int = int(perms_value)
        except Exception:
            perms_int = 0
        return bool(is_owner or (perms_int & (PERM_ADMIN | PERM_MANAGE_GUILD)))

    def _sync_user_and_guilds(access_token: str):
        uh = {"Authorization": f"Bearer {access_token}"}
        u = requests.get(f"{DISCORD_API_BASE}/users/@me", headers=uh, timeout=15)
        g = requests.get(f"{DISCORD_API_BASE}/users/@me/guilds", headers=uh, timeout=15)
        u.raise_for_status(); g.raise_for_status()
        u = u.json(); guilds = g.json() if isinstance(g.json(), list) else []

        admin_ids = []
        guild_icons = {}
        for gg in guilds:
            is_owner = bool(gg.get("owner"))
            perms_val = gg.get("permissions") or gg.get("permissions_new") or 0
            if _has_admin(perms_val, is_owner):
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
                    name = next((x.get("name","") for x in guilds if str(x.get("id"))==gid), "")
                    db.add(Guild(discord_id=gid, name=name))
            db.commit()
        return u

    def _file_exists(path: str) -> bool:
        try:
            return os.path.exists(path)
        except Exception:
            return False

    def _get_bot_avatar_urls() -> dict:
        if app.config.get("BOT_AVATARS"):
            return app.config["BOT_AVATARS"]
        avatars: dict[str, str | None] = {}
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
                        av  = me.get("avatar")
                        if uid and av:
                            url = f"https://cdn.discordapp.com/avatars/{uid}/{av}.png?size=64"
                        elif uid:
                            idx = int(uid) % 5
                            url = f"https://cdn.discordapp.com/embed/avatars/{idx}.png"
                except Exception:
                    pass
            if not url:
                static_path = os.path.join(app.static_folder or "static", "bots", f"{key}.png")
                if _file_exists(static_path):
                    url = f"/static/bots/{key}.png"
            avatars[key] = url
        app.config["BOT_AVATARS"] = avatars
        return avatars

    def _activate_subscription(db: Session, bot_key: str, guild_discord_id: str, current_period_end_ts: int = None):
        g = db.scalar(select(Guild).where(Guild.discord_id==guild_discord_id))
        b = db.scalar(select(BotType).where(BotType.key==bot_key))
        if not (g and b):
            return False
        s = db.scalar(select(Subscription).where((Subscription.guild_id==g.id) & (Subscription.bot_type_id==b.id)))
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

    def _cancel_subscription(db: Session, bot_key: str, guild_discord_id: str):
        g = db.scalar(select(Guild).where(Guild.discord_id==guild_discord_id))
        b = db.scalar(select(BotType).where(BotType.key==bot_key))
        if not (g and b):
            return False
        s = db.scalar(select(Subscription).where((Subscription.guild_id==g.id) & (Subscription.bot_type_id==b.id)))
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
        logged = bool(session.get("user")) or DEV_MODE
        return render_template("home.html", logged=logged, dev_mode=DEV_MODE, trial_days=TRIAL_DAYS, current_user=session.get("user"))

    @app.get("/dashboard")
    def dashboard():
        logged = bool(session.get("user")) or DEV_MODE
        ids = session.get("admin_guild_ids") or []
        guild_icons = session.get("guild_icons") or {}

        with Session(app.engine) as db:
            bots = db.scalars(select(BotType)).all()
            if not bots:
                for k, bd in BOT_DEFS.items():
                    db.add(BotType(key=k, name=bd["name"]))
                db.commit()
                bots = db.scalars(select(BotType)).all()

            guilds = db.scalars(select(Guild).where(Guild.discord_id.in_(ids))).all() if ids else []
            subs = db.scalars(select(Subscription)).all()
            
            if STRIPE_AVAILABLE and STRIPE_SECRET_KEY:
                updated_any = False
                for s in subs:
                    if s.status == "active" and s.guild.discord_id in ids:
                        try:
                            q = f"metadata['bot_key']:'{s.bot_type.key}' AND metadata['guild_id']:'{s.guild.discord_id}'"
                            res = stripe.Subscription.search(query=q, limit=1)
                            items = getattr(res, "data", []) or []
                            found_summary = items[0] if items else None
                            
                            if found_summary:
                                sub_id_stripe = found_summary.get("id")
                                full_sub = stripe.Subscription.retrieve(sub_id_stripe)
                                st = full_sub.get("status", "canceled")
                                s.status = "active" if st in ("active", "trialing", "past_due") else "canceled"
                                s.cancel_at_period_end = full_sub.get("cancel_at_period_end", False)
                                ts = full_sub.get("current_period_end")
                                if ts:
                                    s.current_period_end = dt.datetime.utcfromtimestamp(ts)
                                updated_any = True
                        except Exception as e:
                            print(f"[Auto-Sync Error] {s.guild.discord_id}: {e}")
                if updated_any: db.commit()

            submap: dict[str, dict[str, Subscription]] = {}
            for s in subs:
                submap.setdefault(s.bot_type.key, {})[s.guild.discord_id] = s
                s.trial_remaining_info = calculate_trial_info(s)

            has_any_active = any((s.status in ("active", "lifetime") and s.guild.discord_id in ids) for s in subs)
            bot_avatars = _get_bot_avatar_urls()

            active_lock = None
            trial_ever = False
            if logged:
                user_id = (session.get("user") or {}).get("id") or "dev"
                now = dt.datetime.utcnow()
                with Session(app.engine) as db2:
                    active_lock = db2.scalar(
                        select(TrialLock).where(TrialLock.discord_user_id==user_id, TrialLock.until > now)
                    )
                    trial_ever = bool(db2.scalar(
                        select(TrialLock.id).where(TrialLock.discord_user_id==user_id)
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

    @app.post("/trial/start/<bot_key>/<guild_id>")
    def trial_start(bot_key, guild_id):
        user_id = (session.get("user") or {}).get("id") or ("dev" if DEV_MODE else None)
        if not user_id:
            flash("Tu dois être connecté.", "error")
            return redirect(url_for("dashboard"))

        now = dt.datetime.utcnow()
        with Session(app.engine) as db:
            any_lock = db.scalar(select(TrialLock).where(TrialLock.discord_user_id == user_id))
            if any_lock:
                flash("Tu as déjà consommé ton essai gratuit.", "error")
                return redirect(url_for("dashboard"))

            g = db.scalar(select(Guild).where(Guild.discord_id==guild_id))
            b = db.scalar(select(BotType).where(BotType.key==bot_key))
            if not (g and b):
                flash("Bot/serveur introuvable.", "error")
                return redirect(url_for("dashboard"))

            s = db.scalar(select(Subscription).where((Subscription.guild_id==g.id) & (Subscription.bot_type_id==b.id)))
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
    def trial_cancel(bot_key, guild_id):
        if not DEV_MODE: abort(403)
        with Session(app.engine) as db:
            g = db.scalar(select(Guild).where(Guild.discord_id==guild_id))
            b = db.scalar(select(BotType).where(BotType.key==bot_key))
            if g and b:
                s = db.scalar(select(Subscription).where((Subscription.guild_id==g.id) & (Subscription.bot_type_id==b.id)))
                if s:
                    s.status = "canceled"
                    s.trial_until = None
                    s.current_period_end = None
                db.commit()
        flash("(DEV) Essai annulé.", "ok")
        return redirect(url_for("dashboard"))

    @app.post("/subscribe/<bot_key>/<guild_id>")
    def subscribe(bot_key, guild_id):
        if not (STRIPE_AVAILABLE and STRIPE_SECRET_KEY.startswith("sk_") and PRICE_MAP.get(bot_key)):
            flash("Stripe non configuré.", "error")
            return redirect(url_for("dashboard"))
        user = session.get("user")
        if not user:
            flash("Connecte-toi.", "error")
            return redirect(url_for("dashboard"))
        with Session(app.engine) as db:
            g = db.scalar(select(Guild).where(Guild.discord_id==guild_id))
            b = db.scalar(select(BotType).where(BotType.key==bot_key))
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
                client_reference_id=f"{bot_key}:{guild_id}:{(user or {}).get('id')}",
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
                bot_key = meta.get("bot_key")
                guild_id = meta.get("guild_id")
                
                period_end_ts = None
                sub_id = sess.get("subscription")
                if sub_id:
                    if isinstance(sub_id, str):
                        sub_data = stripe.Subscription.retrieve(sub_id)
                        period_end_ts = sub_data.get("current_period_end")
                    elif hasattr(sub_id, "current_period_end"):
                        period_end_ts = sub_id.current_period_end

                if bot_key and guild_id:
                    with Session(app.engine) as db:
                        _activate_subscription(db, bot_key, guild_id, period_end_ts)
                        flash("Abonnement activé avec succès !", "ok")
                        return redirect(url_for("dashboard"))
            except Exception as e:
                flash(f"Info: Paiement reçu, activation en cours... ({e})", "info")
        
        return redirect(url_for("dashboard"))

    def _find_customer_for(bot_key, guild_id):
        try:
            q = f"status:'active' AND metadata['bot_key']:'{bot_key}' AND metadata['guild_id']:'{guild_id}'"
            res = stripe.Subscription.search(query=q, limit=1)
            items = getattr(res, "data", []) or []
            if items: return items[0]["customer"]
            q2 = f"metadata['bot_key']:'{bot_key}' AND metadata['guild_id']:'{guild_id}'"
            res = stripe.Subscription.search(query=q2, limit=1)
            items = getattr(res, "data", []) or []
            if items: return items[0]["customer"]
        except Exception as e: print("[portal] error:", e)
        return None

    @app.post("/billing/portal/<bot_key>/<guild_id>")
    def billing_portal(bot_key, guild_id):
        if not (STRIPE_AVAILABLE and STRIPE_SECRET_KEY.startswith("sk_")):
            flash("Billing Portal indisponible.", "error")
            return redirect(url_for("dashboard"))
        try:
            customer_id = _find_customer_for(bot_key, guild_id)
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
        if not (STRIPE_AVAILABLE and STRIPE_WEBHOOK_SECRET): return "not configured", 400
        payload = request.get_data(as_text=True)
        sig = request.headers.get("Stripe-Signature", "")
        try: event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
        except: return "invalid", 400
        etype = event.get("type")
        obj = event["data"]["object"]

        def _update_sub_data(db: Session, bot_key, guild_id, stripe_sub):
            g = db.scalar(select(Guild).where(Guild.discord_id==guild_id))
            b = db.scalar(select(BotType).where(BotType.key==bot_key))
            if g and b:
                s = db.scalar(select(Subscription).where((Subscription.guild_id==g.id) & (Subscription.bot_type_id==b.id)))
                if not s:
                    s = Subscription(guild_id=g.id, bot_type_id=b.id)
                    db.add(s)
                status = stripe_sub.get("status", "")
                if status in ("active", "trialing", "past_due"):
                    s.status = "active"
                elif status in ("canceled", "unpaid", "incomplete_expired"):
                    s.status = "canceled"
                s.cancel_at_period_end = stripe_sub.get("cancel_at_period_end", False)
                ts = stripe_sub.get("current_period_end")
                if ts: s.current_period_end = dt.datetime.utcfromtimestamp(ts)
                db.commit()

        if etype in ("customer.subscription.updated", "customer.subscription.created"):
            meta = obj.get("metadata") or {}
            if meta.get("bot_key") and meta.get("guild_id"):
                with Session(app.engine) as db: _update_sub_data(db, meta.get("bot_key"), meta.get("guild_id"), obj)
            return "", 200

        if etype == "checkout.session.completed":
            try:
                sess_id = obj.get("id")
                full = stripe.checkout.Session.retrieve(sess_id)
                meta = full.get("metadata") or {}
                ts = None
                sub_id = full.get("subscription")
                if sub_id:
                    if isinstance(sub_id, str):
                        sub_data = stripe.Subscription.retrieve(sub_id)
                        ts = sub_data.get("current_period_end")
                    elif hasattr(sub_id, "current_period_end"):
                        ts = sub_id.current_period_end

                if meta.get("bot_key") and meta.get("guild_id"):
                    with Session(app.engine) as db: 
                        _activate_subscription(db, meta.get("bot_key"), meta.get("guild_id"), ts)
            except:
                pass
            return "", 200

        if etype in ("invoice.payment_succeeded", "invoice.paid"):
            sub_id = obj.get("subscription")
            if sub_id:
                try:
                    if isinstance(sub_id, str):
                        sub = stripe.Subscription.retrieve(sub_id)
                    else:
                        sub = sub_id 
                    meta = getattr(sub, "metadata", {}) or {}
                    bot_key = meta.get("bot_key")
                    guild_id = meta.get("guild_id")
                    if bot_key and guild_id:
                        ts = sub.current_period_end
                        with Session(app.engine) as db:
                            _activate_subscription(db, bot_key, guild_id, ts)
                except: pass
            return "", 200

        if etype == "customer.subscription.deleted":
            meta = obj.get("metadata") or {}
            if meta.get("bot_key") and meta.get("guild_id"):
                with Session(app.engine) as db: _cancel_subscription(db, meta.get("bot_key"), meta.get("guild_id"))
            return "", 200
        return "", 200

    @app.get("/invite/<bot_key>/<guild_id>")
    def invite(bot_key, guild_id):
        bot_def = BOT_DEFS.get(bot_key)
        if not bot_def: return redirect(url_for("dashboard"))
        cid = bot_def["client_id"]
        oauth = f"https://discord.com/api/oauth2/authorize?client_id={cid}&permissions=2147483648&scope=bot&guild_id={guild_id}&disable_guild_select=true"
        return redirect(oauth)

    # =========================================================================
    #  MODIFICATION CRITIQUE : MODE CONFIANCE + GESTION CANCELED
    # =========================================================================
    @app.get("/api/bot/config/<bot_key>")
    def api_bot_config(bot_key):
        if request.args.get("token") != PANEL_API_TOKEN: return jsonify({"error": "unauthorized"}), 401
        
        now = dt.datetime.utcnow()
        allowed = []
        
        with Session(app.engine) as db:
            for s in db.scalars(select(Subscription)).all():
                if s.bot_type.key == bot_key:
                    is_allowed = False
                    
                    # 1. Cas VIP / A vie
                    if s.status == "lifetime":
                        is_allowed = True
                        
                    # 2. Cas Essai (Trial)
                    elif s.status == "trial":
                        if s.trial_until and s.trial_until > now:
                            is_allowed = True
                            
                    # 3. Cas Abonnement Actif (MODE CONFIANCE)
                    # Si c'est marqué "active", on autorise TOUJOURS (pour éviter le blocage si la date est vieille à cause d'un webhook raté)
                    elif s.status == "active":
                        is_allowed = True

                    # 4. Cas Annulé mais période pas finie (Stripe "cancel_at_period_end")
                    elif s.status == "canceled":
                        if s.current_period_end and s.current_period_end > now:
                            is_allowed = True

                    if is_allowed:
                        allowed.append(int(s.guild.discord_id))
                        
        return jsonify({"bot_key": bot_key, "allowed_guild_ids": allowed})
    # =========================================================================
        
    @app.get("/api/bot/tasks/<bot_key>")
    def api_bot_tasks(bot_key):
        if request.args.get("token") != PANEL_API_TOKEN: return jsonify({"error": "unauthorized"}), 401
        
        with Session(app.engine) as db:
            tasks = db.scalars(select(ScheduledTask).where(ScheduledTask.bot_key == bot_key, ScheduledTask.is_active == True)).all()
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

    @app.post("/logout")
    @app.get("/logout")
    def logout_discord():
        session.clear()
        flash("Déconnecté.", "ok")
        return redirect(url_for("index"))

    @app.get("/login")
    def login_discord():
        url = oauth_authorize_url()
        return render_template('auth_bouncer.html', auth_url=url)

    @app.get("/oauth/callback")
    def oauth_callback():
        code = request.args.get("code")
        if not code: return redirect(url_for("dashboard"))
        data = {"client_id": DISCORD_CLIENT_ID, "client_secret": DISCORD_CLIENT_SECRET, "grant_type": "authorization_code", "code": code, "redirect_uri": DISCORD_REDIRECT_URI}
        r = requests.post(f"{DISCORD_API_BASE}/oauth2/token", data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        if r.status_code != 200: return redirect(url_for("dashboard"))
        acc = r.json().get("access_token")
        session["oauth"] = {"access_token": acc}
        u = _sync_user_and_guilds(acc)
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
            u = _sync_user_and_guilds(session["oauth"]["access_token"])
            session["user"] = {
                "id": u.get("id"),
                "username": u.get("username"),
                "discord_id": u.get("id"),
                "avatar_hash": u.get("avatar")
            }
        except: return redirect(url_for("login_discord"))
        return redirect(url_for("dashboard"))

    @app.get("/__stripe_status")
    def stripe_status():
        with Session(app.engine) as db:
            subs = db.scalars(select(Subscription).options(selectinload(Subscription.guild),selectinload(Subscription.bot_type))).all()
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
            tasks = db.scalars(select(ScheduledTask).where(ScheduledTask.guild_id.in_(guild_ids)).options(selectinload(ScheduledTask.guild))).all()
        return render_template("scheduler.html", tasks=tasks, guilds=guilds, current_user=session.get("user"))

    @app.post("/scheduler/create")
    @login_required
    def scheduler_create():
        guild_discord_id = request.form.get("guild_discord_id")
        bot_key = request.form.get("bot_key")
        task_type = request.form.get("task_type")
        task_param = request.form.get("task_param") # PARAM
        day_of_week = request.form.get("day_of_week") 
        time_of_day = request.form.get("time_of_day") 
        channel_id = request.form.get("channel_id")
        
        ids = session.get("admin_guild_ids") or []
        if guild_discord_id not in ids:
            flash("Erreur de permission.", "error")
            return redirect(url_for("scheduler_list"))
            
        with Session(app.engine) as db:
            g = db.scalar(select(Guild).where(Guild.discord_id == guild_discord_id))
            if not g: 
                flash("Serveur inconnu.", "error"); return redirect(url_for("scheduler_list"))
            
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
    def scheduler_delete(task_id):
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
    def admin_index(): return redirect(url_for("admin_subs"))

    @app.get("/admin/subs")
    @admin_required
    def admin_subs():
        with Session(app.engine) as db:
            subs = db.scalars(select(Subscription).options(selectinload(Subscription.guild),selectinload(Subscription.bot_type)).order_by(Subscription.id.desc())).all()
            locks = db.scalars(select(TrialLock).order_by(TrialLock.id.desc())).all()
            
            bot_avatars = _get_bot_avatar_urls()
            all_guilds = db.scalars(select(Guild)).all()
            guild_map = {g.discord_id: g.name for g in all_guilds}

        return render_template("admin_subs.html", subs=subs, locks=locks, bot_defs=BOT_DEFS, bot_avatars=bot_avatars, guild_map=guild_map, now=dt.datetime.utcnow())

    @app.post("/admin/subs/create")
    @admin_required
    def admin_create_sub():
        bot_key = (request.form.get("bot_key") or "").strip()
        guild_id = (request.form.get("guild_discord_id") or "").strip()
        guild_name = (request.form.get("guild_name") or "").strip()
        try: days = int(request.form.get("days", "0"))
        except: days = 0
        st = (request.form.get("status") or "active").strip().lower()
        if st not in ("active", "trial", "canceled", "lifetime"): return redirect(url_for("admin_subs"))
        with Session(app.engine) as db:
            g = db.scalar(select(Guild).where(Guild.discord_id == guild_id))
            if not g: 
                g = Guild(discord_id=guild_id, name=guild_name if guild_name else f"Guild {guild_id}")
                db.add(g); db.commit()
            b = db.scalar(select(BotType).where(BotType.key == bot_key))
            if not b: 
                b = BotType(key=bot_key, name=bot_key.capitalize())
                db.add(b); db.commit()
            s = db.scalar(select(Subscription).where((Subscription.guild_id==g.id) & (Subscription.bot_type_id==b.id)))
            if not s: s = Subscription(guild_id=g.id, bot_type_id=b.id); db.add(s)
            s.status = st
            if st == "trial": 
                d = days if days > 0 else TRIAL_DAYS
                s.trial_until = dt.datetime.utcnow() + dt.timedelta(days=d)
            else: 
                s.trial_until = None
            if st == "active":
                if days > 0:
                    s.current_period_end = dt.datetime.utcnow() + dt.timedelta(days=days)
                    s.cancel_at_period_end = True 
                else:
                    s.current_period_end = None 
            db.commit()
        return redirect(url_for("admin_subs"))

    @app.post("/admin/subs/sync_stripe/<int:sub_id>")
    @admin_required
    def admin_sync_stripe(sub_id: int):
        if not (STRIPE_AVAILABLE and STRIPE_SECRET_KEY):
            flash("Stripe non configuré.", "error")
            return redirect(url_for("admin_subs"))
        with Session(app.engine) as db:
            s = db.get(Subscription, sub_id)
            if not s: return redirect(url_for("admin_subs"))
            try:
                q = f"metadata['bot_key']:'{s.bot_type.key}' AND metadata['guild_id']:'{s.guild.discord_id}'"
                res = stripe.Subscription.search(query=q, limit=5)
                items = getattr(res, "data", []) or []
                if not items:
                    flash(f"🔍 INTROUVABLE. Recherche: {q}", "error")
                    return redirect(url_for("admin_subs"))
                items.sort(key=lambda x: x.created, reverse=True)
                target_sub = items[0]
                full_sub = stripe.Subscription.retrieve(target_sub.id)
                try: sub_dict = full_sub.to_dict()
                except: sub_dict = dict(full_sub)
                st = sub_dict.get("status")
                ts = sub_dict.get("current_period_end")
                if not ts: ts = sub_dict.get("billing_cycle_anchor")
                if not ts: ts = sub_dict.get("cancel_at")
                cancel = sub_dict.get("cancel_at_period_end")
                debug_msg = f"DEBUG STRIPE > ID: {target_sub.id} | Status: {st} | Timestamp: {ts}"
                if ts: debug_msg += f" ({dt.datetime.utcfromtimestamp(ts).strftime('%d/%m/%Y')})"
                else: debug_msg += " (DATE NULLE !)"
                flash(debug_msg, "warn") 
                new_status = "active" if st in ("active", "trialing", "past_due") else "canceled"
                new_date = dt.datetime.utcfromtimestamp(ts) if ts else None
                stmt = (update(Subscription).where(Subscription.id == sub_id).values(status=new_status, cancel_at_period_end=bool(cancel), current_period_end=new_date))
                db.execute(stmt)
                db.commit()
            except Exception as e:
                flash(f"💥 ERREUR PYTHON : {str(e)}", "error")
        return redirect(url_for("admin_subs"))

    @app.post("/admin/subs/link_stripe/<int:sub_id>")
    @admin_required
    def admin_link_stripe(sub_id: int):
        stripe_id = request.form.get("stripe_id", "").strip()
        if not (STRIPE_AVAILABLE and STRIPE_SECRET_KEY and stripe_id):
            flash("Configuration Stripe ou ID manquant.", "error")
            return redirect(url_for("admin_subs"))
        with Session(app.engine) as db:
            s = db.get(Subscription, sub_id)
            if not s: return redirect(url_for("admin_subs"))
            try:
                sub = stripe.Subscription.retrieve(stripe_id)
                stripe.Subscription.modify(stripe_id, metadata={"bot_key": s.bot_type.key, "guild_id": s.guild.discord_id})
                ts = sub.get("current_period_end")
                cancel = sub.get("cancel_at_period_end")
                status = sub.get("status")
                new_status = "active" if status in ("active", "trialing", "past_due") else "canceled"
                new_date = dt.datetime.utcfromtimestamp(ts) if ts else None
                s.status = new_status
                s.current_period_end = new_date
                s.cancel_at_period_end = bool(cancel)
                db.commit()
                flash(f"✅ Abonnement lié et synchronisé ! (Fin : {new_date})", "ok")
            except Exception as e:
                flash(f"Erreur Liaison : {str(e)}", "error")
        return redirect(url_for("admin_subs"))

    @app.post("/admin/subs/set_status/<int:sub_id>")
    @admin_required
    def admin_set_status(sub_id: int):
        st = (request.form.get("status") or "").strip().lower()
        if st not in ("active", "trial", "canceled", "lifetime"): return redirect(url_for("admin_subs"))
        with Session(app.engine) as db:
            s = db.get(Subscription, sub_id)
            if s:
                s.status = st
                if st == "trial": s.trial_until = dt.datetime.utcnow() + dt.timedelta(days=TRIAL_DAYS)
                else: s.trial_until = None
                s.current_period_end = None 
                s.cancel_at_period_end = False
                db.commit()
        return redirect(url_for("admin_subs"))

    @app.post("/admin/subs/prolong/<int:sub_id>")
    @admin_required
    def admin_prolong_trial(sub_id: int):
        try: days = int(request.form.get("days", "0"))
        except: days = 0
        with Session(app.engine) as db:
            s = db.get(Subscription, sub_id)
            if s and s.status == "trial":
                base = s.trial_until or dt.datetime.utcnow()
                s.trial_until = base + dt.timedelta(days=days)
                db.commit()
                flash(f"Ajouté {days} jours d'essai.", "ok")
            else:
                flash("Impossible: pas en essai.", "error")
        return redirect(url_for("admin_subs"))

    @app.post("/admin/subs/delete/<int:sub_id>")
    @admin_required
    def admin_delete_sub(sub_id: int):
        with Session(app.engine) as db:
            s = db.get(Subscription, sub_id)
            if s: db.delete(s); db.commit()
        return redirect(url_for("admin_subs"))

    @app.post("/admin/locks/release/<int:lock_id>")
    @admin_required
    def admin_release_lock(lock_id: int):
        with Session(app.engine) as db:
            l = db.get(TrialLock, lock_id)
            if l: db.delete(l); db.commit()
        return redirect(url_for("admin_subs"))

    @app.get("/api/discord/channels/<guild_id>")
    @login_required
    def api_get_channels(guild_id):
        if guild_id not in (session.get("admin_guild_ids") or []):
            return jsonify({"error": "Forbidden"}), 403
        channels = []
        for key, token in BOT_TOKENS.items():
            if not token: continue
            try:
                r = requests.get(f"{DISCORD_API_BASE}/guilds/{guild_id}/channels", headers={"Authorization": f"Bot {token}"}, timeout=3)
                if r.status_code == 200:
                    data = r.json()
                    filtered = [c for c in data if c.get("type") in (0, 5)]
                    filtered.sort(key=lambda x: x.get("position", 0))
                    channels = [{"id": c["id"], "name": c["name"]} for c in filtered]
                    break 
            except: continue
        return jsonify(channels)
    
    @app.route('/privacy')
    def privacy_policy():
        return render_template('privacy.html')

    return app

app = make_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","5000")))