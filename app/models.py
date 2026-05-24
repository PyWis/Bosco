from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

MONTHS = [
    "Talassio",   # 0  – Gennaio
    "Februo",     # 1  – Febbraio
    "Zefiro",     # 2  – Marzo
    "Florio",     # 3  – Aprile
    "Cerere",     # 4  – Maggio
    "Solstizio",  # 5  – Giugno
    "Arido",      # 6  – Luglio
    "Vulcani",    # 7  – Agosto
    "Vindemio",   # 8  – Settembre
    "Oliveto",    # 9  – Ottobre
    "Ctonio",     # 10 – Novembre
    "Brumale",    # 11 – Dicembre
]

KINGDOMS = {
    'Kenn':   'yellow',
    'Drassi': 'blue',
    'Whasi':  'red',
}


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80),  unique=True, nullable=False)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_superadmin = db.Column(db.Boolean, default=False)
    kingdom       = db.Column(db.String(20))   # Kenn | Drassi | Whasi
    setup_complete= db.Column(db.Boolean, default=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    village = db.relationship('Village', backref='user', uselist=False,
                              cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def color(self):
        return KINGDOMS.get(self.kingdom, 'yellow')

    def __repr__(self):
        return f'<User {self.username}>'


# ---------------------------------------------------------------------------
# Global game state (one row)
# ---------------------------------------------------------------------------
class GameState(db.Model):
    __tablename__ = 'game_state'

    id            = db.Column(db.Integer, primary_key=True)
    current_month = db.Column(db.Integer, default=0)   # 0-11
    current_year  = db.Column(db.Integer, default=1)
    turn_number   = db.Column(db.Integer, default=1)
    last_turn_time= db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def month_name(self):
        return MONTHS[self.current_month]

    @property
    def date_string(self):
        return f"{self.month_name} anno {self.current_year} dF"

    def advance(self):
        self.turn_number   += 1
        self.current_month  = (self.current_month + 1) % 12
        if self.current_month == 0:
            self.current_year += 1
        self.last_turn_time = datetime.utcnow()


# ---------------------------------------------------------------------------
# Village
# ---------------------------------------------------------------------------
class Village(db.Model):
    __tablename__ = 'villages'

    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name         = db.Column(db.String(100))
    kingdom_name = db.Column(db.String(100))
    food         = db.Column(db.Integer, default=10)
    tools        = db.Column(db.Integer, default=0)

    buildings  = db.relationship('Building',   backref='village',
                                 cascade='all, delete-orphan')
    inhabitants= db.relationship('Inhabitant', backref='village',
                                 cascade='all, delete-orphan')
    turn_logs  = db.relationship('TurnLog',    backref='village',
                                 cascade='all, delete-orphan',
                                 order_by='TurnLog.id.desc()')

    # ------------------------------------------------------------------
    # Computed helpers
    # ------------------------------------------------------------------
    @property
    def house(self):
        return next((b for b in self.buildings if b.type == 'house'), None)

    @property
    def field(self):
        return next((b for b in self.buildings if b.type == 'field'), None)

    @property
    def workshop(self):
        return next((b for b in self.buildings if b.type == 'workshop'), None)

    @property
    def training_ground(self):
        return next((b for b in self.buildings if b.type == 'training_ground'), None)

    @property
    def max_training_ground_spots(self):
        tg = self.training_ground
        return tg.level * 2 if tg else 0

    @property
    def max_inhabitants(self):
        h = self.house
        return h.level * 10 if h else 0

    @property
    def max_field_workers(self):
        f = self.field
        return f.level * 5 if f else 0

    @property
    def max_workshop_workers(self):
        w = self.workshop
        return w.level * 5 if w else 0

    @property
    def alive_inhabitants(self):
        return [i for i in self.inhabitants if i.is_alive]

    @property
    def working_inhabitants(self):
        return [i for i in self.alive_inhabitants if i.can_work]

    @property
    def total_inhabitants(self):
        return len(self.alive_inhabitants)

    def __repr__(self):
        return f'<Village {self.name}>'


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------
BUILDING_MAX_LEVEL = 28

def upgrade_cost(current_level: int) -> int:
    """Cost (in tools) to upgrade FROM current_level."""
    import math
    return int(10 * (1.5 ** (current_level - 1)))


# Base cost multipliers per building type
BUILDING_BASE_COSTS = {
    'house':          10,
    'field':          10,
    'workshop':       10,
    'training_ground': 20,
}

# Specialisation strings keyed by gender
SPECIALIZATIONS = {
    'M': ['Guerriero', 'Mago', 'Sacerdote'],
    'F': ['Guerriera', 'Maga', 'Sacerdotessa'],
}

def m_level_step_cost(level_num: int) -> int:
    """Punti m_training_pts necessari per avanzare da M(level_num) a M(level_num+1)."""
    return int(28 * (1.37 ** (level_num - 1)))

def m_cumulative_threshold(level_num: int) -> int:
    """Totale m_training_pts cumulativo per trovarsi a M(level_num). M0 e M1 = 0."""
    if level_num <= 1:
        return 0
    return sum(m_level_step_cost(k) for k in range(1, level_num))

def generate_stats(age: int):
    """Genera VIT, STR, MAG, DEX casuali rispettando i vincoli di età.
    age >= 18 → somma ≤ 50; age < 18 → somma ≥ 25."""
    import random
    for _ in range(10_000):
        v, s, m, d = (random.randint(0, 20) for _ in range(4))
        total = v + s + m + d
        if age >= 18 and total <= 50:
            return v, s, m, d
        if age < 18 and total >= 25:
            return v, s, m, d
    return 10, 10, 10, 10  # fallback


class Building(db.Model):
    __tablename__ = 'buildings'

    id               = db.Column(db.Integer, primary_key=True)
    village_id       = db.Column(db.Integer, db.ForeignKey('villages.id'), nullable=False)
    type             = db.Column(db.String(20), nullable=False)  # house|field|workshop
    level            = db.Column(db.Integer, default=1)
    upgrade_pending  = db.Column(db.Boolean, default=False)
    upgrade_at_turn  = db.Column(db.Integer, nullable=True)  # game turn when it completes

    LABELS = {
        'house':           'Case',
        'field':           'Campi',
        'workshop':        'Officina',
        'training_ground': 'Campo di Addestramento',
    }

    @property
    def label(self):
        return self.LABELS.get(self.type, self.type)

    @property
    def next_level_cost(self):
        base = BUILDING_BASE_COSTS.get(self.type, 10)
        return int(base * (1.5 ** (self.level - 1)))

    @property
    def at_max_level(self):
        return self.level >= BUILDING_MAX_LEVEL

    @property
    def capacity_description(self):
        if self.type == 'house':
            return f"{self.level * 10} abitanti"
        elif self.type == 'field':
            return f"{self.level * 5} lavoratori → {self.level * 5} cibo/slot"
        elif self.type == 'workshop':
            return f"{self.level * 5} lavoratori → {self.level * 5} attrezzi/slot"
        elif self.type == 'training_ground':
            return f"{self.level * 2} abitanti M → 1 pt/slot"
        return ''

    def __repr__(self):
        return f'<Building {self.type} lv{self.level}>'


# ---------------------------------------------------------------------------
# Inhabitant
# ---------------------------------------------------------------------------
MALE_NAMES = [
    "Aethelon","Alisandro","Antandro","Argiris","Arisbo","Artaxas","Ascylto",
    "Balisandro","Callias","Cidro","Cosimo","Damone","Dario","Demetrio","Diomede",
    "Eaco","Egidio","Eliano","Erebo","Evandro","Falaride","Filone","Galeno",
    "Gauro","Giasone","Icaro","Isidoro","Leandro","Licaone","Lisimaco","Melito",
    "Menandro","Mirone","Nereo","Nicandro","Olimpo","Oronzo","Palemone",
    "Pancrazio","Phaneas","Sandro","Silas","Talaro","Talete","Tarconte",
    "Tersite","Tindari","Ulisse","Vandalo","Zaleuco",
]

FEMALE_NAMES = [
    "Acantha","Alcesta","Altea","Amira","Anatolia","Andromeda","Aretusa",
    "Ariadne","Arsinoe","Atalanta","Calliope","Calipso","Cassandra","Cirene",
    "Clio","Cora","Dafne","Damaris","Demetria","Egea","Elettra","Elena",
    "Eudossia","Eulalia","Fedra","Filomela","Galatea","Ilaria","Iside",
    "Ismene","Leda","Leandra","Ligeia","Lycoris","Melania","Melissa","Mirina",
    "Myrto","Nausicaa","Nerina","Olimpia","Partenope","Penelope","Rhodia",
    "Selene","Sibilla","Talassa","Talia","Teodora","Xenia",
]

SURNAMES = [
    "Altamar","Argiropoli","Barisano","Calarco","Cardamone","Coronati",
    "Damasceno","Egeo","Gauro","Lecati","Malacosta","Malamorte","Marmo",
    "Melas","Mirto","Moncada","Olimpiade","Oristano","Palaiologos","Pellegrino",
    "Salis","Samerio","Sandalio","Sartoris","Solano","Taranto","Tindari",
    "Torralba","Valeriano","Zaleuco",
]

# Work slot options
SLOT_OPTIONS = ['idle', 'field', 'workshop', 'training']


class Inhabitant(db.Model):
    __tablename__ = 'inhabitants'

    id          = db.Column(db.Integer, primary_key=True)
    village_id  = db.Column(db.Integer, db.ForeignKey('villages.id'), nullable=False)
    first_name  = db.Column(db.String(60), nullable=False)
    last_name   = db.Column(db.String(60), nullable=False)
    gender      = db.Column(db.String(1),  nullable=False)  # M | F
    age         = db.Column(db.Integer, default=18)
    birth_month = db.Column(db.Integer, default=0)  # 0-11
    level_type  = db.Column(db.String(1), default='J')  # J | M
    level_num   = db.Column(db.Integer, default=0)
    training_pts= db.Column(db.Integer, default=0)
    is_alive    = db.Column(db.Boolean, default=True)
    specialization  = db.Column(db.String(30))          # Guerriero / Maga / etc.
    stat_vit        = db.Column(db.Integer)
    stat_str        = db.Column(db.Integer)
    stat_mag        = db.Column(db.Integer)
    stat_dex        = db.Column(db.Integer)
    m_training_pts  = db.Column(db.Integer, default=0)

    # 4 work/train slots per turn (4h each)
    slot1 = db.Column(db.String(12), default='idle')
    slot2 = db.Column(db.String(12), default='idle')
    slot3 = db.Column(db.String(12), default='idle')
    slot4 = db.Column(db.String(12), default='idle')

    # ------------------------------------------------------------------
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def level_label(self):
        if self.level_type == 'GM':
            return 'GM'
        return f"{self.level_type}{self.level_num}"

    @property
    def can_use_slots(self):
        """Can be assigned to any slot (training or work) — age >= 14."""
        return self.age >= 14 and self.is_alive

    @property
    def can_work(self):
        """Can be assigned to production slots (Campo / Officina) — age >= 18."""
        return self.age >= 18 and self.is_alive

    @property
    def can_use_workshop(self):
        """J11+ or M/GM class can work in the workshop."""
        if self.level_type in ('M', 'GM'):
            return True
        return self.level_num >= 11

    @property
    def can_train(self):
        """J class (any age) and M1+ can use the 'Allena' slot to gain training_pts."""
        if not self.is_alive:
            return False
        if self.level_type == 'J':
            return True
        if self.level_type == 'M' and self.level_num >= 1:
            return True
        return False

    @property
    def food_cost(self):
        if self.level_type == 'M':
            return 3
        return 2

    @property
    def _level_threshold(self):
        """Totale EXP cumulativo necessario per essere al livello attuale."""
        return self.level_num * 28

    @property
    def _next_level_threshold(self):
        """Totale EXP cumulativo necessario per raggiungere il livello successivo."""
        return (self.level_num + 1) * 28

    @property
    def exp(self):
        """EXP 'libera': accumulata sul livello corrente, non quella già usata."""
        if self.level_type != 'J':
            return None
        return max(0, self.training_pts - self._level_threshold)

    @property
    def exp_needed(self):
        """EXP necessaria per completare il livello corrente (costo del passo)."""
        if self.level_type != 'J' or self.level_num >= 21:
            return None
        return self._next_level_threshold - self._level_threshold

    @property
    def slots(self):
        return [self.slot1, self.slot2, self.slot3, self.slot4]

    @property
    def food_slots(self):
        """Slot produttivi nel Campo (usati per calcolare il cibo prodotto)."""
        return sum(1 for s in self.slots if s == 'field')

    @property
    def tool_slots(self):
        """Slot produttivi in Officina (usati per calcolare gli attrezzi prodotti)."""
        return sum(1 for s in self.slots if s == 'workshop')

    @property
    def train_slots(self):
        return sum(1 for s in self.slots if s == 'training')

    @property
    def works_in_field(self):
        """True se l'abitante ha almeno 1 slot assegnato al Campo (occupa 1 posto)."""
        return any(s == 'field' for s in self.slots)

    @property
    def works_in_workshop(self):
        """True se l'abitante ha almeno 1 slot assegnato all'Officina (occupa 1 posto)."""
        return any(s == 'workshop' for s in self.slots)

    @property
    def can_use_training_ground(self):
        """M1+ o GM possono usare il Campo di Addestramento."""
        if self.level_type == 'GM':
            return True
        return self.level_type == 'M' and self.level_num >= 1

    @property
    def works_in_training_ground(self):
        return any(s == 'training_ground' for s in self.slots)

    @property
    def m_exp(self):
        """EXP libera sul livello M corrente (usa training_pts, azzerati alla transizione J→M)."""
        if self.level_type == 'M' and self.level_num >= 1:
            return max(0, (self.training_pts or 0) - m_cumulative_threshold(self.level_num))
        if self.level_type == 'GM':
            return None
        return None

    @property
    def m_exp_needed(self):
        """Costo del passo M corrente → successivo."""
        if self.level_type == 'M' and 1 <= self.level_num < 20:
            return m_level_step_cost(self.level_num)
        return None

    def set_slot(self, idx, value):
        """idx: 1-4"""
        if idx == 1: self.slot1 = value
        elif idx == 2: self.slot2 = value
        elif idx == 3: self.slot3 = value
        elif idx == 4: self.slot4 = value

    def __repr__(self):
        return f'<Inhabitant {self.full_name} {self.level_label}>'


# ---------------------------------------------------------------------------
# Turn log
# ---------------------------------------------------------------------------
class TurnLog(db.Model):
    __tablename__ = 'turn_logs'

    id             = db.Column(db.Integer, primary_key=True)
    village_id     = db.Column(db.Integer, db.ForeignKey('villages.id'), nullable=False)
    turn_number    = db.Column(db.Integer)
    month_name     = db.Column(db.String(50))
    year           = db.Column(db.Integer)
    food_produced  = db.Column(db.Integer, default=0)
    tools_produced = db.Column(db.Integer, default=0)
    food_consumed  = db.Column(db.Integer, default=0)
    food_balance   = db.Column(db.Integer, default=0)
    deaths         = db.Column(db.Integer, default=0)
    new_arrivals   = db.Column(db.Integer, default=0)
    level_ups      = db.Column(db.Integer, default=0)
    log_text       = db.Column(db.Text, default='')
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def date_string(self):
        return f"{self.month_name} anno {self.year} dF"
