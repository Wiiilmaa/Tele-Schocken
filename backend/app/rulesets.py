"""
rulesets.py
====================================
Loads and manages game rulesets from rulesets.json.
Each ruleset defines chip count, finale mode, and scoring rules.
"""
import json
import os

_rulesets_cache = None


def _load_rulesets():
    """Load rulesets from JSON file and cache them."""
    global _rulesets_cache
    if _rulesets_cache is not None:
        return _rulesets_cache

    json_path = os.path.join(os.path.dirname(__file__), 'rulesets.json')
    with open(json_path, 'r', encoding='utf-8') as f:
        _rulesets_cache = json.load(f)
    return _rulesets_cache


def get_all_rulesets():
    """Return all available rulesets (summary: id, name, stack_max, play_final)."""
    rulesets = _load_rulesets()
    return [{
        'id': r['id'],
        'name': r['name'],
        'stack_max': r['stack_max'],
        'play_final': r['play_final'],
        'rule_count': len(r['rules']),
    } for r in rulesets]


def get_ruleset(ruleset_id):
    """Return a single ruleset by ID, or None if not found."""
    rulesets = _load_rulesets()
    for r in rulesets:
        if r['id'] == ruleset_id:
            return r
    return None


def get_complete_rules(ruleset):
    """
    Take a ruleset's explicit rules and append auto-generated 'Schrott' entries
    for all 3-dice combinations not already listed. Schrott always costs 1 chip.
    Returns the complete ordered rule list.
    """
    explicit_rules = list(ruleset['rules'])
    explicit_dice = {r['dice'] for r in explicit_rules}

    # Generate all possible 3-dice combinations (sorted descending)
    for i in range(6, 0, -1):
        for j in range(i, 0, -1):
            for k in range(j, 0, -1):
                dice_val = i * 100 + j * 10 + k
                if dice_val not in explicit_dice:
                    explicit_rules.append({
                        'dice': dice_val,
                        'name': 'Schrott ({})'.format(dice_val),
                        'chips': 1,
                    })

    return explicit_rules


def calculate_winning_ruleset(vote_counts, current_ruleset_id):
    """
    Given vote_counts dict {ruleset_id: count} and the current ruleset_id,
    determine if a different ruleset should replace the current one.

    The current ruleset has "home advantage": it only gets replaced when
    at least one other ruleset has strictly MORE raw votes.  The tiebreaker
    (+0.5 for play_final, +0–0.4 for explicit rule count) only decides
    among challengers that share the highest raw vote count.

    Returns the winning ruleset_id, or None to keep the current one.
    """
    if not vote_counts:
        return None

    current_votes = vote_counts.get(current_ruleset_id, 0)

    # Find the highest raw vote count among OTHER rulesets
    max_other_votes = 0
    for rid, count in vote_counts.items():
        if rid != current_ruleset_id and count > max_other_votes:
            max_other_votes = count

    # Current ruleset stays unless another has strictly more raw votes
    if max_other_votes <= current_votes:
        return None

    # Collect all challengers tied at the top raw vote count
    challengers = [rid for rid, count in vote_counts.items()
                   if rid != current_ruleset_id and count == max_other_votes]

    if len(challengers) == 1:
        return challengers[0]

    # Tiebreaker among challengers: +0.5 finale, +0–0.4 rule count
    rulesets = _load_rulesets()
    ruleset_map = {r['id']: r for r in rulesets}

    rule_counts = [len(r['rules']) for r in rulesets]
    min_rules = min(rule_counts)
    max_rules = max(rule_counts)
    rule_range = max_rules - min_rules if max_rules > min_rules else 1

    def tiebreak_score(rid):
        rs = ruleset_map.get(rid)
        if rs is None:
            return 0
        score = 0.0
        if rs.get('play_final'):
            score += 0.5
        score += (len(rs['rules']) - min_rules) / rule_range * 0.4
        return score

    return max(challengers, key=tiebreak_score)


def reload_rulesets():
    """Force reload of rulesets from disk (for future admin UI)."""
    global _rulesets_cache
    _rulesets_cache = None
    return _load_rulesets()
