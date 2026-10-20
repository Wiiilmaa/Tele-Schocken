---
title: "Spielerliste aendern: Zustands-Invarianten und die SQLAlchemy-Falle dahinter"
author: Wiiilmaa
date: 2026-10-17
branch: step_up
cost: { minutes: 1, tokens: 0 }
touches:
  - backend/app/api/admin_endpoints.py
  - backend/app/api/game_endpoints.py
  - backend/app/models.py
  - backend/app/routes.py
  - backend/app/static/scripts/adminpanel.js
  - backend/app/static/styles/dice.css
  - backend/app/templates/game.html
  - backend/app/templates/gameplay.html
  - backend/tests/test_leave.py
  - backend/migrations/versions/i9d0e1f2a3b4_add_user_takeover_state.py
---

## Decided

Jede Aenderung der Spielerliste laeuft durch `remove_player()` /
`consolidate_game_state()` in `backend/app/api/admin_endpoints.py`. Wer direkt
`db.session.delete(user)` in einem Endpoint schreibt, baut die naechste
Sackgasse. Die vier Invarianten stehen im Docstring von
`consolidate_game_state`.

Spielregel mit dem Nutzer geklaert: wer mit einer Haelfte das Spiel verlaesst,
**verliert das Spiel** (`finalcount +1` *und* `log_game_result` ins Protokoll),
danach startet ein neues. Das ist bewusst der bestehende GAMEFINISCH-Pfad
(`execute_deferred_actions`), nicht eine eigene Sonderbehandlung.

Halb/Finale-Modell, nicht offensichtlich: `game.halfcount` wird beim Start des
Finales auf 0 zurueckgesetzt. Die Invariante im Finale ist deshalb "genau zwei
User mit `halfcount == 1`", **nicht** `game.halfcount == 2`.

## Tried and ruled out

`db.session.add(game)` nach `db.session.delete(child)` + `flush()`: das `add()`
kaskadiert (save-update) auf `game.users`, wo das geflushte Objekt noch steht →
`InvalidRequestError: Instance has been deleted`. Das `add()` ist ohnehin
ueberfluessig (game haengt schon in der Session). Wer nach einem Delete noch
`game.users` liest, braucht `db.session.expire(game, ['users'])` — siehe
`_drop_user()`; flush allein raeumt die Collection nicht.

Beim Reconnect `pending_join = True` zu setzen (alter Stand in
`set_game_user`): nimmt einen Spieler mitten aus der laufenden Runde, Haelfte
bleibt sichtbar, aber kein Zug. War die Ursache von "kann nicht wuerfeln".
Ein zurueckgegebener Platz wird nie geparkt → `_take_seat_back()`.

## Watch out

`app/errors.py` rendert fuer 404/500 HTML-Templates — **auch unter `/api/`**.
Jeder Serverfehler kommt im Frontend als generisches `alert('Fehler')` an, weil
`JSON.parse` scheitert. "Nur Fehler angezeigt" heisst also: 500 oder 404 suchen,
nicht die Meldung.

Die Wuerfel-Route ist `POST /api/game/<gid>/user/<uid>/dice`, nicht `/roll`.
Ein Test gegen `/roll` bekommt 405 mit HTML-Body und laeuft still ins Leere.

Tests brauchen `TELESCHOCKEN_CONFIG_FILE`; `tests/__init__.py` importiert
zusaetzlich ein `config.py` im backend-Verzeichnis (gitignored, nicht im Repo).
`tests/test_routes.py` scheitert mit 3 Tests bereits auf master (veraltete
Asserts: `data['Admin']` statt `Admins`, `b'Tele-Schocken Beta'`) — kein
Regressionssignal.

Python 3.14 + SQLAlchemy 2.0.22 (requirements.txt) bricht beim Import;
lokal mit python3.11 arbeiten.
