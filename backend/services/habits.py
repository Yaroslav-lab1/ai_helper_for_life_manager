from datetime import date, timedelta

from backend.models import Habit


def streak_stats(habit: Habit, today: date) -> dict[str, int | bool]:
    dates = sorted({item.checkin_date for item in habit.checkins})
    date_set = set(dates)
    cursor = today if today in date_set else today - timedelta(days=1)
    current = 0
    while cursor in date_set:
        current += 1
        cursor -= timedelta(days=1)

    best = run = 0
    previous = None
    for current_date in dates:
        run = run + 1 if previous and current_date == previous + timedelta(days=1) else 1
        best = max(best, run)
        previous = current_date

    week_start = today - timedelta(days=today.weekday())
    return {
        "current_streak": current,
        "best_streak": best,
        "completed_today": today in date_set,
        "week_count": sum(1 for item in dates if week_start <= item <= today),
    }
