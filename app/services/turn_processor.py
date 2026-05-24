"""
Turn processor – chiamato ogni TURN_DURATION_MINUTES minuti.
Elabora tutti i villaggi in sequenza e avanza lo stato di gioco.
"""
import random
import logging
from datetime import datetime

from app.models import (
    db, GameState, Village, Building, Inhabitant, TurnLog,
    MONTHS, MALE_NAMES, FEMALE_NAMES, SURNAMES, upgrade_cost
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _random_inhabitant(village_id: int, age: int | None = None) -> Inhabitant:
    gender = random.choice(['M', 'F'])
    first  = random.choice(MALE_NAMES if gender == 'M' else FEMALE_NAMES)
    last   = random.choice(SURNAMES)
    if age is None:
        age = random.randint(14, 18)
    inh = Inhabitant(
        village_id  = village_id,
        first_name  = first,
        last_name   = last,
        gender      = gender,
        age         = age,
        birth_month = random.randint(0, 11),
        level_type  = 'J',
        level_num   = 0,
        training_pts= 0,
        is_alive    = True,
    )
    return inh


# ---------------------------------------------------------------------------
# Core village turn
# ---------------------------------------------------------------------------
def process_village_turn(village: Village, gs: GameState) -> TurnLog:
    lines     = []
    food_prod = 0
    tool_prod = 0
    food_cons = 0
    deaths    = 0
    arrivals  = 0
    level_ups = 0

    alive = village.alive_inhabitants

    # ------------------------------------------------------------------
    # 1. Complete pending building upgrades (requested last turn)
    # ------------------------------------------------------------------
    for bld in village.buildings:
        if bld.upgrade_pending and bld.upgrade_at_turn == gs.turn_number:
            bld.level         += 1
            bld.upgrade_pending = False
            bld.upgrade_at_turn = None
            lines.append(f"🔨 {bld.label} salita al livello {bld.level}!")

    # ------------------------------------------------------------------
    # 2. Production: fields & workshop
    # ------------------------------------------------------------------
    field_workers    = 0
    workshop_workers = 0

    for inh in alive:
        if not inh.can_work:
            continue
        for slot in inh.slots:
            if slot == 'field':
                food_prod    += 1
                field_workers += 1
            elif slot == 'workshop':
                if inh.can_use_workshop:
                    tool_prod        += 1
                    workshop_workers += 1

    village.food  += food_prod
    village.tools += tool_prod

    if food_prod > 0:
        lines.append(f"🌾 Prodotti {food_prod} cibi dai Campi.")
    if tool_prod > 0:
        lines.append(f"⚒️  Prodotti {tool_prod} attrezzi dall'Officina.")

    # ------------------------------------------------------------------
    # 3. Training & level-ups
    # ------------------------------------------------------------------
    for inh in alive:
        if not inh.can_work or not inh.can_train:
            continue
        train_count = inh.train_slots
        if train_count == 0:
            continue

        pts_this_turn = 0
        for slot_idx in range(1, 5):
            slot_val = inh.slots[slot_idx - 1]
            if slot_val == 'training':
                max_pts = 70 if slot_idx == 4 else 100
                pts_this_turn += random.randint(1, max_pts)

        inh.training_pts += pts_this_turn

        # Level up (max 1 per turn)
        if inh.level_type == 'J' and inh.level_num < 21:
            needed = (inh.level_num + 1) * 28
            if inh.training_pts >= needed:
                inh.level_num    += 1
                level_ups        += 1
                lines.append(
                    f"⭐ {inh.full_name} ha raggiunto il livello J{inh.level_num}!"
                )
                # Transition J21 → M0
                if inh.level_num == 21:
                    inh.level_type = 'M'
                    inh.level_num  = 0
                    lines.append(
                        f"👴 {inh.full_name} ha raggiunto la maturità (M0): +1 cibo consumato."
                    )

    # ------------------------------------------------------------------
    # 4. Aging – inhabitants born this month age by 1
    # ------------------------------------------------------------------
    for inh in alive:
        if inh.birth_month == gs.current_month:
            inh.age += 1
            if inh.age == 18:
                lines.append(f"🎂 {inh.full_name} ha compiuto 18 anni: può lavorare!")

    # ------------------------------------------------------------------
    # 5. Food consumption
    # ------------------------------------------------------------------
    for inh in alive:
        food_cons += inh.food_cost

    village.food -= food_cons
    food_balance  = food_prod - food_cons
    lines.append(
        f"🍞 Consumati {food_cons} cibi (bilancio: "
        f"{'+'if food_balance>=0 else ''}{food_balance})."
    )

    # ------------------------------------------------------------------
    # 6. Starvation
    # ------------------------------------------------------------------
    if village.food < 0:
        score   = abs(village.food)
        to_kill = max(1, int((score - 5) / 5)) if score > 5 else 0
        if to_kill > 0:
            candidates = [i for i in alive]
            random.shuffle(candidates)
            for inh in candidates[:to_kill]:
                inh.is_alive = False
                deaths += 1
                lines.append(f"💀 {inh.full_name} è morto per fame.")

    # ------------------------------------------------------------------
    # 7. New arrival
    # ------------------------------------------------------------------
    alive_after = village.alive_inhabitants  # re-eval after deaths
    if len(alive_after) < village.max_inhabitants:
        new_inh = _random_inhabitant(village.id)
        db.session.add(new_inh)
        arrivals += 1
        status = "non può ancora lavorare" if new_inh.age < 18 else "pronto a lavorare"
        lines.append(
            f"👶 {new_inh.full_name} ({new_inh.age} anni) si è unito al villaggio "
            f"({status})."
        )

    # ------------------------------------------------------------------
    # 8. Write log
    # ------------------------------------------------------------------
    entry = TurnLog(
        village_id    = village.id,
        turn_number   = gs.turn_number,
        month_name    = gs.month_name,
        year          = gs.current_year,
        food_produced = food_prod,
        tools_produced= tool_prod,
        food_consumed = food_cons,
        food_balance  = food_balance,
        deaths        = deaths,
        new_arrivals  = arrivals,
        level_ups     = level_ups,
        log_text      = '\n'.join(lines),
    )
    db.session.add(entry)
    return entry


# ---------------------------------------------------------------------------
# Master turn runner
# ---------------------------------------------------------------------------
def run_turn(app):
    """Called by APScheduler. Processes one game turn."""
    with app.app_context():
        try:
            gs = GameState.query.first()
            if not gs:
                log.warning("GameState non trovato, salto turno.")
                return

            log.info(f"--- TURNO {gs.turn_number} | {gs.date_string} ---")

            for village in Village.query.all():
                process_village_turn(village, gs)

            gs.advance()
            db.session.commit()
            log.info(f"Turno completato. Ora: {gs.date_string}")

        except Exception as e:
            db.session.rollback()
            log.exception(f"Errore durante il turno: {e}")
