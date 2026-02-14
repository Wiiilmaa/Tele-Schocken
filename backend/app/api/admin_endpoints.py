from app.api import bp
from app import db

from flask_socketio import emit

from flask import jsonify
from flask import request
from app.models import User, Game, Status
from random import seed, randrange
from jinja2 import utils

from app.api.errors import bad_request
from app.rulesets import get_all_rulesets, get_ruleset
from app.scoring import calculate_scoring


def _is_admin(game, user_id):
    """Check if a user is an admin for this game."""
    for u in game.users:
        if u.id == user_id and u.is_admin:
            return True
    return False


def _reset_user_dice(user):
    """Reset a user's dice and visibility for a new round. Uses None instead of 0."""
    user.dice1 = None
    user.dice2 = None
    user.dice3 = None
    user.number_dice = 0
    user.dice1_visible = False
    user.dice2_visible = False
    user.dice3_visible = False


def _handle_round_end(game, loser):
    """
    Handle the half/final/gamefinisch logic after chips are distributed.
    Called when the loser (userB) has received chips.
    Sets game status, resets users, returns message string.
    """
    message = 'OK'

    if loser.chips == game.stack_max:
        # Someone loses a half - increase chance of fallen dice
        game.changs_of_fallling_dice = game.changs_of_fallling_dice + 0.0002

        if game.play_final:
            if game.status == Status.PLAYFINAL:
                message = 'Spieler {} hat das Finale verloren'.format(loser.name)
                game.message = message
                game.status = Status.GAMEFINISCH
                loser.finalcount = loser.finalcount + 1
                game.halfcount = 0
                game.stack = game.stack_max
            else:
                # Second half to the same user -> game finish
                if loser.halfcount == 1:
                    game.stack = game.stack_max
                    loser.finalcount = loser.finalcount + 1
                    game.finalcount = game.finalcount + 1
                    game.status = Status.GAMEFINISCH
                    game.halfcount = 0
                    for user in game.active_users:
                        user.passive = False
                        user.chips = 0
                        user.halfcount = 0
                    message = 'Spieler {} hat das Finale verloren'.format(loser.name)
                    game.message = message
                # First half, round finish
                elif loser.halfcount == 0:
                    game.stack = game.stack_max
                    game.halfcount = game.halfcount + 1
                    loser.halfcount = loser.halfcount + 1
                    if game.halfcount == 2:
                        game.status = Status.PLAYFINAL
                        game.halfcount = 0
                        for user in game.active_users:
                            user.passive = False
                            user.chips = 0
                        message = 'Finale wird gespielt'
                        game.message = 'Finale wird gespielt grau hinterlegte Spieler muessen warten'
                    else:
                        game.status = Status.ROUNDFINISCH
                        message = 'Spieler {} verliert eine Haelfte'.format(loser.name)
                else:
                    message = 'Fehler'
        # No final, only count halfs
        else:
            loser.halfcount = loser.halfcount + 1
            game.status = Status.ROUNDFINISCH
            game.stack = game.stack_max
            game.halfcount = game.halfcount + 1
            message = 'Spieler {} verliert eine Haelfte'.format(loser.name)

    # Reset all active users for next round
    for user in game.active_users:
        if game.status == Status.ROUNDFINISCH:
            user.chips = 0
            user.passive = False
        if game.status == Status.GAMEFINISCH:
            user.chips = 0
            user.passive = False
            user.halfcount = 0
        if game.status == Status.PLAYFINAL:
            if user.halfcount == 0:
                user.passive = True
        _reset_user_dice(user)

    return message


def execute_deferred_actions(game):
    """
    Called when game reaches GAMEFINISCH.
    Removes leaving players, activates pending players,
    sets first_user to loser, handles lobby transition or auto-restart.
    """
    loser_id = game.first_user_id

    # 1. Remove players marked for leaving
    leaving_users = [u for u in game.users if u.leave_after_game]
    for user in leaving_users:
        if user.id == loser_id:
            # Find next in seat order who stays
            all_users = list(game.users)
            loser_index = next((i for i, u in enumerate(all_users) if u.id == loser_id), 0)
            for offset in range(1, len(all_users)):
                candidate = all_users[(loser_index + offset) % len(all_users)]
                if not candidate.leave_after_game and not candidate.pending_join:
                    loser_id = candidate.id
                    break
        db.session.delete(user)

    # 2. Activate pending players
    for user in game.users:
        if user.pending_join:
            user.pending_join = False
            user.chips = 0
            _reset_user_dice(user)

    # 3. Set first_user for next game to loser
    game.first_user_id = loser_id
    game.move_user_id = loser_id
    game.reveal_votes = ''

    # 4. If lobby_after_game: transition to WAITING
    if game.lobby_after_game:
        game.status = Status.WAITING
        game.lobby_after_game = False
        for user in game.users:
            user.chips = 0
            _reset_user_dice(user)
            user.passive = False
            user.leave_after_game = False
        game.stack = game.stack_max
        game.player_changes_allowed = True
        game.message = "Zurueck in der Lobby"
    else:
        # Auto-start next round
        game.status = Status.STARTED
        for user in game.active_users:
            user.chips = 0
            _reset_user_dice(user)
            user.passive = False
            user.leave_after_game = False
        game.stack = game.stack_max
        game.player_changes_allowed = True
        # Keep the message from the round end (shows who lost)


# Get all available rulesets
@bp.route('/rulesets', methods=['GET'])
def list_rulesets():
    """Return all available rulesets for the lobby dropdown."""
    rulesets = get_all_rulesets()
    return jsonify(rulesets), 200


# Create new Game
@bp.route('/game', methods=['POST'])
def create_Game():
    """Create a new Game the creator is the Admin"""
    seed(1)
    data = request.get_json() or {}
    response = jsonify()
    if 'name' not in data:
        return bad_request('must include name field')
    else:
        escapedusername = str(utils.escape(data['name']))
        game = Game()
        inuse = User.query.filter_by(name=escapedusername).first()
        if inuse is not None:
            response = jsonify(Message='Benutzername wird bereits verwendet!')
            response.status_code = 400
            return response
        user = User()
        user.name = escapedusername
        user.is_admin = True  # Creator is first admin
        game.users.append(user)
        db.session.add(game)
        db.session.commit()
        # Keep admin_user_id for backwards compatibility during migration
        game.admin_user_id = user.id
        db.session.add(game)
        db.session.commit()
        response = jsonify(Link='tele-schocken.de/{}'.format(game.UUID), UUID=game.UUID, Admin_Id=user.id)
        response.status_code = 201
    return response


# Start the Game
@bp.route('/game/<gid>/start', methods=['POST'])
def start_game(gid):
    """The Admin can use this route to start the game with a selected ruleset."""
    data = request.get_json() or {}
    game = Game.query.filter_by(UUID=gid).first()
    if game is None:
        return jsonify(Message='Spiel nicht gefunden'), 404

    # B2: Admin check
    requester_id = data.get('admin_id')
    if requester_id and not _is_admin(game, int(requester_id)):
        return jsonify(Message='Nur Admins duerfen das Spiel starten'), 403

    # Support both new ruleset-based and legacy stack_max/play_final start
    if 'ruleset_id' in data:
        ruleset_id = str(utils.escape(data['ruleset_id']))
        ruleset = get_ruleset(ruleset_id)
        if ruleset is None:
            return jsonify(Message='Unbekanntes Ruleset: {}'.format(ruleset_id)), 400
        game.ruleset_id = ruleset_id
        game.stack_max = ruleset['stack_max']
        game.stack = ruleset['stack_max']
        game.play_final = ruleset['play_final']
    elif 'stack_max' in data and 'play_final' in data:
        # Legacy support
        escaped_stack_max = int(utils.escape(data['stack_max']))
        game.stack_max = escaped_stack_max
        game.stack = escaped_stack_max
        escaped_play_final = str(utils.escape(data['play_final']))
        game.play_final = escaped_play_final.lower() in ['true', '1', 't', 'y', 'yes']
        game.ruleset_id = 'classic_13'  # default
    else:
        return jsonify(Message='Bitte ein Ruleset oder stack_max und play_final angeben'), 400

    game.status = Status.STARTED

    # Pick first user: use first_user_id if set (e.g. from previous game), else random
    active = game.active_users
    if game.first_user_id and any(u.id == game.first_user_id for u in active):
        game.move_user_id = game.first_user_id
    else:
        game.first_user_id = active[randrange(len(active))].id
        game.move_user_id = game.first_user_id

    # Reset all users for fresh start
    for user in active:
        user.chips = 0
        user.dice1 = None
        user.dice2 = None
        user.dice3 = None
        user.number_dice = 0
        user.passive = False
        user.dice1_visible = False
        user.dice2_visible = False
        user.dice3_visible = False

    # Falling dice option (default: off)
    falling_dice = data.get('falling_dice', False)
    if isinstance(falling_dice, str):
        falling_dice = falling_dice.lower() in ['true', '1', 't', 'y', 'yes']
    game.changs_of_fallling_dice = 0.003 if falling_dice else 0.0

    game.reveal_votes = ''
    game.player_changes_allowed = True
    db.session.add(game)
    db.session.commit()
    emit('reload_game', game.to_dict(), room=gid, namespace='/game')
    return jsonify(Message='Hat geklappt!'), 201


# Distribute chips (server-side scoring)
@bp.route('/game/<gid>/distribute', methods=['POST'])
def distribute_chips(gid):
    """Calculate scoring and distribute chips automatically based on rules."""
    game = Game.query.filter_by(UUID=gid).first()
    if game is None:
        return jsonify(Message='Spiel nicht gefunden'), 404

    # Validate phase
    if game.status not in (Status.STARTED, Status.PLAYFINAL):
        return jsonify(Message='Spiel ist nicht in einer spielbaren Phase'), 400
    if game.move_user_id != -1:
        return jsonify(Message='Noch nicht alle Spieler sind fertig'), 400
    if not game._all_dice_visible():
        return jsonify(Message='Noch nicht alle Wuerfel aufgedeckt'), 400

    # Calculate scoring
    scoring = calculate_scoring(game)
    if scoring is None:
        return jsonify(Message='Auswertung konnte nicht berechnet werden'), 500

    # Perform the chip transfer
    target_user = User.query.get(scoring['To'])
    if target_user is None:
        return jsonify(Message='Zielspieler nicht gefunden'), 500

    from_source = scoring['From']
    transfer_count = scoring['Chips']

    if from_source == 'schockaus':
        # Schock aus: all remaining stack chips to loser
        target_user.chips = target_user.chips + game.stack
        game.stack = 0
    elif from_source == 'stack':
        game.stack = game.stack - transfer_count
        target_user.chips = target_user.chips + transfer_count
    else:
        # From another player
        source_user = User.query.get(int(from_source))
        if source_user:
            source_user.chips = source_user.chips - transfer_count
            target_user.chips = target_user.chips + transfer_count

    game.first_user_id = target_user.id
    game.move_user_id = target_user.id

    # Short message for the game message line
    if from_source == 'schockaus':
        game.message = "Schock aus! Alle Chips an {}".format(scoring['To_Name'])
    else:
        game.message = "{} Chip(s) von {} an {}".format(
            transfer_count, scoring['From_Name'], scoring['To_Name'])

    # Handle round end (half/final logic)
    message = _handle_round_end(game, target_user)

    # If GAMEFINISCH: execute deferred actions
    if game.status == Status.GAMEFINISCH:
        execute_deferred_actions(game)

    db.session.add(game)
    db.session.commit()
    emit('reload_game', game.to_dict(), room=gid, namespace='/game')
    return jsonify(Message=message), 200


# Manual transfer chips (admin only, kept as "Manuelle Korrektur")
@bp.route('/game/<gid>/user/chips', methods=['POST'])
def transfer_chips(gid):
    """Manual chip transfer by admin."""
    game = Game.query.filter_by(UUID=gid).first()
    if game is None:
        return jsonify(Message='Spiel nicht gefunden'), 404

    data = request.get_json() or {}

    # B2: Admin check
    admin_id = data.get('admin_id')
    if admin_id and not _is_admin(game, int(admin_id)):
        return jsonify(Message='Nur Admins duerfen Chips verteilen'), 403

    if 'target' not in data:
        return jsonify(Message='request must include target'), 400

    response = jsonify(Message='success')

    # Transfer from user A to B
    if 'count' in data and 'source' in data and 'target' in data:
        escapedsource = str(utils.escape(data['source']))
        userA = User.query.get_or_404(escapedsource)
        escapedtarget = str(utils.escape(data['target']))
        userB = User.query.get_or_404(escapedtarget)
        if data['count'] is not None:
            escapedcount = int(utils.escape(data['count']))
        else:
            return jsonify(Message='No chips in count. try again'), 400

        if userA.chips >= escapedcount:
            if game.status == Status.PLAYFINAL:
                if userB.halfcount == 0 or userA.halfcount == 0:
                    return jsonify(Message='Benutzer nicht im Finale'), 400
            userA.chips = userA.chips - escapedcount
            userB.chips = userB.chips + escapedcount
            game.first_user_id = userB.id
            game.move_user_id = userB.id
            game.message = "{} Chip(s) von: {} an: {} verteilt!".format(escapedcount, userA.name, userB.name)
            db.session.add(game)
            db.session.commit()
        else:
            return jsonify(Message='nicht genuegend Chips an der Quelle'), 400

    # Transfer from stack to user B
    if 'count' in data and 'stack' in data and 'target' in data:
        escapedtarget = str(utils.escape(data['target']))
        userB = User.query.get_or_404(escapedtarget)
        if data['count'] is not None:
            escapedcount = int(utils.escape(data['count']))
        else:
            return jsonify(Message='No chips in count. try again'), 400
        if game.stack >= escapedcount:
            if game.status == Status.PLAYFINAL:
                if userB.halfcount == 0:
                    return jsonify(Message='Benutzer nicht im Finale'), 400
            game.stack = game.stack - escapedcount
            userB.chips = userB.chips + escapedcount
            game.first_user_id = userB.id
            game.move_user_id = userB.id
            game.message = "{} Chip(s) vom Stapel an: {} verteilt!".format(escapedcount, userB.name)
            db.session.add(game)
            db.session.commit()
        else:
            return jsonify(Message='Nicht genuegend Chips auf dem Stapel'), 400

    # Transfer all to B (Schockaus)
    if 'schockaus' in data and 'target' in data:
        escapedtarget = str(utils.escape(data['target']))
        userB = User.query.get_or_404(escapedtarget)
        escapedschockaus = utils.escape(data['schockaus'])
        if escapedschockaus:
            if game.status == Status.PLAYFINAL:
                if userB.halfcount == 0:
                    return jsonify(Message='Benutzer nicht im Finale'), 400
            game.stack = 0
            userB.chips = game.stack_max
            game.first_user_id = userB.id
            game.move_user_id = userB.id
            game.message = "Schockaus! Alle Chips an: {} verteilt!".format(userB.name)
            db.session.add(game)
            db.session.commit()
        else:
            return jsonify(Message='wrong transfer, check and try again'), 400

    # Handle round end logic
    if game.status == Status.ROUNDFINISCH or game.status == Status.GAMEFINISCH:
        game.status = Status.STARTED

    escapedtarget = str(utils.escape(data['target']))
    userB = User.query.get_or_404(escapedtarget)

    message = _handle_round_end(game, userB)

    if game.status == Status.GAMEFINISCH:
        execute_deferred_actions(game)

    response = jsonify(Message=message)
    db.session.add(game)
    db.session.commit()
    response.status_code = 200
    emit('reload_game', game.to_dict(), room=gid, namespace='/game')
    return response


# Toggle admin status for a user
@bp.route('/game/<gid>/user/<uid>/toggle_admin', methods=['POST'])
def toggle_admin(gid, uid):
    """Promote or demote a user to/from admin. Requester must be admin."""
    game = Game.query.filter_by(UUID=gid).first()
    if game is None:
        return jsonify(Message='Spiel nicht gefunden'), 404

    data = request.get_json() or {}
    requester_id = data.get('requester_id')
    if not requester_id or not _is_admin(game, int(requester_id)):
        return jsonify(Message='Nur Admins duerfen andere Admins ernennen'), 403

    target_user = User.query.get(uid)
    if target_user is None or target_user.game_id != game.id:
        return jsonify(Message='Spieler ist nicht in diesem Spiel'), 404

    if target_user.is_admin:
        # Demoting: check not the last admin
        admin_count = sum(1 for u in game.users if u.is_admin and u.id != target_user.id)
        if admin_count == 0:
            return jsonify(Message='Es muss mindestens einen Admin geben'), 400
        target_user.is_admin = False
        game.message = "{} ist kein Admin mehr".format(target_user.name)
    else:
        # Promoting
        target_user.is_admin = True
        game.message = "{} ist jetzt Admin".format(target_user.name)

    # Keep admin_user_id in sync for backward compat
    admins = [u for u in game.users if u.is_admin]
    if admins:
        game.admin_user_id = admins[0].id

    db.session.add(game)
    db.session.commit()
    emit('reload_game', game.to_dict(), room=gid, namespace='/game')
    return jsonify(Message='Hat geklappt!'), 200


# Mark/unmark player for leaving after current game
@bp.route('/game/<gid>/user/<uid>/mark_leave', methods=['POST'])
def mark_leave_after_game(gid, uid):
    """Toggle leave_after_game for a user. Own user or admin can do this."""
    game = Game.query.filter_by(UUID=gid).first()
    if game is None:
        return jsonify(Message='Spiel nicht gefunden'), 404

    target_user = User.query.get(uid)
    if target_user is None or target_user.game_id != game.id:
        return jsonify(Message='Spieler ist nicht in diesem Spiel'), 404

    data = request.get_json() or {}
    requester_id = data.get('requester_id')
    if not requester_id:
        return jsonify(Message='requester_id fehlt'), 400

    requester_id = int(requester_id)
    is_self = (requester_id == target_user.id)
    is_admin = _is_admin(game, requester_id)

    if not is_self and not is_admin:
        return jsonify(Message='Nur der Spieler selbst oder ein Admin kann diese Aktion ausfuehren'), 403

    # Toggle
    new_state = not target_user.leave_after_game

    # If marking to leave (not unmarking): check admin constraint
    if new_state and target_user.is_admin:
        other_admins = [u for u in game.users
                        if u.is_admin and u.id != target_user.id and not u.leave_after_game]
        if len(other_admins) == 0:
            return jsonify(Message='Du bist der letzte Admin. Ernenne erst einen weiteren Admin.'), 400

    target_user.leave_after_game = new_state

    # Immediate removal: only when player changes are allowed
    # (lobby or game just (re)started, before anyone rolled).
    if new_state:
        can_remove_now = game.player_changes_allowed
        if can_remove_now:
            # Remove immediately
            if target_user.id == game.first_user_id:
                # Find next user
                users = list(game.users)
                idx = next((i for i, u in enumerate(users) if u.id == target_user.id), 0)
                for offset in range(1, len(users)):
                    candidate = users[(idx + offset) % len(users)]
                    if candidate.id != target_user.id and not candidate.pending_join:
                        game.first_user_id = candidate.id
                        break
            if target_user.id == game.move_user_id:
                users = list(game.users)
                idx = next((i for i, u in enumerate(users) if u.id == target_user.id), 0)
                for offset in range(1, len(users)):
                    candidate = users[(idx + offset) % len(users)]
                    if candidate.id != target_user.id and not candidate.pending_join:
                        game.move_user_id = candidate.id
                        break

            game.message = "Spieler {} hat das Spiel verlassen".format(target_user.name)
            db.session.delete(target_user)
            db.session.add(game)
            db.session.commit()
            emit('reload_game', game.to_dict(), room=gid, namespace='/game')
            return jsonify(Message='Spieler entfernt'), 200

    db.session.add(game)
    db.session.commit()
    emit('reload_game', game.to_dict(), room=gid, namespace='/game')

    if new_state:
        return jsonify(Message='{} wird nach dem Spiel entfernt'.format(target_user.name)), 200
    else:
        return jsonify(Message='{} bleibt im Spiel'.format(target_user.name)), 200


# Toggle lobby-after-game flag
@bp.route('/game/<gid>/mark_lobby', methods=['POST'])
def mark_lobby_after_game(gid):
    """Toggle lobby_after_game. Admin only."""
    game = Game.query.filter_by(UUID=gid).first()
    if game is None:
        return jsonify(Message='Spiel nicht gefunden'), 404

    data = request.get_json() or {}
    requester_id = data.get('requester_id')
    if not requester_id or not _is_admin(game, int(requester_id)):
        return jsonify(Message='Nur Admins duerfen diese Aktion ausfuehren'), 403

    game.lobby_after_game = not game.lobby_after_game
    db.session.add(game)
    db.session.commit()
    emit('reload_game', game.to_dict(), room=gid, namespace='/game')

    if game.lobby_after_game:
        return jsonify(Message='Nach dem Spiel zurueck zur Lobby'), 200
    else:
        return jsonify(Message='Lobby nach dem Spiel aufgehoben'), 200


# XHR Delete User from Game (admin only)
@bp.route('/game/<gid>/user/<uid>', methods=['DELETE'])
def delete_player(gid, uid):
    game = Game.query.filter_by(UUID=gid).first()
    delete_user = User.query.get_or_404(uid)
    if game is None:
        return jsonify(Message='Spiel nicht gefunden'), 404
    if delete_user.game_id != game.id:
        return jsonify(Message='Spieler ist nicht in diesem Spiel'), 404

    # Cannot remove the last admin
    if delete_user.is_admin:
        admin_count = sum(1 for u in game.users if u.is_admin and u.id != delete_user.id)
        if admin_count == 0:
            return jsonify(Message='Letzter Admin kann nicht entfernt werden'), 400

    if delete_user.id == game.first_user_id:
        aktualuserid = [i for i, x in enumerate(game.users) if x == delete_user]
        if len(game.users) > aktualuserid[0]+1:
            game.first_user_id = game.users[aktualuserid[0]+1].id
        else:
            game.first_user_id = game.users[0].id
    if delete_user.id == game.move_user_id:
        aktualuserid = [i for i, x in enumerate(game.users) if x == delete_user]
        if len(game.users) > aktualuserid[0]+1:
            game.move_user_id = game.users[aktualuserid[0]+1].id
        else:
            game.move_user_id = game.users[0].id

    for user in game.users:
        user.chips = 0
        _reset_user_dice(user)
        user.passive = False

    game.stack = game.stack_max
    # H2: Removed "Seite neu laden" instruction
    game.message = "Spieler: {} wurde entfernt".format(delete_user.name)
    db.session.delete(delete_user)

    # Update admin_user_id for backward compat
    admins = [u for u in game.users if u.is_admin and u.id != delete_user.id]
    if admins:
        game.admin_user_id = admins[0].id

    db.session.add(game)
    db.session.commit()
    emit('reload_game', game.to_dict(), room=gid, namespace='/game')
    return jsonify(Message='success'), 200


# XHR choose new admin (legacy endpoint, now uses toggle_admin internally)
@bp.route('/game/<gid>/user/<uid>/change_admin', methods=['POST'])
def choose_admin(gid, uid):
    """Legacy endpoint: promote another user to admin."""
    game = Game.query.filter_by(UUID=gid).first()
    user = User.query.get_or_404(uid)
    data = request.get_json() or {}
    if 'new_admin_id' not in data:
        return jsonify(Message='request must include new_admin_id'), 400

    new_admin_id = str(utils.escape(data['new_admin_id']))
    new_admin = User.query.get_or_404(new_admin_id)

    if game is None:
        return jsonify(Message='Spiel nicht gefunden'), 404
    if user.game_id != game.id:
        return jsonify(Message='Spieler ist nicht in diesem Spiel'), 404
    if not user.is_admin:
        return jsonify(Message='Nur Admins duerfen diese Aktion ausfuehren'), 403

    # Promote the new admin
    new_admin.is_admin = True
    game.admin_user_id = new_admin.id
    # H2: Removed "Seite neu laden" instruction
    game.message = "{} ist jetzt auch Admin".format(new_admin.name)
    db.session.add(game)
    db.session.commit()
    emit('reload_game', game.to_dict(), room=gid, namespace='/game')
    return jsonify(Message='Hat geklappt!'), 200


# back to waiting
@bp.route('/game/<gid>/back', methods=['POST'])
def wait_game(gid):
    """The Admin can use this route to put the game back to the waiting area."""
    game = Game.query.filter_by(UUID=gid).first()
    if game is None:
        return jsonify(Message='Spiel nicht gefunden'), 404

    for user in game.users:
        if game.play_final:
            user.halfcount = 0
        user.chips = 0
        _reset_user_dice(user)
        user.passive = False
        user.leave_after_game = False
        user.pending_join = False

    if game.play_final:
        game.halfcount = 0
    game.message = ""
    game.stack = game.stack_max
    game.status = Status.WAITING
    game.lobby_after_game = False
    game.reveal_votes = ''
    game.player_changes_allowed = True
    db.session.add(game)
    db.session.commit()
    emit('reload_game', game.to_dict(), room=gid, namespace='/game')
    return jsonify(Message='success'), 201
