"""Admins verteilen Strafen ("Einwuerfeln") und nehmen sie zurueck."""
import json
from app import app, db
from app.models import Game, User, Status

app.app_context().push()
db.create_all()


def _make_game():
    game = Game()
    db.session.add(game)
    db.session.commit()
    users = []
    for i, name in enumerate(['pen_admin', 'pen_player']):
        user = User()
        user.name = name
        user.game_id = game.id
        user.turn_order = i
        user.is_admin = (i == 0)
        db.session.add(user)
        users.append(user)
    db.session.commit()
    game.first_user_id = users[0].id
    game.move_user_id = users[0].id
    game.admin_user_id = users[0].id
    game.status = Status.STARTED
    db.session.commit()
    return game.UUID, users[0].id, users[1].id


def _post(client, gid, uid, requester_id, delta):
    return client.post(
        '/api/game/{}/user/{}/penalty'.format(gid, uid),
        data=json.dumps({'requester_id': requester_id, 'delta': delta}),
        content_type='application/json')


def test_admin_gives_and_revokes_penalty():
    gid, admin_id, victim_id = _make_game()
    client = app.test_client()

    assert _post(client, gid, victim_id, admin_id, 1).status_code == 200
    assert User.query.get(victim_id).penalty_count == 1

    assert _post(client, gid, victim_id, admin_id, 1).status_code == 200
    assert User.query.get(victim_id).penalty_count == 2

    assert _post(client, gid, victim_id, admin_id, -1).status_code == 200
    assert User.query.get(victim_id).penalty_count == 1


def test_penalty_never_goes_below_zero():
    gid, admin_id, victim_id = _make_game()
    client = app.test_client()
    response = _post(client, gid, victim_id, admin_id, -1)
    assert response.status_code == 400
    assert User.query.get(victim_id).penalty_count == 0


def test_only_admins_may_give_penalties():
    gid, admin_id, victim_id = _make_game()
    client = app.test_client()
    response = _post(client, gid, admin_id, victim_id, 1)
    assert response.status_code == 403
    assert User.query.get(admin_id).penalty_count == 0
