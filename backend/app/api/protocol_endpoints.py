"""
protocol_endpoints.py
====================================
API endpoints for the game protocol / statistics admin page.
Handles person management, nick-to-person mapping, statistics,
CSV import/export, and data deletion.
"""
from app.api import bp
from app import db, app

from flask import jsonify, request, session, Response
from app.models import (Person, GameLog, GameLogPlayer, NickMapping)

import csv
import io
from datetime import datetime
import pytz

BERLIN_TZ = pytz.timezone('Europe/Berlin')


def _check_protokoll_auth():
    return session.get('protokoll_auth', False)


def _auth_error():
    return jsonify(Message='Nicht autorisiert'), 401


# --------------- Authentication ---------------

@bp.route('/protokoll/auth', methods=['POST'])
def protokoll_auth():
    data = request.get_json() or {}
    password = data.get('password', '')
    configured = app.config.get('ADMIN_PASSWORD', '')
    if not configured:
        return jsonify(Message='Kein Admin-Passwort konfiguriert'), 500
    if password == configured:
        session['protokoll_auth'] = True
        return jsonify(Message='OK'), 200
    return jsonify(Message='Falsches Passwort'), 401


@bp.route('/protokoll/auth', methods=['DELETE'])
def protokoll_logout():
    session.pop('protokoll_auth', None)
    return jsonify(Message='OK'), 200


@bp.route('/protokoll/auth', methods=['GET'])
def protokoll_auth_check():
    if _check_protokoll_auth():
        return jsonify(authenticated=True), 200
    return jsonify(authenticated=False), 200


# --------------- Person CRUD ---------------

@bp.route('/protokoll/persons', methods=['GET'])
def list_persons():
    if not _check_protokoll_auth():
        return _auth_error()
    persons = Person.query.order_by(Person.name).all()
    return jsonify([{'id': p.id, 'name': p.name} for p in persons]), 200


@bp.route('/protokoll/persons', methods=['POST'])
def create_person():
    if not _check_protokoll_auth():
        return _auth_error()
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify(Message='Name darf nicht leer sein'), 400
    if Person.query.filter_by(name=name).first():
        return jsonify(Message='Person existiert bereits'), 400
    person = Person(name=name)
    db.session.add(person)
    db.session.commit()
    return jsonify({'id': person.id, 'name': person.name}), 201


@bp.route('/protokoll/persons/<int:pid>', methods=['PUT'])
def update_person(pid):
    if not _check_protokoll_auth():
        return _auth_error()
    person = Person.query.get_or_404(pid)
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify(Message='Name darf nicht leer sein'), 400
    existing = Person.query.filter_by(name=name).first()
    if existing and existing.id != pid:
        return jsonify(Message='Person mit diesem Namen existiert bereits'), 400
    person.name = name
    db.session.commit()
    return jsonify({'id': person.id, 'name': person.name}), 200


@bp.route('/protokoll/persons/<int:pid>', methods=['DELETE'])
def delete_person(pid):
    if not _check_protokoll_auth():
        return _auth_error()
    person = Person.query.get_or_404(pid)
    # Find affected game logs before removing the person reference
    affected_log_ids = db.session.query(GameLogPlayer.game_log_id).filter(
        GameLogPlayer.person_id == pid).distinct().all()
    affected_log_ids = [r[0] for r in affected_log_ids]
    GameLogPlayer.query.filter_by(person_id=pid).update({'person_id': None})
    NickMapping.query.filter_by(person_id=pid).delete()
    if affected_log_ids:
        GameLog.query.filter(GameLog.id.in_(affected_log_ids)).update(
            {'mapping_complete': False}, synchronize_session='fetch')
    db.session.delete(person)
    db.session.commit()
    return jsonify(Message='OK'), 200


# --------------- Game Logs ---------------

@bp.route('/protokoll/games', methods=['GET'])
def list_game_logs():
    if not _check_protokoll_auth():
        return _auth_error()

    incomplete_only = request.args.get('incomplete', 'false').lower() == 'true'
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    query = GameLog.query
    if incomplete_only:
        query = query.filter_by(mapping_complete=False)
    if date_from:
        query = query.filter(
            GameLog.game_date >= datetime.strptime(date_from, '%Y-%m-%d').date())
    if date_to:
        query = query.filter(
            GameLog.game_date <= datetime.strptime(date_to, '%Y-%m-%d').date())

    games = query.order_by(GameLog.game_date.desc(), GameLog.id.desc()).all()
    result = []
    for game in games:
        players = []
        for p in game.players:
            players.append({
                'id': p.id,
                'nick': p.nick,
                'is_loser': p.is_loser,
                'person_id': p.person_id,
                'person_name': p.person.name if p.person_id and p.person else None
            })
        result.append({
            'id': game.id,
            'game_uuid': game.game_uuid,
            'game_date': game.game_date.isoformat() if game.game_date else None,
            'mapping_complete': game.mapping_complete,
            'players': players
        })
    return jsonify(result), 200


@bp.route('/protokoll/games/<int:gid>/mapping', methods=['PUT'])
def update_game_mapping(gid):
    if not _check_protokoll_auth():
        return _auth_error()

    game_log = GameLog.query.get_or_404(gid)
    data = request.get_json() or {}
    # mappings: {player_id_str: person_id_int_or_null}
    mappings = data.get('mappings', {})

    for player in game_log.players:
        pid_str = str(player.id)
        if pid_str in mappings:
            person_id = mappings[pid_str]
            player.person_id = person_id
            if person_id:
                existing = NickMapping.query.filter_by(nick=player.nick).first()
                if existing:
                    existing.person_id = person_id
                else:
                    nm = NickMapping(nick=player.nick, person_id=person_id)
                    db.session.add(nm)

    game_log.mapping_complete = all(
        p.person_id is not None for p in game_log.players)

    db.session.commit()
    return jsonify(Message='OK', mapping_complete=game_log.mapping_complete), 200


@bp.route('/protokoll/games', methods=['DELETE'])
def delete_game_logs():
    if not _check_protokoll_auth():
        return _auth_error()

    data = request.get_json() or {}
    ids = data.get('ids', [])
    date_from = data.get('date_from')
    date_to = data.get('date_to')

    deleted = 0
    if ids:
        for gid in ids:
            game_log = GameLog.query.get(gid)
            if game_log:
                db.session.delete(game_log)
                deleted += 1
    elif date_from and date_to:
        df = datetime.strptime(date_from, '%Y-%m-%d').date()
        dt = datetime.strptime(date_to, '%Y-%m-%d').date()
        logs = GameLog.query.filter(
            GameLog.game_date >= df, GameLog.game_date <= dt).all()
        for log in logs:
            db.session.delete(log)
            deleted += 1

    db.session.commit()
    return jsonify(Message='{} Spiele gelöscht'.format(deleted)), 200


# --------------- Nick Mappings ---------------

@bp.route('/protokoll/nick_mappings', methods=['GET'])
def list_nick_mappings():
    if not _check_protokoll_auth():
        return _auth_error()
    mappings = NickMapping.query.all()
    result = {}
    for m in mappings:
        result[m.nick] = m.person_id
    return jsonify(result), 200


# --------------- Statistics ---------------

@bp.route('/protokoll/statistics', methods=['GET'])
def get_statistics():
    if not _check_protokoll_auth():
        return _auth_error()

    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    person_id = request.args.get('person_id', type=int)

    query = GameLog.query.filter_by(mapping_complete=True)
    if date_from:
        query = query.filter(
            GameLog.game_date >= datetime.strptime(date_from, '%Y-%m-%d').date())
    if date_to:
        query = query.filter(
            GameLog.game_date <= datetime.strptime(date_to, '%Y-%m-%d').date())
    if person_id:
        query = query.filter(
            GameLog.players.any(GameLogPlayer.person_id == person_id))

    games = query.order_by(GameLog.game_date, GameLog.id).all()

    # --- Game days ---
    game_days = {}
    for game in games:
        day = game.game_date.isoformat()
        if day not in game_days:
            game_days[day] = {'date': day, 'nicks': set(), 'mappings': {}}
        for p in game.players:
            game_days[day]['nicks'].add(p.nick)
            if p.person:
                game_days[day]['mappings'][p.nick] = p.person.name

    game_days_list = []
    for day_data in sorted(game_days.values(), key=lambda d: d['date']):
        day_data['nicks'] = sorted(day_data['nicks'])
        game_days_list.append(day_data)

    # --- Game results ---
    game_results = []
    for game in games:
        loser = None
        winners = []
        for p in game.players:
            pname = p.person.name if p.person else p.nick
            if p.is_loser:
                loser = pname
            else:
                winners.append(pname)
        game_results.append({
            'id': game.id,
            'date': game.game_date.strftime('%d.%m.%Y'),
            'loser': loser,
            'winners': sorted(winners)
        })

    # --- Beer sum ---
    beer_data = {}
    all_person_ids = set()

    for game in games:
        loser_pid = None
        winner_pids = []
        for p in game.players:
            if p.person_id:
                all_person_ids.add(p.person_id)
            if p.is_loser:
                loser_pid = p.person_id
            else:
                winner_pids.append(p.person_id)

        if loser_pid is None:
            continue

        for wpid in winner_pids:
            if wpid is None:
                continue
            # Loser owes winner a beer
            beer_data.setdefault(loser_pid, {}).setdefault(
                wpid, {'gives': 0, 'gets': 0})['gives'] += 1
            # Winner receives beer from loser
            beer_data.setdefault(wpid, {}).setdefault(
                loser_pid, {'gives': 0, 'gets': 0})['gets'] += 1

    person_map = {}
    for pid in all_person_ids:
        person = Person.query.get(pid)
        if person:
            person_map[pid] = person.name

    target_persons = [person_id] if person_id else sorted(
        all_person_ids, key=lambda p: person_map.get(p, ''))

    beer_summary = []
    for pid in target_persons:
        if pid not in person_map:
            continue
        opponents = []
        for opp_id, counts in beer_data.get(pid, {}).items():
            if opp_id not in person_map:
                continue
            opponents.append({
                'opponent': person_map[opp_id],
                'opponent_id': opp_id,
                'gives': counts['gives'],
                'gets': counts['gets'],
                'diff': counts['gets'] - counts['gives']
            })
        opponents.sort(key=lambda x: x['opponent'])
        beer_summary.append({
            'person': person_map[pid],
            'person_id': pid,
            'opponents': opponents
        })

    return jsonify({
        'game_days': game_days_list,
        'game_results': game_results,
        'beer_summary': beer_summary,
        'total_games': len(games)
    }), 200


# --------------- CSV Export ---------------

@bp.route('/protokoll/export', methods=['GET'])
def export_csv():
    if not _check_protokoll_auth():
        return _auth_error()

    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    person_id = request.args.get('person_id', type=int)

    query = GameLog.query.filter_by(mapping_complete=True)
    if date_from:
        query = query.filter(
            GameLog.game_date >= datetime.strptime(date_from, '%Y-%m-%d').date())
    if date_to:
        query = query.filter(
            GameLog.game_date <= datetime.strptime(date_to, '%Y-%m-%d').date())
    if person_id:
        query = query.filter(
            GameLog.players.any(GameLogPlayer.person_id == person_id))

    games = query.order_by(GameLog.game_date, GameLog.id).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_ALL)

    for game in games:
        loser = None
        winners = []
        for p in game.players:
            name = p.person.name if p.person else p.nick
            if p.is_loser:
                loser = name
            else:
                winners.append(name)
        row = [game.game_date.strftime('%d.%m.%Y'), loser] + sorted(winners)
        writer.writerow(row)

    resp = Response(output.getvalue(), mimetype='text/csv')
    resp.headers['Content-Disposition'] = \
        'attachment; filename=schocken_protokoll.csv'
    return resp


# --------------- CSV Import ---------------

@bp.route('/protokoll/import', methods=['POST'])
def import_csv():
    if not _check_protokoll_auth():
        return _auth_error()

    data = request.get_json() or {}
    csv_text = data.get('csv', '')

    if not csv_text:
        return jsonify(Message='Keine Daten'), 400

    reader = csv.reader(io.StringIO(csv_text), delimiter=';',
                        quotechar='"', quoting=csv.QUOTE_ALL)
    person_by_name = {p.name: p for p in Person.query.all()}
    imported = 0

    for row in reader:
        if len(row) < 2:
            continue

        date_str = row[0].strip().strip('"')
        loser_name = row[1].strip().strip('"')
        winner_names = [w.strip().strip('"') for w in row[2:]
                        if w.strip().strip('"')]

        try:
            game_date = datetime.strptime(date_str, '%d.%m.%Y').date()
        except ValueError:
            continue

        game_log = GameLog()
        game_log.game_date = game_date
        game_log.game_uuid = 'import'
        game_log.created_at = datetime.utcnow()

        lp = GameLogPlayer()
        lp.nick = loser_name
        lp.is_loser = True
        if loser_name in person_by_name:
            lp.person_id = person_by_name[loser_name].id
        game_log.players.append(lp)

        for wname in winner_names:
            wp = GameLogPlayer()
            wp.nick = wname
            wp.is_loser = False
            if wname in person_by_name:
                wp.person_id = person_by_name[wname].id
            game_log.players.append(wp)

        game_log.mapping_complete = all(
            p.person_id is not None for p in game_log.players)

        # Create nick mappings for matched names
        for p in game_log.players:
            if p.person_id:
                existing_nm = NickMapping.query.filter_by(nick=p.nick).first()
                if not existing_nm:
                    nm = NickMapping(nick=p.nick, person_id=p.person_id)
                    db.session.add(nm)

        db.session.add(game_log)
        imported += 1

    db.session.commit()
    return jsonify(Message='{} Spiele importiert'.format(imported)), 200


# --------------- Game Logging Helper ---------------

def log_game_result(game, loser):
    """
    Called when a game reaches GAMEFINISCH.
    Logs the loser and all winners (active non-loser players).
    Uses game.started date as the Spieltag date.
    """
    game_date = game.started.date() if game.started else datetime.now(
        BERLIN_TZ).date()

    game_log = GameLog()
    game_log.game_uuid = game.UUID
    game_log.game_date = game_date
    game_log.created_at = datetime.now(BERLIN_TZ)

    def find_person(nick):
        nm = NickMapping.query.filter_by(nick=nick).first()
        return nm.person_id if nm else None

    lp = GameLogPlayer()
    lp.nick = loser.name
    lp.is_loser = True
    lp.person_id = find_person(loser.name)
    game_log.players.append(lp)

    for user in game.active_users:
        if user.id != loser.id:
            wp = GameLogPlayer()
            wp.nick = user.name
            wp.is_loser = False
            wp.person_id = find_person(user.name)
            game_log.players.append(wp)

    game_log.mapping_complete = all(
        p.person_id is not None for p in game_log.players)

    db.session.add(game_log)
