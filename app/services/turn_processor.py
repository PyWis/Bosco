"""
Turn processor – chiamato ogni TURN_DURATION_MINUTES minuti.
Elabora tutti i villaggi in sequenza e avanza lo stato di gioco.
"""
import random
import logging
from datetime import datetime

from app.models import (
    db, GameState, Village, Building, Inhabitant, TurnLog,
    MONTHS, MALE_NAMES, FEMALE_NAMES, SURNAMES,
    m_level_step_cost, m_cumulative_threshold,
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
        # Normalmente servono 18 anni; eccezione: U18 assegnati al Campo Addes.
        if not inh.can_work and not inh.works_in_training_ground:
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
    # 3a. Training – slot 'training' (J e M1+)
    #     Produce training_pts → avanza il livello J (J→M0 a J21)
    #     oppure il livello M (usando training_pts, azzerati alla transizione).
    #     Gli U18 in Campo Addes. possono allenarsi normalmente.
    # ------------------------------------------------------------------
    for inh in alive:
        if not inh.can_train:   # esclude M0, GM e morti
            continue
        if inh.train_slots == 0:
            continue

        pts_this_turn = 0
        for slot_idx in range(1, 5):
            if inh.slots[slot_idx - 1] == 'training':
                max_pts = 70 if slot_idx == 4 else 100
                pts_this_turn += random.randint(1, max_pts)

        inh.training_pts += pts_this_turn

        if inh.level_type == 'J' and inh.level_num < 21:
            # Level up J (max 1 per turn)
            needed = (inh.level_num + 1) * 28
            if inh.training_pts >= needed:
                inh.level_num += 1
                level_ups     += 1
                lines.append(f"⭐ {inh.full_name} ha raggiunto J{inh.level_num}!")
                # Transizione J21 → M0: azzera training_pts per il nuovo contatore M
                if inh.level_num == 21:
                    inh.level_type   = 'M'
                    inh.level_num    = 0
                    inh.training_pts = 0
                    lines.append(
                        f"👴 {inh.full_name} ha raggiunto la maturità (M0): "
                        f"scegli la specializzazione nel Campo di Addestramento."
                    )

        elif inh.level_type == 'M' and 1 <= inh.level_num < 20:
            # Level up M tramite 'Allena' (usa training_pts)
            threshold = m_cumulative_threshold(inh.level_num + 1)
            if inh.training_pts >= threshold:
                inh.level_num += 1
                level_ups     += 1
                lines.append(
                    f"🌟 {inh.full_name} ({inh.specialization}) ha raggiunto M{inh.level_num} con l'allenamento!"
                )

        elif inh.level_type == 'M' and inh.level_num == 20:
            # M20 → GM tramite 'Allena'
            threshold = m_cumulative_threshold(21)  # oltre la soglia M20
            if inh.training_pts >= threshold:
                inh.level_type = 'GM'
                inh.level_num  = 0
                level_ups      += 1
                lines.append(
                    f"👑 {inh.full_name} ha raggiunto il rango di Gran Maestro (GM)!"
                )

    # ------------------------------------------------------------------
    # 3b. Campo di Addestramento – slot 'training_ground' (M1+, GM)
    #     Accumula m_training_pts (contatore separato, NON per livellare).
    # ------------------------------------------------------------------
    for inh in alive:
        if not inh.can_use_training_ground:
            continue
        tg_slots = sum(1 for s in inh.slots if s == 'training_ground')
        if tg_slots == 0:
            continue

        inh.m_training_pts = (inh.m_training_pts or 0) + tg_slots
        lines.append(
            f"⚔️  {inh.full_name} ha guadagnato {tg_slots} pt addestramento Campo "
            f"(tot: {inh.m_training_pts})."
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
    #    -1 .. -5  → 1 morto casuale
    #    ≤ -6      → 2 morti casuali
    #    Dopo le uccisioni il cibo viene riportato a 0.
    # ------------------------------------------------------------------
    if village.food < 0:
        to_kill = 2 if village.food <= -6 else 1
        candidates = [i for i in alive if i.is_alive]
        random.shuffle(candidates)
        for inh in candidates[:to_kill]:
            inh.is_alive = False
            deaths += 1
            lines.append(f"💀 {inh.full_name} è morto per fame.")
        village.food = 0
        lines.append("🌾 Le riserve di cibo sono state azzerate dopo la carestia.")

    # ------------------------------------------------------------------
    # 7. New arrival (saltato se il villaggio ha bloccato gli arrivi)
    # ------------------------------------------------------------------
    alive_after = village.alive_inhabitants  # re-eval after deaths
    if village.block_arrivals:
        lines.append("🚫 Arrivi bloccati: nessun nuovo abitante questo turno.")
    elif len(alive_after) < village.max_inhabitants:
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
