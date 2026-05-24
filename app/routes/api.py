"""Lightweight JSON API used by frontend JS for polling."""
from flask import Blueprint, jsonify
from flask_login import login_required, current_user
from app.models import GameState

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/gamestate')
@login_required
def gamestate():
    gs = GameState.query.first()
    if not gs:
        return jsonify(error='No game state'), 404
    from config import Config
    import datetime
    minutes  = Config.TURN_DURATION_MINUTES
    elapsed  = (datetime.datetime.utcnow() - gs.last_turn_time).total_seconds()
    remaining = max(0, minutes * 60 - elapsed)
    return jsonify(
        turn        = gs.turn_number,
        month       = gs.month_name,
        year        = gs.current_year,
        date_string = gs.date_string,
        remaining_seconds = int(remaining),
    )


@api_bp.route('/village')
@login_required
def village_summary():
    v = current_user.village
    if not v:
        return jsonify(error='No village'), 404
    return jsonify(
        food  = v.food,
        tools = v.tools,
        total_inhabitants = v.total_inhabitants,
        max_inhabitants   = v.max_inhabitants,
    )
