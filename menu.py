"""CSP solver that assigns dishes to meal slots.

A slot is a (week, day, meal) tuple, e.g. (1, "Saturday", "Dinner").
"""
from collections import defaultdict, namedtuple
import random

from ortools.sat.python import cp_model

import config


class MenuError(Exception):
    """The menu can't be generated; the message is meant for the user."""


# portions: how many meals one batch lasts (2 = the dish is repeated as leftovers).
Dish = namedtuple("Dish", "id category portions", defaults=(1,))


def plan_slots(weeks):
    """All slots that need a dish, in chronological order."""
    return [
        (w, day, meal)
        for w in range(1, weeks + 1)
        for day in config.DAYS
        for meal in config.MEALS
        if (day, meal) not in config.FREE_SLOTS
    ]


def day_number(slot):
    """Days since the start of the menu (Monday of week 1 is 0)."""
    week, day, _ = slot
    return (week - 1) * 7 + config.DAYS.index(day)


def required_category(slot):
    _, day, meal = slot
    return next((c for d, m, c in config.CATEGORY_RULES if (d, m) == (day, meal)), None)


def solve(dishes, slots, locked=None, allowed=None, seed=None, time_limit=5.0):
    """Assign dishes to every slot in `slots`.

    dishes: list of Dish, the dishes that can be planned.
    slots: slots to fill.
    locked: {slot: dish_id} for slots that are already decided. Their dishes
        are not reused and they count towards the variety/balance rules.
    allowed: optional function (slot, dish_id) -> bool, e.g. for seasons.
    Returns {slot: dish_id}. A dish with 2 portions fills two slots, the second
    within config.LEFTOVERS_MAX_GAP_DAYS days of the first.
    Raises MenuError if no menu is possible.
    """
    locked = locked or {}
    allowed = allowed or (lambda slot, dish_id: True)
    rng = random.Random(seed)
    by_id = {d.id: d for d in dishes}
    used = set(locked.values())
    available = [d for d in dishes if d.id not in used and any(allowed(s, d.id) for s in slots)]
    rng.shuffle(available)

    capacity = sum(d.portions for d in available)
    if capacity < len(slots):
        raise MenuError(
            f"Not enough dishes: {len(slots)} meals to plan but the dishes available "
            f"(in season, not already planned) only cover {capacity}. Add more dishes."
        )

    by_category = defaultdict(list)
    for d in available:
        by_category[d.category].append(d.id)

    needed_by_category = defaultdict(list)
    for s in slots:
        if category := required_category(s):
            needed_by_category[category].append(s)
    for category, needing in needed_by_category.items():
        if len(by_category[category]) < len(needing):
            _, day, meal = needing[0]
            raise MenuError(
                f"{day} {meal.lower()} must be a '{category}' dish, but there are only "
                f"{len(by_category[category])} available for {len(needing)} meals. "
                f"Add more '{category}' dishes or change the rule in config.py."
            )

    model = cp_model.CpModel()
    x = {(s, d.id): model.NewBoolVar(f"x_{s}_{d.id}") for s in slots for d in available}
    chosen = {d.id: model.NewBoolVar(f"chosen_{d.id}") for d in available}

    for s in slots:
        model.AddExactlyOne(x[s, d.id] for d in available)
        if category := required_category(s):
            model.Add(sum(x[s, d] for d in by_category[category]) == 1)
        for d in available:
            if not allowed(s, d.id):
                model.Add(x[s, d.id] == 0)

    for d in available:
        # A chosen dish fills exactly as many slots as it has portions.
        model.Add(sum(x[s, d.id] for s in slots) == d.portions * chosen[d.id])
        if d.portions > 1:
            for i, a in enumerate(slots):
                for b in slots[i + 1:]:
                    gap = abs(day_number(a) - day_number(b))
                    if gap == 0 or gap > config.LEFTOVERS_MAX_GAP_DAYS:
                        model.AddBoolOr([x[a, d.id].Not(), x[b, d.id].Not()])

    fill = set(slots)

    def category_count(slot, category):
        """Linear expression: 1 if `slot` gets a dish of `category`."""
        if slot in locked:
            dish = by_id.get(locked[slot])
            return int(dish is not None and dish.category == category)
        if slot in fill:
            return sum(x[slot, d] for d in by_category[category])
        return 0

    categories = {d.category for d in dishes}

    if config.VARIED_DAYS:
        for w in {w for w, _, _ in slots}:
            for day in config.DAYS:
                day_slots = [(w, day, m) for m in config.MEALS]
                if not any(s in fill for s in day_slots):
                    continue
                for category in categories:
                    model.Add(sum(category_count(s, category) for s in day_slots) <= 1)

    # Soft balance: each week should get its fair share of every category,
    # proportional to how many meals the dishes of that category provide.
    # Deviations are scaled by the total to stay integer.
    category_meals = defaultdict(int)
    for d in dishes:
        category_meals[d.category] += d.portions
    total = sum(category_meals.values())
    deviations = []
    for w in {w for w, _, _ in slots}:
        week_slots = [s for s in list(fill) + list(locked) if s[0] == w]
        for category in categories:
            count = sum(category_count(s, category) for s in week_slots)
            target = category_meals[category] * len(week_slots)
            dev = model.NewIntVar(0, total * len(week_slots), f"dev_{w}_{category}")
            model.Add(dev >= total * count - target)
            model.Add(dev >= target - total * count)
            deviations.append(dev)

    # Random tie-breaking so every generation is different.
    noise = sum(rng.randrange(1000) * v for v in x.values())
    model.Minimize(1000 * sum(deviations) + noise)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    # Close enough to the best balance; proving optimality can take much longer.
    solver.parameters.relative_gap_limit = 0.05
    solver.parameters.random_seed = rng.randrange(2**31)
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise MenuError(
            "No menu satisfies the rules. Try adding dishes of other categories "
            "(lunch and dinner on the same day can't share a category), or dishes "
            "that last a single meal."
        )

    return {s: next(d.id for d in available if solver.Value(x[s, d.id])) for s in slots}


if __name__ == "__main__":
    import db

    conn = db.connect()
    dishes = db.plannable_dishes(conn)
    names = dict(conn.execute("SELECT id, name FROM dishes").fetchall())
    for (w, day, meal), d in solve(dishes, plan_slots(config.DEFAULT_WEEKS)).items():
        print(f"Week {w} {day:<9} {meal:<6} {names[d]}")
