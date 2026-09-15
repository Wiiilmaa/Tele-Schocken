"""Runnable without a DB: vote counting + winner determination."""
import importlib.util
import os

# load rulesets.py directly: no Flask/DB needed for this logic
_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'app', 'rulesets.py')
_spec = importlib.util.spec_from_file_location('rulesets', _path)
rulesets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rulesets)
count_votes = rulesets.count_votes
calculate_winning_ruleset = rulesets.calculate_winning_ruleset


class _U(object):
    def __init__(self, vote, pending_join=False, leave_after_game=False):
        self.ruleset_vote = vote
        self.pending_join = pending_join
        self.leave_after_game = leave_after_game


def test_count_votes_ignores_pending_and_leaving():
    users = [_U('a'), _U('b'), _U('b', pending_join=True),
             _U('b', leave_after_game=True), _U(None)]
    assert count_votes(users) == {'a': 1, 'b': 1}


def test_leaving_player_does_not_decide_next_ruleset():
    # 'jule_13' is current; two leavers want 'classic_13' -> no change once they left
    users = [_U('jule_13'), _U('classic_13', leave_after_game=True),
             _U('classic_13', leave_after_game=True)]
    assert calculate_winning_ruleset(count_votes(users), 'jule_13') is None


def test_majority_changes_ruleset():
    users = [_U('jule_13'), _U('classic_13'), _U('classic_13')]
    assert calculate_winning_ruleset(count_votes(users), 'jule_13') == 'classic_13'


if __name__ == '__main__':
    test_count_votes_ignores_pending_and_leaving()
    test_leaving_player_does_not_decide_next_ruleset()
    test_majority_changes_ruleset()
    print('ok')
