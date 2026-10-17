"""The game state must never be invalid, no matter how the player set changes.

Covers the reported breakages:
  * a player holding a half drops out -> they lose the game, a new one starts
  * a final must never be played by a single player
  * a reconnecting player must not be locked out of the running round
  * joining under a taken nickname waits for an admin instead of failing
"""
import json
from app import app, db
from app.models import Game, GameLog, GameLogPlayer, User, Status

app.app_context().push()
db.create_all()

_seq = [0]


def _game(status=Status.STARTED, names=('ann', 'bob', 'cid'), play_final=True):
    """A running game with distinct player names per test."""
    _seq[0] += 1
    game = Game()
    game.play_final = play_final
    db.session.add(game)
    db.session.commit()
    users = []
    for i, name in enumerate(names):
        user = User()
        user.name = '{}{}'.format(name, _seq[0])
        user.game_id = game.id
        user.turn_order = i
        user.is_admin = (i == 0)
        db.session.add(user)
        users.append(user)
    db.session.commit()
    game.status = status
    game.first_user_id = users[0].id
    game.move_user_id = users[0].id
    game.admin_user_id = users[0].id
    game.player_changes_allowed = True
    db.session.commit()
    return game, users


def _assert_valid(game):
    """The invariants consolidate_game_state() promises."""
    active = game.active_users
    holders = [u for u in active if (u.halfcount or 0) >= 1]
    if game.status in (Status.STARTED, Status.ROUNDFINISCH, Status.PLAYFINAL):
        assert len(active) >= 2, 'running game with less than 2 players'
        ids = [u.id for u in active]
        assert game.first_user_id in ids, 'starter is not in the game'
        assert game.move_user_id == -1 or game.move_user_id in ids, \
            'move pointer is not in the game'
    if game.status == Status.PLAYFINAL:
        assert len(holders) == 2, 'final with {} half holders'.format(len(holders))
        for user in active:
            assert user.passive == ((user.halfcount or 0) < 1)
    elif game.status in (Status.STARTED, Status.ROUNDFINISCH):
        assert game.halfcount == len(holders), \
            'halfcount {} != {} half holders'.format(game.halfcount, len(holders))
    if not game.play_final:
        assert all((u.halfcount or 0) == 0 for u in active)


def _leave(client, game, user, requester=None):
    return client.post(
        '/api/game/{}/user/{}/mark_leave'.format(game.UUID, user.id),
        data=json.dumps({'requester_id': (requester or user).id}),
        content_type='application/json')


# ---------- whoever goes while holding a half, loses the game ----------

def test_half_holder_who_leaves_loses_the_game():
    game, (ann, bob, cid) = _game()
    bob.halfcount = 1
    game.halfcount = 1
    db.session.commit()

    assert _leave(app.test_client(), game, bob).status_code == 200

    assert User.query.get(bob.id) is None
    assert bob.finalcount == 1, 'leaving with a half must count as a lost game'
    # the lost game is in the protocol, with them as the loser
    logged = (GameLogPlayer.query.join(GameLog)
              .filter(GameLog.game_uuid == game.UUID,
                      GameLogPlayer.nick == bob.name).one())
    assert logged.is_loser is True
    # a new game, nobody holds a half any more
    assert game.halfcount == 0
    assert all((u.halfcount or 0) == 0 for u in game.active_users)
    _assert_valid(game)


def test_half_holder_removed_by_admin_loses_the_game():
    game, (ann, bob, cid) = _game()
    bob.halfcount = 1
    game.halfcount = 1
    db.session.commit()

    response = app.test_client().delete(
        '/api/game/{}/user/{}'.format(game.UUID, bob.id))
    assert response.status_code == 200
    assert bob.finalcount == 1
    assert game.halfcount == 0
    _assert_valid(game)


def test_leaving_without_a_half_does_not_end_the_game():
    game, (ann, bob, cid) = _game()
    bob.halfcount = 1
    game.halfcount = 1
    db.session.commit()

    assert _leave(app.test_client(), game, cid).status_code == 200

    assert game.status == Status.STARTED
    assert bob.halfcount == 1, 'an unrelated player leaving must not void a half'
    assert game.halfcount == 1
    _assert_valid(game)


# ---------- a final is never played alone ----------

def test_finalist_leaving_never_leaves_a_one_player_final():
    game, (ann, bob, cid) = _game(status=Status.PLAYFINAL)
    ann.halfcount = 1
    bob.halfcount = 1
    cid.passive = True
    game.halfcount = 0
    db.session.commit()

    assert _leave(app.test_client(), game, bob).status_code == 200

    assert game.status != Status.PLAYFINAL, 'final with one player'
    _assert_valid(game)


def test_newcomer_in_a_final_stays_out_of_it():
    game, (ann, bob, cid) = _game(status=Status.PLAYFINAL)
    ann.halfcount = 1
    bob.halfcount = 1
    cid.passive = True
    db.session.commit()

    response = app.test_client().post(
        '/api/game/{}/user'.format(game.UUID),
        data=json.dumps({'name': 'latecomer{}'.format(_seq[0])}),
        content_type='application/json')
    assert response.status_code == 200

    _assert_valid(game)


def test_game_falls_back_to_waiting_when_too_few_players_remain():
    game, (ann, bob) = _game(names=('ann', 'bob'))
    db.session.commit()

    assert _leave(app.test_client(), game, bob).status_code == 200

    assert game.status == Status.WAITING
    _assert_valid(game)


# ---------- reconnect keeps the seat playable ----------

def test_reconnect_mid_game_stays_an_active_player():
    game, (ann, bob, cid) = _game()
    bob.halfcount = 1
    game.halfcount = 1
    game.player_changes_allowed = False  # somebody already rolled
    db.session.commit()

    response = app.test_client().post(
        '/api/game/{}/user'.format(game.UUID),
        data=json.dumps({'name': bob.name, 'reconnect_id': bob.id}),
        content_type='application/json')
    assert response.status_code == 200
    assert bob.pending_join is False, 'reconnect must not park an active player'
    assert bob.halfcount == 1
    assert bob.id in [u.id for u in game.active_users]
    _assert_valid(game)


# ---------- taken nickname: the admin decides ----------

def test_taken_nickname_asks_an_admin_instead_of_failing():
    game, (ann, bob, cid) = _game()
    client = app.test_client()
    payload = json.dumps({'name': bob.name})  # no reconnect_id: storage lost

    response = client.post('/api/game/{}/user'.format(game.UUID),
                           data=payload, content_type='application/json')
    assert response.status_code == 202
    assert json.loads(response.get_data(as_text=True))['Takeover_Pending'] is True
    assert bob.takeover_state == 'requested'
    assert bob.to_dict()['Takeover_Requested'] is True

    # polling again keeps waiting, it does not pile up requests
    assert client.post('/api/game/{}/user'.format(game.UUID), data=payload,
                       content_type='application/json').status_code == 202

    # admin confirms
    approve = client.post(
        '/api/game/{}/user/{}/takeover'.format(game.UUID, bob.id),
        data=json.dumps({'requester_id': ann.id, 'approve': True}),
        content_type='application/json')
    assert approve.status_code == 200

    # now the joiner gets the seat, with everything that was on it
    response = client.post('/api/game/{}/user'.format(game.UUID),
                           data=payload, content_type='application/json')
    assert response.status_code == 200
    assert bob.takeover_state is None
    assert User.query.filter_by(name=bob.name, game_id=game.id).count() == 1


def test_denied_takeover_tells_the_joiner_to_pick_another_name():
    game, (ann, bob, cid) = _game()
    client = app.test_client()
    payload = json.dumps({'name': bob.name})
    client.post('/api/game/{}/user'.format(game.UUID), data=payload,
                content_type='application/json')
    client.post('/api/game/{}/user/{}/takeover'.format(game.UUID, bob.id),
                data=json.dumps({'requester_id': ann.id, 'approve': False}),
                content_type='application/json')

    response = client.post('/api/game/{}/user'.format(game.UUID), data=payload,
                           content_type='application/json')
    assert response.status_code == 403
    assert bob.takeover_state is None


def test_only_admins_decide_a_takeover():
    game, (ann, bob, cid) = _game()
    client = app.test_client()
    client.post('/api/game/{}/user'.format(game.UUID),
                data=json.dumps({'name': bob.name}),
                content_type='application/json')
    response = client.post(
        '/api/game/{}/user/{}/takeover'.format(game.UUID, bob.id),
        data=json.dumps({'requester_id': cid.id, 'approve': True}),
        content_type='application/json')
    assert response.status_code == 403
    assert bob.takeover_state == 'requested'


def test_last_two_players_and_the_half_holder_leaves():
    game, (ann, bob) = _game(names=('ann', 'bob'))
    bob.halfcount = 1
    game.halfcount = 1
    db.session.commit()

    assert _leave(app.test_client(), game, bob).status_code == 200

    assert bob.finalcount == 1, 'the lost game still counts'
    assert game.status == Status.WAITING
    _assert_valid(game)


def test_rulesets_without_a_final_never_carry_halves():
    game, (ann, bob, cid) = _game(play_final=False)
    bob.halfcount = 1  # left over from a ruleset switch
    game.halfcount = 1
    db.session.commit()

    assert _leave(app.test_client(), game, cid).status_code == 200

    assert game.halfcount == 0
    assert all((u.halfcount or 0) == 0 for u in game.active_users)
    _assert_valid(game)


def test_consolidate_repairs_a_state_that_is_already_broken():
    """Belt and braces: whatever leaves an invalid state behind, the next
    consolidation must straighten it out."""
    from app.api.admin_endpoints import consolidate_game_state
    game, (ann, bob, cid) = _game(status=Status.PLAYFINAL)
    ann.halfcount = 1          # only one half holder in a final
    bob.passive = True
    cid.passive = True
    game.first_user_id = 999999  # pointer to a player who is long gone
    game.move_user_id = 999999
    db.session.commit()

    consolidate_game_state(game)
    db.session.commit()

    assert game.status == Status.STARTED
    _assert_valid(game)


def test_consolidate_promotes_two_half_holders_into_the_final():
    from app.api.admin_endpoints import consolidate_game_state
    game, (ann, bob, cid) = _game(status=Status.STARTED)
    ann.halfcount = 1
    bob.halfcount = 1
    game.halfcount = 2
    db.session.commit()

    consolidate_game_state(game)
    db.session.commit()

    assert game.status == Status.PLAYFINAL
    assert cid.passive is True
    _assert_valid(game)


# ---------- nobody must get stuck on "Spiel ist noch nicht gestartet!" ----------

STUCK = 'Spiel ist noch nicht gestartet!'


def _roll(client, game, user):
    response = client.post(
        '/api/game/{}/user/{}/dice'.format(game.UUID, user.id),
        data=json.dumps({'dice1': 'true', 'dice2': 'true', 'dice3': 'true'}),
        content_type='application/json')
    assert response.status_code != 405, 'roll endpoint moved — test is blind'
    return response


def _message(response):
    assert response.headers['Content-Type'].startswith('application/json'), \
        'expected JSON, got {}'.format(response.status_code)
    return json.loads(response.get_data(as_text=True)).get('Message', '')


def test_the_player_on_turn_can_still_roll_after_a_removal():
    game, (ann, bob, cid) = _game()
    bob.halfcount = 1
    game.halfcount = 1
    db.session.commit()
    client = app.test_client()

    client.delete('/api/game/{}/user/{}'.format(game.UUID, bob.id))

    mover = User.query.get(game.move_user_id)
    assert _message(_roll(client, game, mover)) != STUCK
    _assert_valid(game)


def test_a_fresh_joiner_never_gets_the_not_started_message():
    """The reported dead end: somebody joins and every roll answers
    'Spiel ist noch nicht gestartet!'. A running game must stay rollable."""
    game, (ann, bob, cid) = _game()
    client = app.test_client()
    name = 'joiner{}'.format(_seq[0])

    # mid-round join: parked until the game ends, but the game keeps running
    game.player_changes_allowed = False
    db.session.commit()
    assert client.post('/api/game/{}/user'.format(game.UUID),
                       data=json.dumps({'name': name}),
                       content_type='application/json').status_code == 200

    joiner = User.query.filter_by(name=name, game_id=game.id).first()
    assert joiner.pending_join is True, 'mid-round joiner must be parked'
    assert game.status == Status.STARTED, 'joining must not stop the game'
    # the parked player is told to wait, not that the game has not started
    assert _message(_roll(client, game, joiner)) != STUCK

    # and the players already in the game are unaffected
    mover = User.query.get(game.move_user_id)
    assert _message(_roll(client, game, mover)) != STUCK
    _assert_valid(game)


def test_a_running_game_stays_rollable_through_every_player_change():
    """Walk the reported sequence: half holder removed, rejoins, removed
    again — the game must never sit in a status that refuses every roll."""
    game, (ann, bob, cid, dee) = _game(names=('ann', 'bob', 'cid', 'dee'))
    bob.halfcount = 1
    game.halfcount = 1
    db.session.commit()
    client = app.test_client()
    rollable = (Status.STARTED, Status.PLAYFINAL)

    # 1. admin removes the half holder -> he lost the game, a new one runs
    client.delete('/api/game/{}/user/{}'.format(game.UUID, bob.id))
    assert game.status in rollable
    _assert_valid(game)

    # 2. he comes back under the same name, storage lost -> admin confirms
    payload = json.dumps({'name': bob.name})
    assert client.post('/api/game/{}/user'.format(game.UUID), data=payload,
                       content_type='application/json').status_code == 200
    back = User.query.filter_by(name=bob.name, game_id=game.id).first()
    assert game.status in rollable
    _assert_valid(game)

    # 3. and out again
    client.delete('/api/game/{}/user/{}'.format(game.UUID, back.id))
    assert game.status in rollable
    mover = User.query.get(game.move_user_id)
    assert _message(_roll(client, game, mover)) != STUCK
    _assert_valid(game)


def test_random_player_changes_never_produce_an_invalid_state():
    """Throw joins, leaves and admin removals at a running game in random
    order. After every single change the state must be valid, and the game
    must be either rollable or back in the lobby — never stuck in a status
    that answers every roll with 'Spiel ist noch nicht gestartet!'.
    """
    import random
    random.seed(20261017)
    client = app.test_client()
    game, users = _game(names=('f1', 'f2', 'f3', 'f4'))
    admin = users[0]
    joined = 0

    for step in range(120):
        present = game.active_users
        action = random.choice(['join', 'leave', 'kick', 'half', 'final'])

        if action == 'join':
            joined += 1
            client.post('/api/game/{}/user'.format(game.UUID),
                        data=json.dumps({'name': 'fz{}_{}'.format(_seq[0], joined)}),
                        content_type='application/json')
        elif action in ('leave', 'kick') and len(present) > 1:
            victim = random.choice(present)
            if victim.is_admin and sum(1 for u in present if u.is_admin) < 2:
                continue  # the last admin cannot go, by design
            if action == 'leave':
                _leave(client, game, victim, requester=victim)
            else:
                client.delete('/api/game/{}/user/{}'.format(game.UUID, victim.id))
        elif action == 'half' and game.status == Status.STARTED:
            # hand somebody a half, as a finished round would
            free = [u for u in present if (u.halfcount or 0) == 0]
            if free and not [u for u in present if (u.halfcount or 0) >= 1]:
                free[0].halfcount = 1
                game.halfcount = 1
                db.session.commit()
        elif action == 'final' and game.status == Status.STARTED:
            free = [u for u in present if (u.halfcount or 0) == 0]
            if len(free) >= 2:
                free[0].halfcount = 1
                free[1].halfcount = 1
                from app.api.admin_endpoints import consolidate_game_state
                consolidate_game_state(game)
                db.session.commit()

        _assert_valid(game)
        assert game.status in (Status.STARTED, Status.PLAYFINAL, Status.WAITING), \
            'step {}: game parked in {}'.format(step, game.status)

        if game.status == Status.WAITING and len(game.active_users) >= 2:
            # an admin restarts it, and play goes on
            response = client.post(
                '/api/game/{}/start'.format(game.UUID),
                data=json.dumps({'admin_id': [u.id for u in game.active_users
                                               if u.is_admin][0]}),
                content_type='application/json')
            assert response.status_code == 201
            _assert_valid(game)

        if game.status in (Status.STARTED, Status.PLAYFINAL):
            mover = User.query.get(game.move_user_id)
            if mover is not None and not mover.passive:
                assert _message(_roll(client, game, mover)) != STUCK, \
                    'step {}: game refuses every roll'.format(step)

        if not any(u.is_admin for u in game.active_users):
            break  # no admin left to drive the game
