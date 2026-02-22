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


# --------------- Date-based Mapping ---------------

@bp.route('/protokoll/mapping_by_date', methods=['PUT'])
def update_mapping_by_date():
    """Update nick->person mappings for ALL games on a given date."""
    if not _check_protokoll_auth():
        return _auth_error()

    data = request.get_json() or {}
    date_str = data.get('date')
    mappings = data.get('mappings', {})  # {nick: person_id_or_null}

    if not date_str:
        return jsonify(Message='Datum fehlt'), 400

    game_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    game_logs = GameLog.query.filter_by(game_date=game_date).all()

    for gl in game_logs:
        for player in gl.players:
            if player.nick in mappings:
                person_id = mappings[player.nick]
                player.person_id = person_id
                if person_id:
                    existing = NickMapping.query.filter_by(
                        nick=player.nick).first()
                    if existing:
                        existing.person_id = person_id
                    else:
                        nm = NickMapping(nick=player.nick,
                                         person_id=person_id)
                        db.session.add(nm)
        gl.mapping_complete = all(
            p.person_id is not None for p in gl.players)

    db.session.commit()
    return jsonify(Message='OK'), 200


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
    dry_run = data.get('dry_run', False)

    if not csv_text:
        return jsonify(Message='Keine Daten'), 400

    reader = csv.reader(io.StringIO(csv_text), delimiter=';',
                        quotechar='"', quoting=csv.QUOTE_ALL)
    person_by_name = {p.name: p for p in Person.query.all()}
    importable = 0
    errors = []

    for line_num, row in enumerate(reader, 1):
        if len(row) < 2:
            errors.append({'line': line_num,
                           'text': ';'.join(row),
                           'error': 'Zu wenige Spalten'})
            continue

        date_str = row[0].strip().strip('"')
        loser_name = row[1].strip().strip('"')
        winner_names = [w.strip().strip('"') for w in row[2:]
                        if w.strip().strip('"')]

        try:
            game_date = datetime.strptime(date_str, '%d.%m.%Y').date()
        except ValueError:
            errors.append({'line': line_num,
                           'text': ';'.join(row),
                           'error': 'Ungültiges Datum: ' + date_str})
            continue

        if not winner_names:
            errors.append({'line': line_num,
                           'text': ';'.join(row),
                           'error': 'Keine Gewinner angegeben'})
            continue

        if dry_run:
            importable += 1
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

        for p in game_log.players:
            if p.person_id:
                existing_nm = NickMapping.query.filter_by(
                    nick=p.nick).first()
                if not existing_nm:
                    nm = NickMapping(nick=p.nick, person_id=p.person_id)
                    db.session.add(nm)

        db.session.add(game_log)
        importable += 1

    if not dry_run:
        db.session.commit()

    msg = '{} Spiele importiert'.format(importable) if not dry_run \
        else '{} Spiele importierbar'.format(importable)
    return jsonify(Message=msg, imported=importable, errors=errors), 200


# --------------- Markdown Import ---------------

def _parse_md_import(text):
    """
    Parse a markdown/outliner game log.

    Expected structure:
      * YYYYMMDD
          * Loser: N Runde(n) (Winner1, Winner2, ...)
    Year headings (* YYYY) are silently skipped as grouping headers.
    Returns (results, errors) where results is a list of
    (date, loser, count, [winners]) tuples and errors is a list of
    (line_number, line_text, error_description) tuples.
    """
    import re

    lines = text.split('\n')
    current_date = None
    results = []
    errors = []

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped:
            continue

        # Remove markdown list markers (*, -, +) and leading whitespace
        cleaned = re.sub(r'^[\s\t]*[\*\-\+]\s*', '', line).strip()
        if not cleaned:
            continue

        # Date: 8 digits (YYYYMMDD)
        if re.match(r'^\d{8}$', cleaned):
            try:
                current_date = datetime.strptime(cleaned, '%Y%m%d').date()
            except ValueError:
                errors.append((i, stripped, 'Ungültiges Datum: ' + cleaned))
            continue

        # Year heading: 4 digits only (just a grouping header, skip)
        if re.match(r'^\d{4}$', cleaned):
            continue

        # Game entry: Loser: N Runde(n) (Winner1, Winner2, ...)
        m = re.match(
            r'^(.+?)\s*:\s*(\d+)\s*Runden?\s*\((.+)\)\s*$', cleaned)
        if m:
            if current_date is None:
                errors.append(
                    (i, stripped, 'Kein Datum vor dieser Zeile definiert'))
                continue
            loser = m.group(1).strip()
            count = int(m.group(2))
            winners = [w.strip() for w in m.group(3).split(',')
                       if w.strip()]
            if not winners:
                errors.append((i, stripped, 'Leere Gewinner-Liste'))
                continue
            results.append((current_date, loser, count, winners))
            continue

        # Game entry without winners in parentheses
        m = re.match(r'^(.+?)\s*:\s*(\d+)\s*Runden?\s*$', cleaned)
        if m:
            errors.append(
                (i, stripped, 'Keine Gewinner in Klammern angegeben'))
            continue

        # Unrecognized non-empty line
        errors.append(
            (i, stripped, 'Zeile konnte nicht interpretiert werden'))

    return results, errors


@bp.route('/protokoll/import_md', methods=['POST'])
def import_md():
    if not _check_protokoll_auth():
        return _auth_error()

    data = request.get_json() or {}
    text = data.get('text', '')
    dry_run = data.get('dry_run', False)

    if not text:
        return jsonify(Message='Keine Daten'), 400

    results, parse_errors = _parse_md_import(text)
    error_list = [{'line': e[0], 'text': e[1], 'error': e[2]}
                  for e in parse_errors]

    # Count total games that would be created (sum of counts)
    importable = sum(count for _, _, count, _ in results)

    if dry_run or (not results and parse_errors):
        msg = '{} Spiele importierbar'.format(importable) if results \
            else 'Keine Spiele erkannt'
        return jsonify(Message=msg, imported=importable,
                       errors=error_list), 200

    person_by_name = {p.name: p for p in Person.query.all()}
    imported = 0

    for game_date, loser, count, winners in results:
        for _ in range(count):
            game_log = GameLog()
            game_log.game_date = game_date
            game_log.game_uuid = 'import'
            game_log.created_at = datetime.utcnow()

            lp = GameLogPlayer()
            lp.nick = loser
            lp.is_loser = True
            if loser in person_by_name:
                lp.person_id = person_by_name[loser].id
            game_log.players.append(lp)

            for wname in winners:
                wp = GameLogPlayer()
                wp.nick = wname
                wp.is_loser = False
                if wname in person_by_name:
                    wp.person_id = person_by_name[wname].id
                game_log.players.append(wp)

            game_log.mapping_complete = all(
                p.person_id is not None for p in game_log.players)

            for p in game_log.players:
                if p.person_id:
                    existing_nm = NickMapping.query.filter_by(
                        nick=p.nick).first()
                    if not existing_nm:
                        nm = NickMapping(nick=p.nick,
                                         person_id=p.person_id)
                        db.session.add(nm)

            db.session.add(game_log)
            imported += 1

    db.session.commit()
    return jsonify(
        Message='{} Spiele importiert'.format(imported),
        imported=imported,
        errors=error_list
    ), 200


# --------------- Live Beer Summary (in-game) ---------------

@bp.route('/protokoll/beer_summary_live', methods=['GET'])
def beer_summary_live():
    """Beer summary for the current game evening, using nicks."""
    game_uuid = request.args.get('game_uuid')
    user_nick = request.args.get('user_nick')

    if not game_uuid or not user_nick:
        return jsonify(Message='Parameter fehlen'), 400

    from app.models import Game
    game = Game.query.filter_by(UUID=game_uuid).first()
    if game is None:
        return jsonify(Message='Spiel nicht gefunden'), 404

    game_date = game.started.date() if game.started else None
    if game_date is None:
        return jsonify(opponents=[]), 200

    logs = GameLog.query.filter_by(game_date=game_date).all()

    gives = {}
    gets = {}

    for log in logs:
        loser_nick = None
        winner_nicks = []
        for p in log.players:
            if p.is_loser:
                loser_nick = p.nick
            else:
                winner_nicks.append(p.nick)

        if loser_nick == user_nick:
            for wn in winner_nicks:
                gives[wn] = gives.get(wn, 0) + 1
        elif user_nick in winner_nicks:
            gets[loser_nick] = gets.get(loser_nick, 0) + 1

    all_opponents = set(list(gives.keys()) + list(gets.keys()))
    opponents = []
    for opp in sorted(all_opponents):
        g = gives.get(opp, 0)
        r = gets.get(opp, 0)
        opponents.append({
            'opponent': opp,
            'gives': g,
            'gets': r,
            'diff': r - g
        })

    return jsonify(opponents=opponents, date=game_date.isoformat()), 200


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
