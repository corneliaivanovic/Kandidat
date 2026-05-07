"""
Readiness-score beräkning (regelbaserat).
Ger en dagsformsprognos baserat på träningsdata.
"""

from dataclasses import dataclass
from models import Athlete


@dataclass
class ReadinessResult:
    """Resultat från readiness-beräkning."""
    score: int  # 0-100
    level: str  # "grön", "gul", "röd"
    acute_load: int  # Senaste 7 dagars belastning
    chronic_load: int  # 28-dagars genomsnittlig veckobelastning
    acwr: float  # Acute:Chronic Workload Ratio
    message: str  # Kort förklaring
    recommendation: str  # "vila", "lätt", "normal", "hårt"


def calculate_readiness(athlete: Athlete) -> ReadinessResult:
    """
    Beräkna readiness-score baserat på träningsbelastning.

    Använder Acute:Chronic Workload Ratio (ACWR) som grund:
    - Acute load = senaste 7 dagars totala belastning
    - Chronic load = genomsnittlig veckobelastning över 28 dagar
    - ACWR = Acute / Chronic

    Tumregler:
    - ACWR < 0.8: Undertränad, kan öka
    - ACWR 0.8-1.3: Optimal zon ("sweet spot")
    - ACWR 1.3-1.5: Varning, risk för överbelastning
    - ACWR > 1.5: Hög risk, behöver vila
    """

    # Beräkna acute load (senaste 7 dagarna)
    acute_load = athlete.get_total_load_last_n_days(7)

    # Beräkna chronic load (genomsnittlig veckobelastning över 28 dagar)
    total_28_days = athlete.get_total_load_last_n_days(28)
    chronic_load = total_28_days / 4  # Genomsnitt per vecka

    # Undvik division med noll
    if chronic_load == 0:
        acwr = 1.0 if acute_load == 0 else 2.0
    else:
        acwr = acute_load / chronic_load

    # Beräkna score och bestäm nivå
    if acwr < 0.8:
        # Undertränad - kan öka belastningen
        score = 85
        level = "grön"
        message = "Låg belastning. Du är redo att öka intensiteten."
        recommendation = "hårt"
    elif acwr <= 1.0:
        # Optimal - lägre delen
        score = 90
        level = "grön"
        message = "Bra balans. Kroppen är redo för träning."
        recommendation = "normal"
    elif acwr <= 1.3:
        # Optimal - övre delen
        score = 75
        level = "grön"
        message = "Bra träningsbelastning. Fortsätt som planerat."
        recommendation = "normal"
    elif acwr <= 1.5:
        # Varning
        score = 50
        level = "gul"
        message = "Hög belastning senaste veckan. Överväg lättare pass."
        recommendation = "lätt"
    else:
        # Hög risk
        score = 25
        level = "röd"
        message = "Mycket hög belastning. Vila eller aktiv återhämtning rekommenderas."
        recommendation = "vila"

    # Justera score baserat på variation (för lite variation = sämre)
    session_counts = athlete.get_session_count_by_type(7)
    unique_types = len(session_counts)
    if unique_types < 2:
        score = max(0, score - 10)
        message += " Överväg mer variation i träningen."

    return ReadinessResult(
        score=score,
        level=level,
        acute_load=acute_load,
        chronic_load=int(chronic_load),
        acwr=round(acwr, 2),
        message=message,
        recommendation=recommendation
    )


def get_week_trend(athlete: Athlete) -> dict:
    """
    Analysera träningstrend för veckan.
    Returnerar data för visualisering.
    """
    from datetime import date, timedelta

    today = date.today()
    weeks = []

    for week_num in range(4):
        week_start = today - timedelta(days=today.weekday() + (7 * week_num))
        week_end = week_start + timedelta(days=6)

        # Hämta loggar för denna vecka
        week_logs = [
            log for log in athlete.logs
            if week_start <= log.date <= week_end
        ]

        total_load = sum(log.load for log in week_logs)
        session_count = len(week_logs)
        avg_rpe = sum(log.rpe for log in week_logs) / session_count if session_count > 0 else 0

        weeks.append({
            "week_label": f"V{week_start.isocalendar()[1]}",
            "total_load": total_load,
            "session_count": session_count,
            "avg_rpe": round(avg_rpe, 1),
            "is_current": week_num == 0
        })

    # Omvänd så nuvarande vecka kommer sist
    weeks.reverse()
    return {"weeks": weeks}
