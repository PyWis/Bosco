from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import db, GameState, Building, BUILDING_MAX_LEVEL, upgrade_cost

village_bp = Blueprint('village', __name__, url_prefix='/village')


@village_bp.route('/')
@login_required
def overview():
    if not current_user.setup_complete:
        return redirect(url_for('auth.setup'))
    gs      = GameState.query.first()
    village = current_user.village
    if village is None:
        # SuperAdmin or user without a village yet
        if current_user.is_superadmin:
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('auth.setup'))
    logs = village.turn_logs[:5]
    return render_template('game/village.html', village=village, gs=gs, logs=logs)


@village_bp.route('/upgrade/<int:building_id>', methods=['POST'])
@login_required
def upgrade(building_id):
    village = current_user.village
    bld     = Building.query.get_or_404(building_id)

    if bld.village_id != village.id:
        flash('Edificio non appartenente al tuo villaggio.', 'danger')
        return redirect(url_for('village.overview'))

    if bld.at_max_level:
        flash(f'{bld.label} è già al livello massimo.', 'warning')
        return redirect(url_for('village.overview'))

    if bld.upgrade_pending:
        flash(f'{bld.label} ha già un aggiornamento in corso.', 'warning')
        return redirect(url_for('village.overview'))

    # Check only one upgrade at a time per village
    pending_any = any(b.upgrade_pending for b in village.buildings)
    if pending_any:
        flash('Puoi avere solo un aggiornamento alla volta.', 'warning')
        return redirect(url_for('village.overview'))

    cost = upgrade_cost(bld.level)
    if village.tools < cost:
        flash(f'Attrezzi insufficienti. Servono {cost}, hai {village.tools}.', 'danger')
        return redirect(url_for('village.overview'))

    gs = GameState.query.first()
    village.tools      -= cost
    bld.upgrade_pending = True
    bld.upgrade_at_turn = gs.turn_number + 1  # completes next turn
    db.session.commit()

    flash(
        f'Aggiornamento di {bld.label} avviato! '
        f'Sarà completato nel prossimo turno ({gs.month_name}).', 'success'
    )
    return redirect(url_for('village.overview'))
