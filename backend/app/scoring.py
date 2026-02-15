"""
scoring.py
====================================
Server-side scoring logic for Schocken.
Determines High/Low players and chip transfers based on the game's active ruleset.
"""
from app.rulesets import get_ruleset, get_complete_rules


def get_dice_value(user):
    """
    Sort a user's 3 dice descending and return as a 3-digit integer.
    E.g. dice 4,2,1 -> 421; dice 6,1,1 -> 611
    Returns 0 if dice are not complete.
    """
    d1 = user.dice1
    d2 = user.dice2
    d3 = user.dice3
    if d1 is None or d2 is None or d3 is None:
        return 0
    if d1 == 0 or d2 == 0 or d3 == 0:
        return 0
    values = sorted([d1, d2, d3], reverse=True)
    return values[0] * 100 + values[1] * 10 + values[2]


def get_scoring(dice_value, complete_rules):
    """
    Look up a dice value in the complete rule list.
    Returns dict with 'order' (index in list), 'chips', 'name'.
    Lower order = better hand.
    """
    for i, rule in enumerate(complete_rules):
        if rule['dice'] == dice_value:
            return {
                'order': i,
                'chips': rule['chips'],
                'name': rule['name'],
            }
    # Should never happen if complete_rules includes all combos
    return {
        'order': 99999,
        'chips': 0,
        'name': 'Unbekannt ({})'.format(dice_value),
    }


def _matched_suffix(matched):
    """Return the display suffix for the 'matched' (nachgelegt) count.
    0 -> '', 1 -> ' nachgelegt', 2 -> ' doppelt nachgelegt',
    3 -> ' dreifach nachgelegt', etc.
    """
    if matched == 0:
        return ''
    if matched == 1:
        return ' nachgelegt'
    prefixes = {
        2: 'doppelt',
        3: 'dreifach',
        4: 'vierfach',
        5: 'fünffach',
        6: 'sechsfach',
        7: 'siebenfach',
        8: 'achtfach',
        9: 'neunfach',
        10: 'zehnfach',
        11: 'elffach',
        12: 'zwölffach',
        13: 'dreizehnfach',
        14: 'vierzehnfach',
        15: 'fünfzehnfach',
        16: 'sechzehnfach',
        17: 'siebzehnfach',
        18: 'achtzehnfach',
        19: 'neunzehnfach',
        20: 'zwanzigfach',
    }
    prefix = prefixes.get(matched, '{}fach'.format(matched))
    return ' {} nachgelegt'.format(prefix)


def _format_result(entry):
    """Format a player's result line including matched suffix."""
    suffix = _matched_suffix(entry['matched'])
    return '{} mit {} im {}. Wurf{}'.format(
        entry['name'], entry['scoring']['name'], entry['number_dice'], suffix)


def calculate_scoring(game):
    """
    Calculate the scoring for a completed round.
    Returns a dict with High, Low, Chips, From, From_Name, To, To_Name.
    """
    # Load the ruleset for this game
    ruleset = get_ruleset(game.ruleset_id) if game.ruleset_id else None
    if ruleset is None:
        # Fallback: use classic ruleset
        ruleset = get_ruleset('classic_13')
    if ruleset is None:
        return None

    complete_rules = get_complete_rules(ruleset)

    # Build list of playing users, ordered starting from first_user_id
    active = game.active_users
    playing = [u for u in active if not u.passive]

    if len(playing) < 2:
        return None

    # Find first_user index
    first_index = -1
    for i, u in enumerate(playing):
        if u.id == game.first_user_id:
            first_index = i
            break

    if first_index == -1:
        # first_user might be passive; use first playing user
        first_index = 0

    # Reorder starting from first_user, track seat position (i)
    # Compute 'matched' field: 0 for the first player, then incremented
    # when the current player has the same dice result and throw count
    # as the predecessor (i.e. "nachgelegt").
    ordered = []
    for i in range(len(playing)):
        idx = (first_index + i) % len(playing)
        u = playing[idx]
        dice_val = get_dice_value(u)
        scoring = get_scoring(dice_val, complete_rules)
        matched = 0
        if i > 0:
            prev = ordered[i - 1]
            if (prev['scoring']['order'] == scoring['order'] and
                    prev['number_dice'] == u.number_dice):
                matched = prev['matched'] + 1
        ordered.append({
            'id': u.id,
            'name': u.name,
            'chips': u.chips,
            'number_dice': u.number_dice,
            'seat': i,
            'matched': matched,
            'scoring': scoring,
        })

    # Sort: lower order = better hand; for same order, fewer throws = better;
    # for same throws, later seat position (higher i) = worse (loser)
    ordered.sort(key=lambda x: (x['scoring']['order'], x['number_dice'], x['seat']))

    high = ordered[0]
    low = ordered[-1]

    # Calculate chip transfer
    high_chips = high['scoring']['chips']

    if high_chips == -1:
        # Schockaus: loser gets ALL chips (stack_max), half/finale is over
        transfer_chips = game.stack_max
        from_source = 'schockaus'
        from_name = 'Schock aus'
    elif game.stack > 0:
        # Chips come from stack
        transfer_chips = min(high_chips, game.stack)
        from_source = 'stack'
        from_name = 'Stapel'
    else:
        # Chips come from high player
        transfer_chips = min(high_chips, high['chips'])
        from_source = high['id']
        from_name = high['name']

    return {
        'High': _format_result(high),
        'Low': _format_result(low),
        'Chips': transfer_chips,
        'From': from_source,
        'From_Name': from_name,
        'To': low['id'],
        'To_Name': low['name'],
    }
