from flask import render_template, redirect, url_for

from app import app, db
from app.forms import CreateGameFrom
from app.models import Game


@app.route('/index2')
def index2():
    return render_template('index2.html')


@app.route('/')
@app.route('/index', methods=['GET', 'POST'])
def index():
    form = CreateGameFrom()
    if form.validate_on_submit():
        game = Game()
        db.session.add(game)
        db.session.commit()
        next_page = url_for('game')
        next_page = url_for('game', variable=game.UUID)
        return redirect(next_page)
    return render_template('index.html', title='Home', form=form)


@app.route('/game_waiting/<gid>', methods=['GET'])
def game(gid):
    game = Game.query.filter_by(UUID=gid).first()
    if game is None:
        return render_template('404.html')
    return render_template('game.html', title='Spiel starten', game=game)


@app.route('/game/<gid>', methods=['GET', 'POST'])
def game_play(gid):
    game = Game.query.filter_by(UUID=gid).first()
    if game is None:
        return render_template('404.html')
    return render_template('gameplay.html', title='Schocken', game=game)


@app.route('/protokoll')
def protokoll():
    return render_template('protokoll.html', title='Protokoll')


def protokoll_alias():
    return redirect(url_for('protokoll'))


# /protokoll is a name that is easy to forget — let the obvious guesses in too
for _alias in ('statistik', 'statistics', 'statistic', 'stats', 'stat',
               'admin', 'protocol', 'protokol', 'auswertung', 'log'):
    app.add_url_rule('/' + _alias, 'protokoll_alias', protokoll_alias)
    app.add_url_rule('/' + _alias + '/', 'protokoll_alias', protokoll_alias)
