from ortools.sat.python import cp_model
import csv

def generate_schedule():

    # 1) List all meals (26 total: 2 weeks * 14/day = 28 minus 2 Saturday lunches)
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    all_meals = []
    for w in range(1, 3):
        for day in days:
            for time in ["Lunch", "Dinner"]:
                if not (day == "Saturday" and time == "Lunch"):
                    # skip Saturday lunch
                    all_meals.append((w, day, time))
    num_meals = len(all_meals)  # should be 26

    # 2) Dishes (26 total) with categories
    def load_dishes_from_csv(filename):
        dish_list = []
        with open(filename, mode="r", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                dish_list.append((row["name"], row["tag"]))
        return dish_list

    dish_list = load_dishes_from_csv("dish_list.csv")
    num_dishes = len(dish_list)

    # 3) Build sets of dish indices by category (for easy counting)
    from collections import defaultdict
    cat_to_indices = defaultdict(list)
    for d_idx, (_, cat) in enumerate(dish_list):
        cat_to_indices[cat].append(d_idx)

    # 4) Create the model and the variables x[m, d]
    model = cp_model.CpModel()
    x = {}
    for m in range(num_meals):
        for d in range(num_dishes):
            x[(m, d)] = model.NewBoolVar(f"x_m{m}_d{d}")

    # 5) One dish per meal
    for m in range(num_meals):
        model.Add(sum(x[(m, d)] for d in range(num_dishes)) == 1)

    # 6) Each dish used exactly once
    for d in range(num_dishes):
        model.Add(sum(x[(m, d)] for m in range(num_meals)) == 1)

    # 7) Weekly category constraints
    cat_constraints = {
        "fish":       (2, 2),  # exactly 2 fish
        "chicken":    (2, 3),  # 2 or 3 chicken
        "vegetarian": (2, 3),  # 2 or 3 vegetarian
        "beef":       (1, 1),  # exactly 1 beef
        "egg":        (3, 3),  # exactly 3 egg
        "pig":        (1, 1),  # exactly 1 pig
        "other":      (1, 1),  # exactly 1 other
    }

    # Identify which meals belong to week 1 vs week 2
    week1_meals = [m for m, (w, _, _) in enumerate(all_meals) if w == 1]
    week2_meals = [m for m, (w, _, _) in enumerate(all_meals) if w == 2]

    # For each category, enforce min/max in each week
    for cat, (min_count, max_count) in cat_constraints.items():
        cat_dishes = cat_to_indices[cat]

        # Week 1
        model.Add(sum(x[(m, d)] 
                      for m in week1_meals 
                      for d in cat_dishes) >= min_count)
        model.Add(sum(x[(m, d)] 
                      for m in week1_meals 
                      for d in cat_dishes) <= max_count)

        # Week 2
        model.Add(sum(x[(m, d)]
                      for m in week2_meals
                      for d in cat_dishes) >= min_count)
        model.Add(sum(x[(m, d)]
                      for m in week2_meals
                      for d in cat_dishes) <= max_count)

    # 8) Saturday dinner must be egg
    # Find the index of each Saturday dinner
    sat_dinners = [m for m, (w, day, time) in enumerate(all_meals) 
                   if day == "Saturday" and time == "Dinner"]
    # We have two Saturdays (week 1 & week 2), each must be an egg dish
    for m in sat_dinners:
        model.Add(sum(x[(m, d)] for d in cat_to_indices["egg"]) == 1)

    # 9) Spacing constraint: no two consecutive meals with same category
    # We'll consider consecutive meals in the all_meals list.
    # For each pair (m, m+1), ensure categories differ.
    # We do that by disallowing x[(m, d1)] and x[(m+1, d2)] 
    # if dish_list[d1].cat == dish_list[d2].cat
    # for m in range(num_meals - 1):
    #     cat_conflicts = []
    #     for d1 in range(num_dishes):
    #         for d2 in range(num_dishes):
    #             if dish_list[d1][1] == dish_list[d2][1]:  # same category
    #                 # can't choose both
    #                 cat_conflicts.append((d1, d2))

    #     for (d1, d2) in cat_conflicts:
    #         # x[m,d1] + x[m+1,d2] <= 1
    #         model.Add(x[(m, d1)] + x[(m+1, d2)] <= 1)

    # Solve
    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    if status in [cp_model.FEASIBLE, cp_model.OPTIMAL]:
        solution = {}
        for m in range(num_meals):
            assigned_dish_idx = None
            for d in range(num_dishes):
                if solver.Value(x[(m, d)]) == 1:
                    assigned_dish_idx = d
                    break
            (week_number, day_name, meal_time) = all_meals[m]
            dish_name = dish_list[assigned_dish_idx][0]
            solution[(week_number, day_name, meal_time)] = dish_name

        # Sort by week, then day, then meal_time for readability
        sorted_solution = dict(sorted(solution.items(), key=lambda k: (k[0][0], 
                                                                       ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"].index(k[0][1]),
                                                                       ["Lunch","Dinner"].index(k[0][2]))))
        return sorted_solution
    else:
        return "No solution found"


if __name__ == "__main__":
    sched = generate_schedule()
    if isinstance(sched, dict):
        for (week, day, time), dish in sched.items():
            print(f"Week {week}, {day} {time} -> {dish}")
    else:
        print(sched)
