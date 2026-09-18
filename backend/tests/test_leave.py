"""Spieler verlassen das Spiel — die Antwort muss immer JSON sein.

Regression: nach dem Flush des geloeschten Users kaskadierte
db.session.add(game) auf game.users und warf InvalidRequestError
("Instance <User> has been deleted") -> HTML-500 -> Frontend zeigte "Fehler".
"""
import json
from app import app, db
from app.models import Game, User, Status

app.app_context().push()
db.create_all()


def _make_game(player_changes_allowed=True):
    game = Game()
    db.session.add(game)
    db.session.commit()
    users = []
    for i, name in enumerate(['leave_a', 'leave_b', 'leave_c']):
        user = User()
        user.name = name
        user.game_id = game.id
        user.turn_order = i
        user.is_admin = (i == 0)
        user.ruleset_vote = 'classic_13' if i else None
        db.session.add(user)
        users.append(user)
    db.session.commit()
    game.first_user_id = users[0].id
    game.move_user_id = users[0].id
    game.admin_user_id = users[0].id
    game.status = Status.STARTED
    game.player_changes_allowed = player_changes_allowed
    db.session.commit()
    return game.UUID, users[0].id, users[1].id


def _post_leave(client, gid, uid, requester_id):
    return client.post(
        '/api/game/{}/user/{}/mark_leave'.format(gid, uid),
        data=json.dumps({'requester_id': requester_id}),
        content_type='application/json')


def test_leave_immediately():
    gid, admin_id, victim_id = _make_game()
    client = app.test_client()
    response = _post_leave(client, gid, victim_id, victim_id)
    assert response.status_code == 200
    assert json.loads(response.get_data(as_text=True))['Message']
    assert User.query.get(victim_id) is None


def test_admin_marks_other_player_leaving():
    gid, admin_id, victim_id = _make_game()
    client = app.test_client()
    response = _post_leave(client, gid, victim_id, admin_id)
    assert response.status_code == 200
    assert User.query.get(victim_id) is None


def test_leave_deferred_while_game_running():
    gid, admin_id, victim_id = _make_game(player_changes_allowed=False)
    client = app.test_client()
    response = _post_leave(client, gid, victim_id, victim_id)
    assert response.status_code == 200
    assert User.query.get(victim_id).leave_after_game is True


def test_admin_deletes_player():
    gid, admin_id, victim_id = _make_game()
    client = app.test_client()
    response = client.delete('/api/game/{}/user/{}'.format(gid, victim_id))
    assert response.status_code == 200
    assert json.loads(response.get_data(as_text=True))['Message'] == 'success'
    assert User.query.get(victim_id) is None
