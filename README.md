# menu

You're planning the meals for the next two weeks. You have a list of dishes to choose from, and a set of things you want to eat each week. How do you find a good solution that satisfies all the requirements? A good option is using [Constraint satisfaction problem](https://en.wikipedia.org/wiki/Constraint_satisfaction_problem), or CSP.

The list of meals should be in `dish_list.csv`, with headers `name,tag` where tag is the main "component" of that meal, e.g. "chicken", "fish", "vegetarian"... There's a template in `dish_list_template.csv`.

The CSP solver code is in `menu.py`. You can (optionally) run it with `python menu.py` to see a possible solution (meal order is randomized so that it changes every time the schedule is re-generated).

Finally, `backend.py` serves 2 endpoints:

- `/menu` returns the current menu, saved in the session (persists while the server is running but not after)
- `/generate` calls `generate_schedule` to re-generate a new meal plan.

These endpoints are used in the web UI (index.html) to display the current schedule and to generate a new one on demand.

>[!warning]
> I programmed the CSP so that both Saturday lunches are free, and Saturday dinners are egg-based. The former is in line 36 (`if not (day == "Saturday" and time == "Lunch")`), and the latter is in the 8th restriction in `menu.py`, feel free to remove those if they don't suit your needs.

## TLDR

1. Create `dish_list.csv` and populate with some meals, ideally 26 of them (14 days, lunch+dinner, minus Saturday lunch—see warning above).
2. Make sure you're using Python 3.11 ([why?](https://github.com/google/or-tools/issues/3955)), (optionally) create a [Conda](https://docs.conda.io/projects/conda/en/latest/index.html) env with `conda create -n myenv python=3.11`.
2. `pip install flask flask_cors ortools` (no `requirements.txt` sorry)
3. Run `python backend.py`
4. On another window, run `python -m http.server` and open `http://localhost:8000` in your browser.

