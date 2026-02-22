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
import json
import re
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
        row = [game.game_date.strftime('%Y%m%d'), loser] + sorted(winners)
        writer.writerow(row)

    today_str = datetime.now(BERLIN_TZ).strftime('%Y%m%d')
    resp = Response(output.getvalue(), mimetype='text/csv')
    resp.headers['Content-Disposition'] = \
        'attachment; filename=schocken_protokoll_{}.csv'.format(today_str)
    return resp


# --------------- CSV Import ---------------

@bp.route('/protokoll/import', methods=['POST'])
def import_csv():
    if not _check_protokoll_auth():
        return _auth_error()

    data = request.get_json() or {}
    csv_text = data.get('csv', '')
    dry_run = data.get('dry_run', False)
    create_persons_list = data.get('create_persons', [])

    if not csv_text:
        return jsonify(Message='Keine Daten'), 400

    # Auto-create requested persons before import
    if create_persons_list and not dry_run:
        for pname in create_persons_list:
            pname = pname.strip()
            if pname and not Person.query.filter_by(name=pname).first():
                db.session.add(Person(name=pname))
        db.session.flush()

    reader = csv.reader(io.StringIO(csv_text), delimiter=';',
                        quotechar='"', quoting=csv.QUOTE_ALL)
    person_by_name = {p.name: p for p in Person.query.all()}
    importable = 0
    errors = []
    unknown_names = set()

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
            game_date = datetime.strptime(date_str, '%Y%m%d').date()
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

        all_names = [loser_name] + winner_names
        for n in all_names:
            if n not in person_by_name:
                unknown_names.add(n)

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
    return jsonify(Message=msg, imported=importable, errors=errors,
                   unknown_persons=sorted(unknown_names)), 200


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
    create_persons_list = data.get('create_persons', [])

    if not text:
        return jsonify(Message='Keine Daten'), 400

    results, parse_errors = _parse_md_import(text)
    error_list = [{'line': e[0], 'text': e[1], 'error': e[2]}
                  for e in parse_errors]

    importable = sum(count for _, _, count, _ in results)

    # Collect unknown person names
    person_by_name = {p.name: p for p in Person.query.all()}
    unknown_names = set()
    for _, loser, _, winners in results:
        for n in [loser] + winners:
            if n not in person_by_name:
                unknown_names.add(n)

    if dry_run or (not results and parse_errors):
        msg = '{} Spiele importierbar'.format(importable) if results \
            else 'Keine Spiele erkannt'
        return jsonify(Message=msg, imported=importable,
                       errors=error_list,
                       unknown_persons=sorted(unknown_names)), 200

    # Auto-create requested persons before import
    if create_persons_list:
        for pname in create_persons_list:
            pname = pname.strip()
            if pname and not Person.query.filter_by(name=pname).first():
                db.session.add(Person(name=pname))
        db.session.flush()
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
        errors=error_list,
        unknown_persons=sorted(unknown_names)
    ), 200


# --------------- Backup ---------------

@bp.route('/protokoll/backup', methods=['GET'])
def backup_data():
    if not _check_protokoll_auth():
        return _auth_error()

    persons = Person.query.order_by(Person.id).all()
    nick_mappings = NickMapping.query.order_by(NickMapping.id).all()
    game_logs = GameLog.query.order_by(GameLog.game_date, GameLog.id).all()

    min_date = None
    max_date = None
    games_data = []
    for gl in game_logs:
        d = gl.game_date.isoformat() if gl.game_date else None
        if d:
            if min_date is None or d < min_date:
                min_date = d
            if max_date is None or d > max_date:
                max_date = d
        players = []
        for p in gl.players:
            players.append({
                'nick': p.nick,
                'is_loser': p.is_loser,
                'person_id': p.person_id
            })
        games_data.append({
            'game_uuid': gl.game_uuid,
            'game_date': d,
            'created_at': gl.created_at.isoformat() if gl.created_at else None,
            'mapping_complete': gl.mapping_complete,
            'players': players
        })

    backup = {
        'version': 1,
        'created_at': datetime.now(BERLIN_TZ).isoformat(),
        'date_from': min_date,
        'date_to': max_date,
        'persons': [{'id': p.id, 'name': p.name} for p in persons],
        'nick_mappings': [{'nick': nm.nick, 'person_id': nm.person_id}
                          for nm in nick_mappings],
        'game_logs': games_data
    }

    today_str = datetime.now(BERLIN_TZ).strftime('%Y%m%d')
    resp = Response(json.dumps(backup, ensure_ascii=False, indent=2),
                    mimetype='application/json')
    resp.headers['Content-Disposition'] = \
        'attachment; filename=schocken_backup_{}.json'.format(today_str)
    return resp


# --------------- Restore ---------------

@bp.route('/protokoll/restore', methods=['POST'])
def restore_data():
    if not _check_protokoll_auth():
        return _auth_error()

    data = request.get_json() or {}
    backup = data.get('backup')
    dry_run = data.get('dry_run', False)

    if not backup or not isinstance(backup, dict):
        return jsonify(Message='Ungültiges Backup-Format'), 400

    if backup.get('version') != 1:
        return jsonify(Message='Unbekannte Backup-Version'), 400

    date_from = backup.get('date_from')
    date_to = backup.get('date_to')
    persons_data = backup.get('persons', [])
    nick_mappings_data = backup.get('nick_mappings', [])
    game_logs_data = backup.get('game_logs', [])

    info = {
        'date_from': date_from,
        'date_to': date_to,
        'persons_count': len(persons_data),
        'nick_mappings_count': len(nick_mappings_data),
        'game_logs_count': len(game_logs_data),
        'games_to_delete': 0
    }

    if date_from and date_to:
        df = datetime.strptime(date_from, '%Y-%m-%d').date()
        dt = datetime.strptime(date_to, '%Y-%m-%d').date()
        existing = GameLog.query.filter(
            GameLog.game_date >= df, GameLog.game_date <= dt).count()
        info['games_to_delete'] = existing

    if dry_run:
        return jsonify(Message='Restore-Vorschau', info=info), 200

    # Delete existing data in the date range
    if date_from and date_to:
        df = datetime.strptime(date_from, '%Y-%m-%d').date()
        dt = datetime.strptime(date_to, '%Y-%m-%d').date()
        logs_to_del = GameLog.query.filter(
            GameLog.game_date >= df, GameLog.game_date <= dt).all()
        for log in logs_to_del:
            db.session.delete(log)
        db.session.flush()

    # Restore persons (create missing ones, build id mapping)
    old_to_new_person = {}
    for pd in persons_data:
        existing = Person.query.filter_by(name=pd['name']).first()
        if existing:
            old_to_new_person[pd['id']] = existing.id
        else:
            new_p = Person(name=pd['name'])
            db.session.add(new_p)
            db.session.flush()
            old_to_new_person[pd['id']] = new_p.id

    # Restore nick mappings
    for nmd in nick_mappings_data:
        new_pid = old_to_new_person.get(nmd['person_id'])
        if not new_pid:
            continue
        existing = NickMapping.query.filter_by(nick=nmd['nick']).first()
        if existing:
            existing.person_id = new_pid
        else:
            nm = NickMapping(nick=nmd['nick'], person_id=new_pid)
            db.session.add(nm)

    # Restore game logs
    restored = 0
    for gld in game_logs_data:
        gl = GameLog()
        gl.game_uuid = gld.get('game_uuid', 'restore')
        gl.game_date = datetime.strptime(
            gld['game_date'], '%Y-%m-%d').date() if gld.get(
                'game_date') else None
        gl.created_at = datetime.fromisoformat(
            gld['created_at']) if gld.get('created_at') else datetime.now(
                BERLIN_TZ)
        gl.mapping_complete = gld.get('mapping_complete', False)

        for pld in gld.get('players', []):
            glp = GameLogPlayer()
            glp.nick = pld['nick']
            glp.is_loser = pld['is_loser']
            old_pid = pld.get('person_id')
            glp.person_id = old_to_new_person.get(old_pid) if old_pid else None
            gl.players.append(glp)

        gl.mapping_complete = all(
            p.person_id is not None for p in gl.players)
        db.session.add(gl)
        restored += 1

    db.session.commit()
    return jsonify(
        Message='{} Spiele wiederhergestellt'.format(restored),
        restored=restored
    ), 200


# --------------- Live Beer Summary (in-game) ---------------

@bp.route('/protokoll/beer_summary_live', methods=['GET'])
def beer_summary_live():
    """Beer summary for the current game evening, using nicks.
    Also returns person-based historical stats if the user is mapped."""
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

    result = {'opponents': opponents, 'date': game_date.isoformat()}

    # Check if user has a person mapping for this game evening
    nm = NickMapping.query.filter_by(nick=user_nick).first()
    person_id = nm.person_id if nm else None

    # Also check GameLogPlayer mapping on this date
    if not person_id:
        player_entry = GameLogPlayer.query.join(GameLog).filter(
            GameLog.game_date == game_date,
            GameLogPlayer.nick == user_nick,
            GameLogPlayer.person_id.isnot(None)
        ).first()
        if player_entry:
            person_id = player_entry.person_id

    if person_id:
        person = Person.query.get(person_id)
        if person:
            result['person_name'] = person.name
            result['person_id'] = person_id

            # Get all complete game logs where person participated
            all_logs = GameLog.query.filter_by(
                mapping_complete=True
            ).filter(
                GameLog.players.any(GameLogPlayer.person_id == person_id)
            ).order_by(GameLog.game_date).all()

            if all_logs:
                # Build per-year stats
                years = set()
                for gl in all_logs:
                    if gl.game_date:
                        years.add(gl.game_date.year)

                years = sorted(years)
                result['year_range'] = {
                    'first': years[0],
                    'last': years[-1]
                }

                def compute_beer(game_list, pid):
                    beer = {}
                    all_pids = set()
                    for gl in game_list:
                        loser_pid = None
                        winner_pids = []
                        for p in gl.players:
                            if p.person_id:
                                all_pids.add(p.person_id)
                            if p.is_loser:
                                loser_pid = p.person_id
                            else:
                                winner_pids.append(p.person_id)
                        if loser_pid == pid:
                            for wp in winner_pids:
                                if wp:
                                    beer.setdefault(wp, {'gives': 0, 'gets': 0})['gives'] += 1
                        elif pid in winner_pids:
                            if loser_pid:
                                beer.setdefault(loser_pid, {'gives': 0, 'gets': 0})['gets'] += 1
                    return beer, all_pids

                person_map = {}
                all_pid_set = set()

                # Overall
                overall_beer, pids = compute_beer(all_logs, person_id)
                all_pid_set.update(pids)

                # Per year
                year_beers = {}
                for yr in years:
                    yr_logs = [gl for gl in all_logs
                               if gl.game_date and gl.game_date.year == yr]
                    yr_beer, pids = compute_beer(yr_logs, person_id)
                    all_pid_set.update(pids)
                    year_beers[yr] = yr_beer

                for pid_val in all_pid_set:
                    p = Person.query.get(pid_val)
                    if p:
                        person_map[pid_val] = p.name

                def format_opponents(beer_dict):
                    opps = []
                    for opp_id, counts in beer_dict.items():
                        if opp_id not in person_map or opp_id == person_id:
                            continue
                        opps.append({
                            'opponent': person_map[opp_id],
                            'gives': counts['gives'],
                            'gets': counts['gets'],
                            'diff': counts['gets'] - counts['gives']
                        })
                    opps.sort(key=lambda x: x['opponent'])
                    return opps

                result['overall'] = format_opponents(overall_beer)
                result['per_year'] = {}
                for yr in years:
                    yr_opps = format_opponents(year_beers[yr])
                    if yr_opps:
                        result['per_year'][yr] = yr_opps

    return jsonify(result), 200


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
