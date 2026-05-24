from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import db, GameState, Inhabitant, SPECIALIZATIONS, generate_stats, stat_upgrade_cost

UPGRADABLE_STATS = {'vit', 'str', 'mag', 'dex'}

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


@training_ground_bp.route('/upgrade_stat/<int:inh_id>', methods=['POST'])
@login_required
def upgrade_stat(inh_id):
    """Spende m_training_pts per aumentare una statistica di 1 punto."""
    village = current_user.village
    inh     = Inhabitant.query.get_or_404(inh_id)

    if inh.village_id != village.id:
        flash('Abitante non del tuo villaggio.', 'danger')
        return redirect(url_for('training_ground.overview'))

    if not inh.is_alive:
        flash('Questo abitante non è più nel villaggio.', 'warning')
        return redirect(url_for('training_ground.overview'))

    if not inh.can_use_training_ground:
        flash(f'{inh.full_name} deve essere almeno M1 per potenziare le statistiche.', 'warning')
        return redirect(url_for('training_ground.overview'))

    stat = request.form.get('stat', '').strip().lower()
    if stat not in UPGRADABLE_STATS:
        flash('Statistica non valida.', 'danger')
        return redirect(url_for('training_ground.overview'))

    # Leggi il valore attuale della stat
    stat_attr  = f'stat_{stat}'
    cur_val    = getattr(inh, stat_attr) or 0
    cost       = stat_upgrade_cost(cur_val)
    avail_pts  = inh.m_training_pts or 0

    if avail_pts < cost:
        flash(
            f'Punti insufficienti per potenziare {stat.upper()} di {inh.full_name}. '
            f'Servono {cost} pt (disponibili: {avail_pts}).',
            'danger'
        )
        return redirect(url_for('training_ground.overview'))

    # Applica l'upgrade
    setattr(inh, stat_attr, cur_val + 1)
    inh.m_training_pts = avail_pts - cost
    db.session.commit()

    stat_labels = {'vit': 'VIT', 'str': 'STR', 'mag': 'MAG', 'dex': 'DEX'}
    flash(
        f'⬆️ {inh.full_name}: {stat_labels[stat]} {cur_val} → {cur_val + 1} '
        f'(costo: {cost} pt, rimanenti: {inh.m_training_pts})',
        'success'
    )
    return redirect(url_for('training_ground.overview'))
