"""Known players (= a Person behind the nick) keep their ruleset vote
across games: casting a vote stores it on the Person, joining restores it.
"""
import json
from app import app, db
from app.models import Game, Person, NickMapping, User

app.app_context().push()
db.create_all()


def _known_player(nick, remembered_vote=None):
    person = Person(name='Person ' + nick)
    person.ruleset_vote = remembered_vote
    db.session.add(person)
    db.session.commit()
    db.session.add(NickMapping(nick=nick, person_id=person.id))
    db.session.commit()
    return person


def _new_game():
    game = Game()
    db.session.add(game)
    db.session.commit()
    return game.UUID


def _join(client, gid, name):
    return client.post('/api/game/{}/user'.format(gid),
                       data=json.dumps({'name': name}),
                       content_type='application/json')


def test_known_player_gets_remembered_vote_on_join():
    person = _known_player('persist_known', 'nutte_15')
    gid = _new_game()  # game itself runs jule_13
    assert _join(app.test_client(), gid, 'persist_known').status_code == 200
    user = User.query.filter_by(name='persist_known').first()
    assert user.ruleset_vote == 'nutte_15'


def test_unknown_player_votes_for_current_ruleset():
    gid = _new_game()
    assert _join(app.test_client(), gid, 'persist_stranger').status_code == 200
    user = User.query.filter_by(name='persist_stranger').first()
    assert user.ruleset_vote == 'jule_13'


def test_vote_is_stored_on_the_person():
    person = _known_player('persist_voter')
    gid = _new_game()
    client = app.test_client()
    _join(client, gid, 'persist_voter')
    user = User.query.filter_by(name='persist_voter').first()
    response = client.post(
        '/api/game/{}/vote_ruleset'.format(gid),
        data=json.dumps({'voter_id': user.id, 'ruleset_id': 'classic_13'}),
        content_type='application/json')
    assert response.status_code == 200
    assert Person.query.get(person.id).ruleset_vote == 'classic_13'
