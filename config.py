"""Menu rules. Edit these to fit your household."""

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MEALS = ["Lunch", "Dinner"]

# Meals that are never planned (e.g. eating out). Shown as "Free" in the app.
FREE_SLOTS = {("Saturday", "Lunch")}

# Meals whose (main) dish must be of a given category.
CATEGORY_RULES = [("Saturday", "Dinner", "egg")]

# Lunch and dinner on the same day must have different categories.
VARIED_DAYS = True

# Number of weeks planned by default (the app lets you switch between 1 and 2).
DEFAULT_WEEKS = 1
MAX_WEEKS = 2

# Seasons by month (1-12). Dishes marked summer-only or winter-only are only
# planned in their season; months in neither set allow both.
SUMMER_MONTHS = {6, 7, 8, 9}
WINTER_MONTHS = {11, 12, 1, 2, 3}

# A dish that lasts 2 meals gets its second serving 1 to this many days later.
LEFTOVERS_MAX_GAP_DAYS = 2
