from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import db, GameState, Inhabitant

inhabitants_bp = Blueprint('inhabitants', __name__, url_prefix='/inhabitants')

VALID_SLOTS = {'idle', 'field', 'workshop', 'training'}


@inhabitants_bp.route('/')
@login_required
def overview():
    if not current_user.setup_complete:
        return redirect(url_for('auth.setup'))
    gs      = GameState.query.first()
    village = current_user.village
    alive   = village.alive_inhabitants
    return render_template('game/inhabitants.html',
                           village=village, gs=gs, inhabitants=alive)


@inhabitants_bp.route('/assign/<int:inh_id>', methods=['POST'])
@login_required
def assign(inh_id):
    village = current_user.village
    inh     = Inhabitant.query.get_or_404(inh_id)

    if inh.village_id != village.id:
        flash('Abitante non appartenente al tuo villaggio.', 'danger')
        return redirect(url_for('inhabitants.overview'))

    if not inh.can_work:
        flash(f'{inh.full_name} non può ancora lavorare (età < 18).', 'warning')
        return redirect(url_for('inhabitants.overview'))

    slots_data = []
    for idx in range(1, 5):
        val = request.form.get(f'slot{idx}', 'idle').strip()
        if val not in VALID_SLOTS:
            val = 'idle'
        slots_data.append(val)

    # Validate: workshop only for J11+ / M class
    for i, val in enumerate(slots_data):
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

    # Check field capacity
    field_slots_this = sum(1 for v in slots_data if v == 'field')
    workshop_slots_this = sum(1 for v in slots_data if v == 'workshop')

    # Count other inhabitants' slots (excluding this one)
    other_alive = [i for i in village.alive_inhabitants
                   if i.id != inh_id and i.can_work]
    total_field    = sum(i.food_slots    for i in other_alive) + field_slots_this
    total_workshop = sum(i.tool_slots    for i in other_alive) + workshop_slots_this

    if total_field > village.max_field_workers:
        flash(
            f'Capacità Campi superata ({village.max_field_workers} slot disponibili).',
            'danger'
        )
        return redirect(url_for('inhabitants.overview'))
    if total_workshop > village.max_workshop_workers:
        flash(
            f'Capacità Officina superata ({village.max_workshop_workers} slot disponibili).',
            'danger'
        )
        return redirect(url_for('inhabitants.overview'))

    inh.slot1, inh.slot2, inh.slot3, inh.slot4 = slots_data
    db.session.commit()
    flash(f'Turno lavorativo di {inh.full_name} aggiornato.', 'success')
    return redirect(url_for('inhabitants.overview'))


@inhabitants_bp.route('/assign_all', methods=['POST'])
@login_required
def assign_all():
    """Bulk assignment: set all slots for every inhabitant at once."""
    village = current_user.village
    alive   = village.alive_inhabitants

    for inh in alive:
        if not inh.can_work:
            continue
        for idx in range(1, 5):
            key = f'inh_{inh.id}_slot{idx}'
            val = request.form.get(key, 'idle').strip()
            if val not in VALID_SLOTS:
                val = 'idle'
            # Basic validation
            if val == 'workshop' and not inh.can_use_workshop:
                val = 'idle'
            if val == 'training' and not inh.can_train:
                val = 'idle'
            inh.set_slot(idx, val)

    db.session.commit()
    flash('Assegnazioni aggiornate per tutti gli abitanti.', 'success')
    return redirect(url_for('inhabitants.overview'))
