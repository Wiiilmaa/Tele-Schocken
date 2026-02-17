from app.api import bp
from app import app, db

from flask_socketio import emit, join_room
from flask import jsonify
from flask import request
from app.models import User, Game, Status
from random import randint, random, seed
from datetime import datetime
from jinja2 import utils

from app.api.errors import bad_request


from flask import session

from flask_socketio import SocketIO
# Set this variable to "threading", "eventlet" or "gevent" to test the
# different async modes, or leave it set to None for the application to choose
# the best option based on installed packages.
async_mode = "gevent"
socketio = SocketIO(app, async_mode=async_mode, cors_allowed_origins="*")


# Get User from Game
def get_Index_Of_User(game, uid):
    id = int(uid)
    for i, x in enumerate(game.users):
        if x.id == id:
            return i
    return -1


def _get_next_active_user(game, current_index):
    """Find the next active (non-passive, non-pending) user in turn order.
    Returns (user_id, found_first_user) where found_first_user means we
    wrapped around to the first user (round complete -> move_user_id = -1).
    """
    active = game.active_users
    if len(active) < 2:
        return -1, True

    # Find current user in active list
    current_user = game.users[current_index]
    active_index = -1
    for i, u in enumerate(active):
        if u.id == current_user.id:
            active_index = i
            break

    if active_index == -1:
        return -1, True

    for i in range(1, len(active)):
        test = (active_index + i) % len(active)
        if active[test].id == game.first_user_id:
            return -1, True
        if not active[test].passive:
            return active[test].id, False

    return -1, True


@socketio.on('connect', namespace='/game')
def test_connect():
    emit('my_response', {'data': 'Connected', 'count': 0})


@socketio.on('join', namespace='/game')
def join(message):
    join_room(message['room'])
    session['receive_count'] = session.get('receive_count', 0) + 1
    print('join room {}'.format(message['room']))
    game = Game.query.filter_by(UUID=message['room']).first()
    if game is not None:
        emit('reload_game', game.to_dict(), room=game.UUID, namespace='/game')


# get Game Data
@bp.route('/game/<gid>', methods=['GET'])
def get_game(gid):
    """**GET   /api/game/<gid>**

    Return a hole game as json

    :reqheader Accept: application/json
    :statuscode 200: Game Data
    :statuscode 404: Game id not in Database
    """
    game = Game.query.filter_by(UUID=gid).first()
    if game is None:
        response = jsonify(Message='Spiel ist nicht in der Datenbank')
        response.status_code = 404
        return response
    response = jsonify(game.to_dict())
    response.status_code = 200
    return response


# set User to Game (supports mid-game joining)
@bp.route('/game/<gid>/user', methods=['POST'])
def set_game_user(gid):
    """Add a User to a game. Supports joining during WAITING (immediate),
    during active game (pending if someone rolled, immediate if not),
    and during GAMEFINISCH (immediate for next game).
    """
    game = Game.query.filter_by(UUID=gid).first()
    if game is None:
        response = jsonify()
        response.status_code = 404
        return response

    data = request.get_json() or {}
    if 'name' not in data:
        return bad_request('must include name field')
    escapedusername = str(utils.escape(data['name']))

    if len(escapedusername.strip()) == 0:
        response = jsonify(Message='Benutzername darf nicht leer sein!')
        response.status_code = 400
        return response

    inuse = User.query.filter_by(name=escapedusername).first()
    if inuse is not None:
        response = jsonify(Message='Benutzername schon vergeben!')
        response.status_code = 400
        return response

    user = User()
    user.name = escapedusername

    if game.player_changes_allowed:
        # Game is in lobby or just (re)started and nobody rolled yet: join immediately
        user.pending_join = False
    else:
        # Game in progress: queue for next game.
        # execute_deferred_actions will activate them when the game ends.
        user.pending_join = True

    game.users.append(user)
    db.session.add(game)
    db.session.commit()
    emit('reload_game', game.to_dict(), room=gid, namespace='/game')
    return jsonify(game.to_dict())


# pull up the dice cup
# A3 fix: added leading /
@bp.route('/game/<gid>/user/<uid>/visible', methods=['POST'])
def pull_up_dice_cup(gid, uid):
    """
    Pull the Dice cup up so that every user can see the dice's
    """
    game = Game.query.filter_by(UUID=gid).first()
    if game is None:
        response = jsonify(Message='Spiel nicht gefunden')
        response.status_code = 404
        return response

    # B1: Game status check
    if game.status not in (Status.STARTED, Status.PLAYFINAL):
        response = jsonify(Message='Spiel ist nicht in einer spielbaren Phase')
        response.status_code = 400
        return response

    user_index = get_Index_Of_User(game, uid)
    if user_index > -1:
        user = game.users[user_index]
    if user_index < 0 or user.game_id != game.id:
        response = jsonify(Message='Spieler ist nicht in diesem Spiel')
        response.status_code = 404
        return response

    # B3: Must have rolled at least once to show dice
    if user.number_dice == 0:
        response = jsonify(Message='Du musst zuerst würfeln!')
        response.status_code = 400
        return response

    data = request.get_json() or {}
    if 'visible' in data:
        escapedvisible = str(utils.escape(data['visible']))
        val = escapedvisible.lower() in ['true', '1']
        user.dice1_visible = val
        user.dice2_visible = val
        user.dice3_visible = val

        # Check if all active non-passive users have revealed
        allvisible = True
        for u in game.active_users:
            if not (u.passive or (u.dice1_visible and u.dice2_visible and u.dice3_visible)):
                allvisible = False
        if allvisible and game.move_user_id == -1:
            game.message = "Warten auf Vergabe der Chips!"

        db.session.add(game)
        db.session.commit()
        response = jsonify(Message='Hat geklappt!')
        response.status_code = 201
        emit('reload_game', game.to_dict(), room=gid, namespace='/game')
        return response
    else:
        response = jsonify(Message="Request must include visible")
        response.status_code = 400
        return response


# user finishes before third roll
@bp.route('/game/<gid>/user/<uid>/finisch', methods=['POST'])
def finish_throwing(gid, uid):
    game = Game.query.filter_by(UUID=gid).first()
    if game is None:
        response = jsonify(Message='Spiel nicht gefunden')
        response.status_code = 404
        return response

    # B1: Game status check
    if game.status not in (Status.STARTED, Status.PLAYFINAL):
        response = jsonify(Message='Spiel ist nicht in einer spielbaren Phase')
        response.status_code = 400
        return response

    user_index = get_Index_Of_User(game, uid)
    if user_index > -1:
        user = game.users[user_index]
    if user_index < 0 or user.game_id != game.id:
        response = jsonify(Message='Spieler ist nicht in diesem Spiel')
        response.status_code = 404
        return response
    # chips on the stack need to dice once
    # no chips on the stack but user has chips so you need to dice once
    if (game.stack != 0 or user.chips != 0) and user.number_dice == 0:
        response = jsonify(Message='Du musst mindestens einmal würfeln!')
        response.status_code = 400
        return response
    if user.dice1 is None or user.dice2 is None or user.dice3 is None:
        response = jsonify(Message='Nach dem Verwandeln von Sechsen in Einsen musst Du nochmal würfeln')
        response.status_code = 400
        return response
    if user.id == game.move_user_id:
        next_id, is_round_complete = _get_next_active_user(game, user_index)
        if is_round_complete:
            game.move_user_id = -1
        else:
            game.move_user_id = next_id
        if game.move_user_id == -1:
            game.message = "Aufdecken!"
        db.session.add(game)
        db.session.commit()
        response = jsonify(Message='Hat geklappt!')
        response.status_code = 200
        emit('reload_game', game.to_dict(), room=gid, namespace='/game')
        return response
    else:
        response = jsonify(Message='Du bist nicht dran!')
        response.status_code = 400
        return response


# set user aktiv or passiv
@bp.route('/game/<gid>/user/<uid>/passiv', methods=['POST'])
def set_user_passiv(gid, uid):
    game = Game.query.filter_by(UUID=gid).first()
    if game is None:
        response = jsonify(Message='Spiel nicht gefunden')
        response.status_code = 404
        return response

    # B1: Game status check
    if game.status not in (Status.STARTED, Status.PLAYFINAL):
        response = jsonify(Message='Spiel ist nicht in einer spielbaren Phase')
        response.status_code = 400
        return response

    user_index = get_Index_Of_User(game, uid)
    if user_index > -1:
        user = game.users[user_index]
    if user_index < 0 or user.game_id != game.id:
        response = jsonify(Message='Spieler ist nicht in diesem Spiel')
        response.status_code = 404
        return response
    data = request.get_json() or {}
    if 'userstate' in data:
        escapeduserstate = str(utils.escape(data['userstate']))
        val = escapeduserstate.lower() in ['true', '1']

        # Finale: pause is never allowed, reject immediately without penalty
        if val and game.status == Status.PLAYFINAL:
            response = jsonify(Message='Pause im Finale nicht erlaubt')
            response.status_code = 400
            return response

        # Penalty check: pressing pause when not allowed
        if val and not user.passive:
            has_stack = game.stack > 0
            has_chips = (user.chips or 0) > 0

            if has_stack or has_chips:
                # Invalid pause attempt -> penalty
                user.penalty_count = (user.penalty_count or 0) + 1

                # Build penalty reason
                reasons = []
                if has_stack:
                    reasons.append('Chips auf dem Stapel')
                if has_chips:
                    reasons.append('eigener Chips')

                # Broadcast message to all
                if has_stack and has_chips:
                    game.message = '{}: Pause trotz Chips auf Stapel und eigener Chips'.format(user.name)
                elif has_stack:
                    game.message = '{}: Pause trotz Chips auf Stapel'.format(user.name)
                elif has_chips:
                    game.message = '{}: Pause trotz Chips'.format(user.name)

                db.session.add(user)
                db.session.add(game)
                db.session.commit()

                penalty_reason = ' und '.join(reasons)
                popup_msg = 'Pausierversuch trotz {}. Dafür musst Du Dich {} mal Einwürfeln'.format(
                    penalty_reason, user.penalty_count)

                emit('reload_game', game.to_dict(), room=gid, namespace='/game')
                response = jsonify(Message=popup_msg, Penalty=True, Penalty_Count=user.penalty_count)
                response.status_code = 400
                return response

            # Check penalty counter: must roll instead of pausing
            if (user.penalty_count or 0) > 0:
                response = jsonify(Message='Du musst Dich {} mal Einwürfeln bevor Du pausieren darfst'.format(
                    user.penalty_count))
                response.status_code = 400
                return response

        user.passive = val

        # If the player goes passive while it's their turn, auto-advance
        if val and user.id == game.move_user_id:
            next_id, is_round_complete = _get_next_active_user(game, user_index)
            if is_round_complete:
                game.move_user_id = -1
            else:
                game.move_user_id = next_id
            if game.move_user_id == -1:
                game.message = "Aufdecken!"

        db.session.add(user)
        db.session.commit()
        response = jsonify(Message='Hat geklappt!')
        response.status_code = 201
        emit('reload_game', game.to_dict(), room=gid, namespace='/game')
        return response
    else:
        response = jsonify(Message="Request must include userstate")
        response.status_code = 400
        return response


# roll dice
@bp.route('/game/<gid>/user/<uid>/dice', methods=['POST'])
def roll_dice(gid, uid):
    """A user can roll up to 3 dice."""
    game = Game.query.filter_by(UUID=gid).first()
    if game is None:
        response = jsonify(Message='Spiel nicht gefunden')
        response.status_code = 404
        return response

    # B1: Game status check (removed implicit GAMEFINISCH->STARTED transition)
    if game.status not in (Status.STARTED, Status.PLAYFINAL):
        response = jsonify(Message='Spiel ist nicht in einer spielbaren Phase')
        response.status_code = 400
        return response

    # Minimum 2 active players required
    if len(game.active_users) < 2:
        response = jsonify(Message='Nicht genug Mitspieler')
        response.status_code = 400
        return response

    user_index = get_Index_Of_User(game, uid)
    if user_index > -1:
        user = game.users[user_index]
    if user_index < 0 or user.game_id != game.id:
        response = jsonify(Message='Spieler ist nicht in diesem Spiel')
        response.status_code = 404
        return response

    data = request.get_json() or {}
    # A2 fix: load first_user to get their number_dice
    first_user = User.query.get(game.first_user_id)
    first_user_dice = first_user.number_dice if first_user else 3

    # Once someone rolls, no more immediate player changes until next game
    if game.player_changes_allowed:
        game.player_changes_allowed = False

    # Decrement penalty counter on first roll when player could have paused
    if (user.number_dice == 0 and (user.penalty_count or 0) > 0
            and game.stack == 0 and (user.chips or 0) == 0
            and game.status != Status.PLAYFINAL):
        user.penalty_count = user.penalty_count - 1

    game.refreshed = datetime.now()
    if user.id == game.move_user_id:
        if game.first_user_id == user.id or user.number_dice < first_user_dice:
            if user.number_dice >= 3:
                response = jsonify(Message='Du hast schon dreimal gewürfelt!')
                response.status_code = 400
                return response
            # Check if a dice fall from the table and return if so
            fallen = decision(game.changs_of_fallling_dice)
            if fallen:
                game.message = "Hoppla, {} ist ein Würfel vom Tisch gefallen!".format(user.name)
                game.fallling_dice_count = game.fallling_dice_count + 1
                db.session.add(game)
                db.session.commit()
                response = jsonify(fallen=fallen, dice1=user.dice1, dice2=user.dice2, dice3=user.dice3, number_dice=user.number_dice)
                response.status_code = 201
                emit('reload_game', game.to_dict(), room=gid, namespace='/game')
                return response
            user.number_dice = user.number_dice + 1
            # Check if this was the last roll for this user
            if user.number_dice == 3 or (user.id != game.first_user_id and user.number_dice == first_user_dice):
                next_id, is_round_complete = _get_next_active_user(game, user_index)
                if is_round_complete:
                    game.move_user_id = -1
                else:
                    # A1 fix: was next_user.id (undefined), now correctly uses next_id
                    game.move_user_id = next_id
                if game.move_user_id == -1:
                    game.message = "Aufdecken!"

            seed()
            if 'dice1' in data and str(utils.escape(data['dice1'])).lower() in ['true', '1']:
                user.dice1 = randint(1, 6)
                user.dice1_visible = False
            else:
                user.dice1_visible = True
            if 'dice2' in data and str(utils.escape(data['dice2'])).lower() in ['true', '1']:
                user.dice2 = randint(1, 6)
                user.dice2_visible = False
            else:
                user.dice2_visible = True
            if 'dice3' in data and str(utils.escape(data['dice3'])).lower() in ['true', '1']:
                user.dice3 = randint(1, 6)
                user.dice3_visible = False
            else:
                user.dice3_visible = True
        else:
            response = jsonify(Message='Du bist nicht dran!')
            response.status_code = 400
            return response

        # Statistic
        if user.dice1 == 1 and user.dice2 == 1 and user.dice3 == 1:
            game.schockoutcount = game.schockoutcount + 1
        game.throw_dice_count = game.throw_dice_count + 1

        # D1: Single commit instead of multiple
        db.session.add(game)
        db.session.add(user)
        db.session.commit()

        response = jsonify(fallen=fallen, dice1=user.dice1, dice2=user.dice2, dice3=user.dice3, number_dice=user.number_dice)
        response.status_code = 201
        emit('reload_game', game.to_dict(), room=gid, namespace='/game')
        return response
    else:
        response = jsonify(Message='Du bist nicht dran!')
        response.status_code = 400
    return response


# turn dice (2 or 3 6er to 1 or 2 1er)
@bp.route('/game/<gid>/user/<uid>/diceturn', methods=['POST'])
def turn_dice(gid, uid):
    """If a User Throws two or three 6er in Throw 1 or 2 they are allowed
    to turn 1 dice (two 6er) or 2 dice (three 6er) to dice with the number 1
    """
    game = Game.query.filter_by(UUID=gid).first()
    if game is None:
        response = jsonify(Message='Spiel nicht gefunden')
        response.status_code = 404
        return response

    # B1: Game status check
    if game.status not in (Status.STARTED, Status.PLAYFINAL):
        response = jsonify(Message='Spiel ist nicht in einer spielbaren Phase')
        response.status_code = 400
        return response

    user_index = get_Index_Of_User(game, uid)
    if user_index > -1:
        user = game.users[user_index]
    if user_index < 0 or user.game_id != game.id:
        response = jsonify(Message='Spieler ist nicht in diesem Spiel')
        response.status_code = 404
        return response
    data = request.get_json() or {}
    first_user = User.query.get_or_404(game.first_user_id)
    waitinguser = User.query.get_or_404(game.move_user_id)
    if waitinguser.id == user.id:
        if first_user.number_dice == 0 or user.number_dice < first_user.number_dice or first_user.number_dice < 3:
            if 'count' in data:
                escapedcount = str(utils.escape(data['count']))
                if int(escapedcount) == 1:
                    if user.dice1 == 6 and user.dice2 == 6:
                        user.dice1 = 1
                        user.dice2 = None
                    elif user.dice2 == 6 and user.dice3 == 6:
                        user.dice2 = 1
                        user.dice3 = None
                    elif user.dice1 == 6 and user.dice3 == 6:
                        user.dice1 = 1
                        user.dice3 = None
                    else:
                        response = jsonify(Message='Keine zwei Sechsen gefunden')
                        response.status_code = 400
                        return response
                elif int(escapedcount) == 2:
                    if user.dice1 == 6 and user.dice2 == 6 and user.dice3 == 6:
                        user.dice1 = 1
                        user.dice2 = 1
                        user.dice3 = None
                    else:
                        response = jsonify(Message='Keine drei Sechsen gefunden')
                        response.status_code = 400
                        return response
                else:
                    response = jsonify(Message='count value not 1 or 2')
                    response.status_code = 400
                    return response
            else:
                response = jsonify(Message='count not in data')
                response.status_code = 400
                return response
        else:
            response = jsonify(Message='Du musst nach dem Umdrehen noch würfeln können')
            response.status_code = 400
            return response
    else:
        response = jsonify(Message='Du bist nicht dran!')
        response.status_code = 400
        return response
    response = jsonify(dice1=user.dice1, dice2=user.dice2, dice3=user.dice3)
    response.status_code = 201
    db.session.add(user)
    db.session.commit()
    # D2: Add reload_game emit after diceturn
    emit('reload_game', game.to_dict(), room=gid, namespace='/game')
    return response


# undo a diceturn (revert 1->6, optionally restore None->6)
@bp.route('/game/<gid>/user/<uid>/diceturn_undo', methods=['POST'])
def undo_turn_dice(gid, uid):
    game = Game.query.filter_by(UUID=gid).first()
    if game is None:
        return jsonify(Message='Spiel nicht gefunden'), 404

    if game.status not in (Status.STARTED, Status.PLAYFINAL):
        return jsonify(Message='Spiel ist nicht in einer spielbaren Phase'), 400

    user_index = get_Index_Of_User(game, uid)
    if user_index > -1:
        user = game.users[user_index]
    if user_index < 0 or user.game_id != game.id:
        return jsonify(Message='Spieler ist nicht in diesem Spiel'), 404

    if user.id != game.move_user_id:
        return jsonify(Message='Du bist nicht dran!'), 400

    data = request.get_json() or {}
    revert_index = data.get('revert_index')
    restore_index = data.get('restore_index')

    dice_vals = [user.dice1, user.dice2, user.dice3]

    if revert_index is not None:
        ri = int(revert_index) - 1
        if ri < 0 or ri > 2 or dice_vals[ri] != 1:
            return jsonify(Message='Ungültiger Würfel zum Zurücksetzen'), 400
        dice_vals[ri] = 6

    if restore_index is not None:
        rsi = int(restore_index) - 1
        if rsi < 0 or rsi > 2 or dice_vals[rsi] is not None:
            return jsonify(Message='Ungültiger Würfel zum Wiederherstellen'), 400
        dice_vals[rsi] = 6

    user.dice1, user.dice2, user.dice3 = dice_vals
    db.session.add(user)
    db.session.commit()
    emit('reload_game', game.to_dict(), room=gid, namespace='/game')
    return jsonify(dice1=user.dice1, dice2=user.dice2, dice3=user.dice3), 201


# XHR Route: sort dice for visual comparison
@bp.route('/game/<gid>/sort', methods=['PUT'])
def sort_dice(gid):
    data = request.get_json() or {}
    if 'admin_id' in data:
        game = Game.query.filter_by(UUID=gid).first()
        escape = str(utils.escape(data['admin_id']))
        user = User.query.get_or_404(escape)
        if game is None:
            response = jsonify(Message='Spiel nicht gefunden')
            response.status_code = 404
            return response
        if user.game_id != game.id:
            response = jsonify(Message='Spieler ist nicht in diesem Spiel')
            response.status_code = 404
            return response
        # B2: Admin check
        if not user.is_admin:
            response = jsonify(Message='Nur Admins dürfen diese Aktion ausführen')
            response.status_code = 403
            return response

        if game.move_user_id == -1 and game._all_dice_visible():
            for u in game.active_users:
                if not u.passive:
                    dices = [u.dice1 or 0, u.dice2 or 0, u.dice3 or 0]
                    dices.sort()
                    u.dice1 = dices[2]
                    u.dice2 = dices[1]
                    u.dice3 = dices[0]
            db.session.add(game)
            db.session.commit()
            emit('reload_game', game.to_dict(), room=gid, namespace='/game')
        else:
            response = jsonify(Message='Warten bis alle aufgedeckt haben!')
            response.status_code = 403
            return response
    else:
        return bad_request('must include admin_id')
    response = jsonify()
    response.status_code = 200
    return response


# Vote to reveal all dice
@bp.route('/game/<gid>/vote_reveal', methods=['POST'])
def vote_reveal_all(gid):
    """Vote to force-reveal all dice. Admin triggers immediately,
    otherwise need strict majority (>50%) of active non-passive players.
    """
    game = Game.query.filter_by(UUID=gid).first()
    if game is None:
        return jsonify(Message='Spiel nicht gefunden'), 404

    if game.status not in (Status.STARTED, Status.PLAYFINAL):
        return jsonify(Message='Spiel ist nicht in einer spielbaren Phase'), 400

    if game.move_user_id != -1:
        return jsonify(Message='Runde ist noch nicht beendet'), 400

    if game._all_dice_visible():
        return jsonify(Message='Alle Würfel sind bereits aufgedeckt'), 400

    data = request.get_json() or {}
    requester_id = data.get('requester_id')
    if not requester_id:
        return jsonify(Message='requester_id fehlt'), 400

    requester_id = int(requester_id)
    user = User.query.get(requester_id)
    if user is None or user.game_id != game.id:
        return jsonify(Message='Spieler ist nicht in diesem Spiel'), 404

    # Track votes
    current_votes = set(v for v in (game.reveal_votes or '').split(',') if v)
    current_votes.add(str(requester_id))
    game.reveal_votes = ','.join(current_votes)

    # Count ALL players (including pending/waiting) for threshold
    vote_count = len(current_votes)
    threshold = (len(game.users) + 1) // 2  # half (rounded up): 2 of 2, 2 of 3, etc.

    # Admin vote triggers immediately
    is_admin = user.is_admin

    if is_admin or vote_count >= threshold:
        # Reveal all dice
        for u in game.active_users:
            if not u.passive:
                u.dice1_visible = True
                u.dice2_visible = True
                u.dice3_visible = True
        game.reveal_votes = ''
        game.message = "Warten auf Vergabe der Chips!"
        db.session.add(game)
        db.session.commit()
    else:
        game.message = "Aufdecken! ({}/{} Stimmen für Alles aufdecken)".format(
            vote_count, threshold)
        db.session.add(game)
        db.session.commit()

    emit('reload_game', game.to_dict(), room=gid, namespace='/game')
    return jsonify(Message='Stimme gezählt'), 200


# to fall a dice from the tableCount
# the chance increases each round
def decision(probability) -> bool:
    """
    Return a Boolean that represent a fallen dice
    """
    return random() < probability
