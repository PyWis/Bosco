from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import db, GameState, Inhabitant

inhabitants_bp = Blueprint('inhabitants', __name__, url_prefix='/inhabitants')

VALID_SLOTS = {'idle', 'field', 'workshop', 'training', 'training_ground'}


SORT_KEYS = {'age', 'level'}
ORDER_KEYS = {'asc', 'desc'}


def _level_sort_key(inh):
    """Ordine: J < M; poi numero livello; poi tipo (J=0, M=1)."""
    type_order = 0 if inh.level_type == 'J' else 1
    return (type_order, inh.level_num)


@inhabitants_bp.route('/')
@login_required
def overview():
    if not current_user.setup_complete:
        return redirect(url_for('auth.setup'))

    gs      = GameState.query.first()
    village = current_user.village
    alive   = village.alive_inhabitants

    sort  = request.args.get('sort',  'age')
    order = request.args.get('order', 'asc')
    if sort  not in SORT_KEYS:  sort  = 'age'
    if order not in ORDER_KEYS: order = 'asc'

    reverse = (order == 'desc')
    if sort == 'age':
        alive = sorted(alive, key=lambda i: i.age, reverse=reverse)
    elif sort == 'level':
        alive = sorted(alive, key=_level_sort_key, reverse=reverse)

    return render_template('game/inhabitants.html',
                           village=village, gs=gs, inhabitants=alive,
                           sort=sort, order=order)


@inhabitants_bp.route('/assign/<int:inh_id>', methods=['POST'])
@login_required
def assign(inh_id):
    village = current_user.village
    inh     = Inhabitant.query.get_or_404(inh_id)

    if inh.village_id != village.id:
        flash('Abitante non appartenente al tuo villaggio.', 'danger')
        return redirect(url_for('inhabitants.overview'))

    if not inh.can_use_slots:
        flash(f'{inh.full_name} è troppo giovane (età < 14).', 'warning')
        return redirect(url_for('inhabitants.overview'))

    slots_data = []
    for idx in range(1, 5):
        val = request.form.get(f'slot{idx}', 'idle').strip()
        if val not in VALID_SLOTS:
            val = 'idle'
        slots_data.append(val)

    # Validazioni per slot
    for val in slots_data:
        if val in ('field', 'workshop') and not inh.can_work:
            flash(
                f'{inh.full_name} ha meno di 18 anni: può solo allenarsi, non lavorare.',
                'warning'
            )
            return redirect(url_for('inhabitants.overview'))
        if val == 'workshop' and not inh.can_use_workshop:
            flash(
                f'{inh.full_name} deve essere almeno J11 per lavorare in Officina.',
                'warning'
            )
            return redirect(url_for('inhabitants.overview'))
        if val == 'training' and not inh.can_train:
            flash(
                f'{inh.full_name} (livello {inh.level_label}) non può più allenarsi.',
                'warning'
            )
            return redirect(url_for('inhabitants.overview'))
        if val == 'training_ground' and not inh.can_use_training_ground:
            flash(
                f'{inh.full_name} deve essere almeno M1 per usare il Campo di Addestramento.',
                'warning'
            )
            return redirect(url_for('inhabitants.overview'))

    # Controllo capacità Campo / Officina: 1 abitante = 1 posto,
    # indipendentemente da quante ore lavora lì.
    this_in_field    = any(v == 'field'    for v in slots_data)
    this_in_workshop = any(v == 'workshop' for v in slots_data)

    other_alive    = [i for i in village.alive_inhabitants if i.id != inh_id]
    total_field    = sum(1 for i in other_alive if i.works_in_field)    + (1 if this_in_field    else 0)
    total_workshop = sum(1 for i in other_alive if i.works_in_workshop) + (1 if this_in_workshop else 0)

    if total_field > village.max_field_workers:
        flash(
            f'Capacità Campi superata ({village.max_field_workers} posti disponibili).',
            'danger'
        )
        return redirect(url_for('inhabitants.overview'))
    if total_workshop > village.max_workshop_workers:
        flash(
            f'Capacità Officina superata ({village.max_workshop_workers} posti disponibili).',
            'danger'
        )
        return redirect(url_for('inhabitants.overview'))

    inh.slot1, inh.slot2, inh.slot3, inh.slot4 = slots_data
    db.session.commit()
    flash(f'Turno di {inh.full_name} aggiornato.', 'success')
    return redirect(url_for('inhabitants.overview'))


@inhabitants_bp.route('/expel/<int:inh_id>', methods=['POST'])
@login_required
def expel(inh_id):
    """Espelle un abitante dal villaggio. Costa 3 turni del suo fabbisogno di cibo."""
    village = current_user.village
    inh     = Inhabitant.query.get_or_404(inh_id)

    if inh.village_id != village.id:
        flash('Abitante non appartenente al tuo villaggio.', 'danger')
        return redirect(url_for('inhabitants.overview'))

    if not inh.is_alive:
        flash('Questo abitante non è più nel villaggio.', 'warning')
        return redirect(url_for('inhabitants.overview'))

    cost = inh.food_cost * 3
    if village.food < cost:
        flash(
            f'Cibo insufficiente per espellere {inh.full_name}. '
            f'Servono {cost} cibi (3 turni × {inh.food_cost}), ne hai {village.food}.',
            'danger'
        )
        return redirect(url_for('inhabitants.overview'))

    village.food -= cost
    inh.is_alive  = False
    inh.slot1 = inh.slot2 = inh.slot3 = inh.slot4 = 'idle'
    db.session.commit()

    flash(
        f'{inh.full_name} è stato espulso dal villaggio '
        f'(costo: {cost} cibi).',
        'warning'
    )
    return redirect(url_for('inhabitants.overview'))


@inhabitants_bp.route('/assign_all', methods=['POST'])
@login_required
def assign_all():
    """Bulk assignment per tutti gli abitanti."""
    village = current_user.village
    alive   = village.alive_inhabitants

    # --- Prima passata: costruisci le assegnazioni proposte in memoria ---
    proposed = {}   # inh.id -> [slot1, slot2, slot3, slot4]

    for inh in alive:
        if not inh.can_use_slots:
            continue
        slots = []
        for idx in range(1, 5):
            key = f'inh_{inh.id}_slot{idx}'
            val = request.form.get(key, 'idle').strip()
            if val not in VALID_SLOTS:
                val = 'idle'
            # Sanity checks lato server
            if val in ('field', 'workshop') and not inh.can_work:
                val = 'idle'
            if val == 'workshop' and not inh.can_use_workshop:
                val = 'idle'
            if val == 'training' and not inh.can_train:
                val = 'idle'
            if val == 'training_ground' and not inh.can_use_training_ground:
                val = 'idle'
            slots.append(val)
        proposed[inh.id] = slots

    # --- Controllo capacità: 1 abitante = 1 posto (indipendente dalle ore) ---
    in_field           = sum(1 for slots in proposed.values() if 'field'            in slots)
    in_workshop        = sum(1 for slots in proposed.values() if 'workshop'         in slots)
    in_training_ground = sum(1 for slots in proposed.values() if 'training_ground'  in slots)

    errors = []
    if in_field > village.max_field_workers:
        errors.append(
            f'Campi: {in_field} abitanti assegnati ma la capacità è '
            f'{village.max_field_workers} (Campi lv{village.field.level}).'
        )
    if in_workshop > village.max_workshop_workers:
        errors.append(
            f'Officina: {in_workshop} abitanti assegnati ma la capacità è '
            f'{village.max_workshop_workers} (Officina lv{village.workshop.level}).'
        )
    if in_training_ground > village.max_training_ground_spots:
        tg = village.training_ground
        errors.append(
            f'Campo di Addestramento: {in_training_ground} abitanti assegnati ma la capacità è '
            f'{village.max_training_ground_spots} '
            f'(Campo lv{tg.level if tg else 0}).'
        )

    if errors:
        for msg in errors:
            flash(f'⚠️ {msg}', 'danger')
        flash('Registro non salvato. Riduci gli assegnati e riprova.', 'warning')
        return redirect(url_for('inhabitants.overview'))

    # --- Seconda passata: applica solo se tutto è valido ---
    for inh in alive:
        if inh.id not in proposed:
            continue
        inh.slot1, inh.slot2, inh.slot3, inh.slot4 = proposed[inh.id]

    db.session.commit()
    flash('Registro abitanti salvato.', 'success')
    return redirect(url_for('inhabitants.overview'))
