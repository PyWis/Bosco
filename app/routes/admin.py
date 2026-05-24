from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import db, User, Village, GameState, KINGDOMS
from functools import wraps

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def superadmin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_superadmin:
            flash('Accesso riservato al SuperAdmin.', 'danger')
            return redirect(url_for('village.overview'))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route('/')
@superadmin_required
def dashboard():
    from flask import current_app
    users    = User.query.order_by(User.created_at).all()
    gs       = GameState.query.first()
    return render_template('admin/dashboard.html', users=users, gs=gs,
                           config=current_app.config)


@admin_bp.route('/users')
@superadmin_required
def users():
    all_users = User.query.order_by(User.created_at).all()
    gs        = GameState.query.first()
    return render_template('admin/users.html', users=all_users, gs=gs)


@admin_bp.route('/users/<int:user_id>/kingdom', methods=['POST'])
@superadmin_required
def change_kingdom(user_id):
    user    = User.query.get_or_404(user_id)
    kingdom = request.form.get('kingdom', '')
    if kingdom not in KINGDOMS:
        flash('Regno non valido.', 'danger')
    else:
        user.kingdom = kingdom
        db.session.commit()
        flash(f'Regno di {user.username} aggiornato a {kingdom}.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@superadmin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_superadmin:
        flash('Non puoi eliminare il SuperAdmin.', 'danger')
        return redirect(url_for('admin.users'))
    db.session.delete(user)
    db.session.commit()
    flash(f'Utente {user.username} eliminato.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/advance_turn', methods=['POST'])
@superadmin_required
def advance_turn():
    """Avanza manualmente il gioco di 1 turno."""
    from app.services.turn_processor import process_village_turn
    gs = GameState.query.first()
    if not gs:
        flash('Stato di gioco non trovato.', 'danger')
        return redirect(url_for('admin.dashboard'))

    villages = Village.query.all()
    processed = 0
    for village in villages:
        process_village_turn(village, gs)
        processed += 1

    gs.advance()
    db.session.commit()

    flash(
        f'Turno avanzato manualmente! Ora siamo a: {gs.date_string} '
        f'(turno {gs.turn_number}) — {processed} villaggi elaborati.',
        'success'
    )
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/users/<int:user_id>/toggle_admin', methods=['POST'])
@superadmin_required
def toggle_admin(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_superadmin and user.id == current_user.id:
        flash('Non puoi rimuovere i tuoi privilegi.', 'danger')
    else:
        user.is_superadmin = not user.is_superadmin
        db.session.commit()
        status = 'promosso' if user.is_superadmin else 'retrocesso'
        flash(f'{user.username} {status}.', 'success')
    return redirect(url_for('admin.users'))
