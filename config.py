"""Menu rules. Edit these to fit your household."""

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MEALS = ["Lunch", "Dinner"]

# Meals that are never planned (e.g. eating out). Shown as "Free" in the app.
FREE_SLOTS = {("Saturday", "Lunch")}

# Meals that must be a dish with a given tag.
TAG_RULES = [("Saturday", "Dinner", "egg")]

# Lunch and dinner on the same day must have different tags.
VARIED_DAYS = True

# Number of weeks planned by default (the app lets you switch between 1 and 2).
DEFAULT_WEEKS = 1
MAX_WEEKS = 2
