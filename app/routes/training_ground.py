from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import db, GameState, Inhabitant, SPECIALIZATIONS, generate_stats

training_ground_bp = Blueprint('training_ground', __name__, url_prefix='/training_ground')


@training_ground_bp.route('/')
@login_required
def overview():
    if not current_user.setup_complete:
        return redirect(url_for('auth.setup'))
    gs      = GameState.query.first()
    village = current_user.village
    tg      = village.training_ground

    alive = village.alive_inhabitants
    m_inhabitants = [i for i in alive if i.level_type in ('M', 'GM')]

    return render_template(
        'game/training_ground.html',
        village=village, gs=gs, tg=tg,
        m_inhabitants=m_inhabitants,
        specializations=SPECIALIZATIONS,
    )


@training_ground_bp.route('/specialize/<int:inh_id>', methods=['POST'])
@login_required
def specialize(inh_id):
    village = current_user.village
    inh     = Inhabitant.query.get_or_404(inh_id)

    if inh.village_id != village.id:
        flash('Abitante non del tuo villaggio.', 'danger')
        return redirect(url_for('training_ground.overview'))

    if not inh.is_alive:
        flash('Questo abitante non è più nel villaggio.', 'warning')
        return redirect(url_for('training_ground.overview'))

    if inh.level_type != 'M' or inh.level_num != 0:
        flash(f'{inh.full_name} non è M0 e non può specializzarsi.', 'warning')
        return redirect(url_for('training_ground.overview'))

    valid = SPECIALIZATIONS.get(inh.gender, [])
    spec  = request.form.get('specialization', '').strip()
    if spec not in valid:
        flash(f'Specializzazione non valida per {inh.full_name}.', 'danger')
        return redirect(url_for('training_ground.overview'))

    # Genera statistiche con vincoli d'età
    vit, str_, mag, dex = generate_stats(inh.age)

    inh.specialization = spec
    inh.stat_vit       = vit
    inh.stat_str       = str_
    inh.stat_mag       = mag
    inh.stat_dex       = dex
    inh.level_num      = 1          # M0 → M1 automaticamente
    inh.m_training_pts = 0
    db.session.commit()

    flash(
        f'{inh.full_name} è diventato {spec} (M1)! '
        f'VIT {vit} · STR {str_} · MAG {mag} · DEX {dex} '
        f'(tot. {vit+str_+mag+dex})',
        'success'
    )
    return redirect(url_for('training_ground.overview'))
