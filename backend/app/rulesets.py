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


def reload_rulesets():
    """Force reload of rulesets from disk (for future admin UI)."""
    global _rulesets_cache
    _rulesets_cache = None
    return _load_rulesets()
