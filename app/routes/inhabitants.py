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


@inhabitants_bp.route('/assign_all', methods=['POST'])
@login_required
def assign_all():
    """Bulk assignment per tutti gli abitanti."""
    village = current_user.village
    alive   = village.alive_inhabitants

    for inh in alive:
        if not inh.can_use_slots:
            continue
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
            inh.set_slot(idx, val)

    db.session.commit()
    flash('Assegnazioni aggiornate per tutti gli abitanti.', 'success')
    return redirect(url_for('inhabitants.overview'))
