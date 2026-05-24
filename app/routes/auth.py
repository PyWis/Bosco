from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app.models import db, User, KINGDOMS

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/')
def index():
    if current_user.is_authenticated:
        if not current_user.setup_complete:
            return redirect(url_for('auth.setup'))
        return redirect(url_for('village.overview'))
    return render_template('index.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('auth.index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            flash(f'Benvenuto, {user.username}!', 'success')
            nxt = request.args.get('next')
            return redirect(nxt or url_for('auth.index'))
        flash('Credenziali non valide.', 'danger')
    return render_template('auth/login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('auth.index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')

        if not username or not email or not password:
            flash('Compila tutti i campi.', 'warning')
        elif password != confirm:
            flash('Le password non coincidono.', 'warning')
        elif User.query.filter_by(username=username).first():
            flash('Nome utente già in uso.', 'danger')
        elif User.query.filter_by(email=email).first():
            flash('Email già registrata.', 'danger')
        else:
            user = User(username=username, email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash('Registrazione completata! Scegli il tuo regno.', 'success')
            return redirect(url_for('auth.setup'))
    return render_template('auth/register.html')


@auth_bp.route('/setup', methods=['GET', 'POST'])
@login_required
def setup():
    if current_user.setup_complete and not current_user.is_superadmin:
        return redirect(url_for('village.overview'))
    if request.method == 'POST':
        village_name = request.form.get('village_name', '').strip()
        kingdom      = request.form.get('kingdom', '')

        # Il nome del regno è l'alleanza scelta
        kingdom_name = kingdom

        if not village_name:
            flash('Inserisci il nome del villaggio.', 'warning')
        elif kingdom not in KINGDOMS:
            flash('Scegli un regno valido.', 'warning')
        else:
            current_user.kingdom        = kingdom
            current_user.setup_complete = True
            db.session.commit()

            # Create village only if player doesn't have one yet
            if not current_user.village:
                from app import _create_starting_village
                _create_starting_village(current_user, village_name, kingdom_name)
            else:
                current_user.village.name         = village_name
                current_user.village.kingdom_name = kingdom_name
                db.session.commit()

            flash('Il tuo villaggio è pronto! Buona fortuna, avventuriero.', 'success')
            return redirect(url_for('village.overview'))
    return render_template('auth/setup.html', kingdoms=KINGDOMS)


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Hai effettuato il logout.', 'info')
    return redirect(url_for('auth.index'))
