"""Build truthful strategy-health metrics from persisted forward validation."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def _number(value):
    try:
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None
    except (TypeError, ValueError, OverflowError):
        return None


def build_strategy_health(rows, storage, strategy_version, now=None):
    """Summarize independent first Top-10 15-minute outcomes, not a backtest."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    usable = []
    seen = set()
    for row in sorted(rows or [], key=lambda item: _number(item.get("epoch")) or 0):
        if row.get("record_type") != "scheduled_checkpoint" or row.get("strategy_version") != strategy_version:
            continue
        try:
            rank = int(row.get("rank"))
            epoch = float(row.get("epoch"))
            captured = datetime.fromtimestamp(epoch, timezone.utc)
        except (TypeError, ValueError, OverflowError):
            continue
        if not 1 <= rank <= 10 or not row.get("ticker") or not row.get("trade_date"):
            continue
        ny = captured.astimezone(NY)
        if ny.weekday() >= 5 or (ny.hour, ny.minute) < (9, 30) or (ny.hour, ny.minute) >= (16, 0):
            continue
        key = (row["trade_date"], row["ticker"])
        if key in seen:
            continue
        seen.add(key)
        outcome = _number(row.get("ret15m_pct"))
        if outcome is not None:
            usable.append((captured, outcome))

    def metrics(items):
        if not items:
            return None
        returns = [ret for _, ret in items]
        return {
            "signals": len(returns),
            "hit1": round(100 * sum(ret >= 1.0 for ret in returns) / len(returns), 1),
            "positive_rate": round(100 * sum(ret > 0 for ret in returns) / len(returns), 1),
            "expectancy_pct": round(sum(returns) / len(returns), 3),
            "stops": round(100 * sum(ret <= -1.0 for ret in returns) / len(returns), 1),
        }

    cutoff = now - timedelta(days=30)
    previous_cutoff = now - timedelta(days=60)
    recent_metrics = metrics([(stamp, ret) for stamp, ret in usable if stamp >= cutoff])
    previous_metrics = metrics([(stamp, ret) for stamp, ret in usable if previous_cutoff <= stamp < cutoff])
    delta = round(recent_metrics["hit1"] - previous_metrics["hit1"], 1) if recent_metrics and previous_metrics else None
    last = max((stamp for stamp, _ in usable), default=None)
    age_days = max(0, (now - last).days) if last else None

    reasons, recommendations = [], []
    if not storage.get("connected", False):
        status, status_he = "unavailable", "מחסן הלמידה לא זמין"
        reasons.append("לא ניתן לקרוא כרגע את נתוני האימות השמורים.")
        recommendations.append("בדוק את חיבור מסד הנתונים; אין לשנות את השיטה לפי מידע חלקי.")
    elif not recent_metrics and usable:
        status, status_he = "stale", "אין אימות מהתקופה האחרונה"
        reasons.append("קיימים נתוני אימות קודמים, אך לא נמדדו אותות במהלך 30 הימים האחרונים.")
        recommendations.append("המשך להריץ סריקה ולצבור מדגם עדכני; משקולות השיטה לא שונו.")
    elif not recent_metrics:
        status, status_he = "waiting", "ממתין לנתוני אימות"
        reasons.append("עדיין אין אותות Top-10 שנמדדו במשך 15 דקות בשעות המסחר ונשמרו לאימות.")
        recommendations.append("הסריקה תתחיל לאסוף אותות; המדדים יוצגו לאחר שהאותות ימדדו ויישמרו.")
    elif recent_metrics["signals"] < 20:
        status, status_he = "watch", "מדגם ראשוני"
        reasons.append(f"נמדדו {recent_metrics['signals']} אותות בלתי תלויים ב־30 הימים האחרונים; המדגם עדיין קטן.")
        recommendations.append("המשך לצבור נתונים. משקולות השיטה לא שונו.")
    else:
        status, status_he = "healthy", "נתוני אימות זמינים"
        reasons.append(f"המדדים מבוססים על {recent_metrics['signals']} אותות בלתי תלויים עם אופק מדידה קבוע של 15 דקות.")
        recommendations.append("המשך לעקוב אחרי המדגם; משקולות השיטה לא שונו.")

    return {
        "has_data": bool(usable),
        "source": "persisted_live_forward_validation",
        "validation_method": "first Top-10 observation per ticker and trading day, measured after 15 minutes",
        "status": status,
        "status_he": status_he,
        "backtest_age_days": age_days,
        "sample_count": recent_metrics["signals"] if recent_metrics else 0,
        "recent": ({
            "hit1": recent_metrics["hit1"],
            "positive_rate": recent_metrics["positive_rate"],
            "expectancy_pct": recent_metrics["expectancy_pct"],
            "stops": recent_metrics["stops"],
            "signals": recent_metrics["signals"],
        } if recent_metrics else None),
        "previous": previous_metrics,
        "delta_hit1_pct_points": delta,
        "reasons": reasons,
        "recommendations": recommendations,
        "storage": storage,
        "production_weights_unchanged": True,
    }
