"""The protocol page lives at /protokoll, a name that is easy to forget.
Every alias we promise must actually land there — a route collision would
otherwise turn one into a silent 404.
"""
from app import app
from app.routes import protokoll_alias  # noqa: F401 — must stay importable


def test_every_alias_redirects_to_protokoll():
    client = app.test_client()
    aliases = [rule.rule for rule in app.url_map.iter_rules()
               if rule.endpoint == 'protokoll_alias']
    assert len(aliases) >= 10, 'aliases were lost'
    for path in aliases:
        response = client.get(path)
        assert response.status_code == 302, '{} -> {}'.format(path, response.status_code)
        assert response.headers['Location'].endswith('/protokoll'), path


def test_protokoll_itself_still_renders():
    assert app.test_client().get('/protokoll').status_code == 200
