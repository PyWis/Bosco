import logging
from flask import Flask
from flask_login import LoginManager
from apscheduler.schedulers.background import BackgroundScheduler

from config import Config
from app.models import db, User, GameState, Village, Building, Inhabitant
from app.models import MALE_NAMES, FEMALE_NAMES, SURNAMES

import random

login_manager = LoginManager()
scheduler     = BackgroundScheduler(timezone='UTC')


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Extensions
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view  = 'auth.login'
    login_manager.login_message = 'Accedi per continuare.'
    login_manager.login_message_category = 'warning'

    # Blueprints
    from app.routes.auth            import auth_bp
    from app.routes.village         import village_bp
    from app.routes.inhabitants     import inhabitants_bp
    from app.routes.training_ground import training_ground_bp
    from app.routes.admin           import admin_bp
    from app.routes.api             import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(village_bp)
    app.register_blueprint(inhabitants_bp)
    app.register_blueprint(training_ground_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)

    # DB init + seed
    with app.app_context():
        db.create_all()
        _seed_superadmin(app)
        _seed_game_state()
        _migrate_villages()   # aggiunge edifici mancanti alle ville esistenti

    # Scheduler
    from app.services.turn_processor import run_turn
    minutes = app.config['TURN_DURATION_MINUTES']
    scheduler.add_job(
        func    = run_turn,
        args    = [app],
        trigger = 'interval',
        minutes = minutes,
        id      = 'turn_job',
        replace_existing = True,
    )
    if not scheduler.running:
        scheduler.start()
        logging.getLogger(__name__).info(
            f"Scheduler avviato: turno ogni {minutes} minuti."
        )

    return app


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------
def _seed_superadmin(app):
    from werkzeug.security import generate_password_hash
    cfg = app.config
    if not User.query.filter_by(is_superadmin=True).first():
        admin = User(
            username      = cfg['SUPERADMIN_USER'],
            email         = cfg['SUPERADMIN_EMAIL'],
            is_superadmin = True,
            kingdom       = 'Kenn',
            setup_complete= True,
        )
        admin.set_password(cfg['SUPERADMIN_PASSWORD'])
        db.session.add(admin)
        db.session.commit()
        logging.getLogger(__name__).info("SuperAdmin creato.")


def _seed_game_state():
    if not GameState.query.first():
        gs = GameState()
        db.session.add(gs)
        db.session.commit()
        logging.getLogger(__name__).info("GameState inizializzato: Talassio anno 1 dF.")


def _create_starting_village(user: User, village_name: str, kingdom_name: str):
    """Create initial village for a new player."""
    village = Village(
        user_id      = user.id,
        name         = village_name,
        kingdom_name = kingdom_name,
        food         = 10,
        tools        = 0,
    )
    db.session.add(village)
    db.session.flush()  # get village.id

    # Starting buildings (level 1)
    for btype in ('house', 'field', 'workshop', 'training_ground'):
        db.session.add(Building(village_id=village.id, type=btype, level=1))

    # Starting inhabitants (5, age 18, 50/50 gender)
    for i in range(5):
        gender = 'M' if i % 2 == 0 else 'F'
        first  = random.choice(MALE_NAMES if gender == 'M' else FEMALE_NAMES)
        last   = random.choice(SURNAMES)
        inh = Inhabitant(
            village_id  = village.id,
            first_name  = first,
            last_name   = last,
            gender      = gender,
            age         = 18,
            birth_month = random.randint(0, 11),
            level_type  = 'J',
            level_num   = 0,
            training_pts= 0,
            is_alive    = True,
        )
        db.session.add(inh)

    db.session.commit()
    return village


def _migrate_villages():
    """Aggiunge edifici e colonne mancanti alle ville già esistenti."""
    # --- Colonne nuove su Inhabitant (ALTER TABLE per SQLite) ---
    new_cols = {
        'specialization':  'VARCHAR(30)',
        'stat_vit':        'INTEGER',
        'stat_str':        'INTEGER',
        'stat_mag':        'INTEGER',
        'stat_dex':        'INTEGER',
        'm_training_pts':  'INTEGER DEFAULT 0',
    }
    with db.engine.connect() as conn:
        import sqlalchemy as sa
        existing = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(inhabitants)"))}
        for col, col_type in new_cols.items():
            if col not in existing:
                conn.execute(sa.text(f"ALTER TABLE inhabitants ADD COLUMN {col} {col_type}"))

        # Colonne nuove su Village
        v_existing = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(villages)"))}
        if 'block_arrivals' not in v_existing:
            conn.execute(sa.text("ALTER TABLE villages ADD COLUMN block_arrivals BOOLEAN DEFAULT 0"))

        conn.commit()

    # --- Edifici mancanti nelle ville esistenti ---
    for village in Village.query.all():
        existing_types = {b.type for b in village.buildings}
        for btype in ('house', 'field', 'workshop', 'training_ground'):
            if btype not in existing_types:
                db.session.add(Building(village_id=village.id, type=btype, level=1))
    db.session.commit()
