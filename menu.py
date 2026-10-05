"""CSP solver that assigns dishes to meal slots.

A slot is a (week, day, meal) tuple, e.g. (1, "Saturday", "Dinner").
"""
from collections import defaultdict
import random

from ortools.sat.python import cp_model

import config


class MenuError(Exception):
    """The menu can't be generated; the message is meant for the user."""


def plan_slots(weeks):
    """All slots that need a dish, in chronological order."""
    return [
        (w, day, meal)
        for w in range(1, weeks + 1)
        for day in config.DAYS
        for meal in config.MEALS
        if (day, meal) not in config.FREE_SLOTS
    ]


def required_tag(slot):
    _, day, meal = slot
    return next((tag for d, m, tag in config.TAG_RULES if (d, m) == (day, meal)), None)


def solve(dishes, slots, locked=None, seed=None, time_limit=10.0):
    """Assign a dish to every slot in `slots`.

    dishes: list of (dish_id, tag), the whole dish catalogue.
    slots: slots to fill.
    locked: {slot: dish_id} for slots that are already decided. Their dishes
        are not reused and they count towards the variety/balance rules.
    Returns {slot: dish_id}. Raises MenuError if no menu is possible.
    """
    locked = locked or {}
    rng = random.Random(seed)
    tag_of = dict(dishes)
    used = set(locked.values())
    available = [d for d, _ in dishes if d not in used]
    rng.shuffle(available)

    if len(available) < len(slots):
        raise MenuError(
            f"Not enough dishes: {len(slots)} meals to plan but only "
            f"{len(available)} dishes available. Add more dishes."
        )

    dishes_by_tag = defaultdict(list)
    for d in available:
        dishes_by_tag[tag_of[d]].append(d)

    needed_by_tag = defaultdict(list)
    for s in slots:
        if tag := required_tag(s):
            needed_by_tag[tag].append(s)
    for tag, needing in needed_by_tag.items():
        if len(dishes_by_tag[tag]) < len(needing):
            _, day, meal = needing[0]
            raise MenuError(
                f"{day} {meal.lower()} must be a '{tag}' dish, but there are only "
                f"{len(dishes_by_tag[tag])} available for {len(needing)} meals. "
                f"Add more '{tag}' dishes or change the rule in config.py."
            )

    model = cp_model.CpModel()
    x = {(s, d): model.NewBoolVar(f"x_{s}_{d}") for s in slots for d in available}

    for s in slots:
        model.AddExactlyOne(x[s, d] for d in available)
        if tag := required_tag(s):
            model.Add(sum(x[s, d] for d in dishes_by_tag[tag]) == 1)
    for d in available:
        model.AddAtMostOne(x[s, d] for s in slots)

    fill = set(slots)

    def tag_count(slot, tag):
        """Linear expression: 1 if `slot` gets a dish tagged `tag`."""
        if slot in locked:
            return int(tag_of.get(locked[slot]) == tag)
        if slot in fill:
            return sum(x[slot, d] for d in dishes_by_tag[tag])
        return 0

    all_tags = {t for _, t in dishes}

    if config.VARIED_DAYS:
        weeks = {w for w, _, _ in slots}
        for w in weeks:
            for day in config.DAYS:
                day_slots = [(w, day, m) for m in config.MEALS]
                if not any(s in fill for s in day_slots):
                    continue
                for tag in all_tags:
                    model.Add(sum(tag_count(s, tag) for s in day_slots) <= 1)

    # Soft balance: each week should get its fair share of every tag,
    # proportional to how many dishes of that tag exist.
    # Deviations are scaled by the number of dishes to stay integer.
    tag_totals = defaultdict(int)
    for _, t in dishes:
        tag_totals[t] += 1
    deviations = []
    for w in {w for w, _, _ in slots}:
        week_slots = [s for s in list(fill) + list(locked) if s[0] == w]
        for tag in all_tags:
            count = sum(tag_count(s, tag) for s in week_slots)
            target = tag_totals[tag] * len(week_slots)
            dev = model.NewIntVar(0, len(dishes) * len(week_slots), f"dev_{w}_{tag}")
            model.Add(dev >= len(dishes) * count - target)
            model.Add(dev >= target - len(dishes) * count)
            deviations.append(dev)

    # Random tie-breaking so every generation is different.
    noise = sum(rng.randrange(1000) * v for v in x.values())
    model.Minimize(1000 * sum(deviations) + noise)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.random_seed = rng.randrange(2**31)
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise MenuError(
            "No menu satisfies the rules. Try adding dishes with different tags "
            "(lunch and dinner on the same day can't share a tag)."
        )

    return {s: next(d for d in available if solver.Value(x[s, d])) for s in slots}


if __name__ == "__main__":
    import db

    conn = db.connect()
    dishes = [(r["id"], r["tag"]) for r in conn.execute("SELECT id, tag FROM dishes")]
    names = dict(conn.execute("SELECT id, name FROM dishes").fetchall())
    for (w, day, meal), d in solve(dishes, plan_slots(config.DEFAULT_WEEKS)).items():
        print(f"Week {w} {day:<9} {meal:<6} {names[d]} ({dict(dishes)[d]})")
