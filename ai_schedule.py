"""
AI Schemaplanerare — Regelbaserad + RAG-baserad schemagenerering för löpare.

Skapar veckoscheman baserat på atletens profil, gren, träningsfas
och antal träningsdagar. Använder RAG med utbildningsmaterial och Claude API
för att generera kunskapsbaserade pass. Faller tillbaka till regelbaserade
mallar om API:t inte är tillgängligt.

Modulen genererar planerade pass (PlannedSession) direkt i databasen.
"""

from datetime import date, timedelta
from typing import Optional
import re
import traceback
from tempo_model import predict_session_tempo


# ============================================================
# PASSMALLAR PER GREN OCH FAS
# ============================================================

# Varje pass definieras som: (namn, typ, duration_min, intensitet, beskrivning)
RUNNING_WORKOUTS = {
    # --- SPRINT (100m-200m) ---
    "sprint": {
        "grundträning": {
            "hard": [
                ("Accelerationsträning", "snabbhet", 60, "hög",
                 "Uppvärmning: 15 min jogg + dynamisk stretch + 4x80m stigande\n"
                 "Huvudpass: 6x30m acceleration från block (vila 3 min)\n"
                 "4x60m med flygande start (vila 4 min)\n"
                 "Nedjogg: 10 min + stretch"),
                ("Fartträning 150m", "snabbhet", 50, "hög",
                 "Uppvärmning: 15 min jogg + dynamisk stretch\n"
                 "Huvudpass: 5x150m på 90% (vila 5 min)\n"
                 "Nedjogg: 10 min + stretch"),
            ],
            "medium": [
                ("Teknikpass sprint", "teknik", 60, "medel",
                 "Uppvärmning: 15 min jogg + dynamisk stretch\n"
                 "Huvudpass: Löpsteg A-skip, B-skip, high knees (4x30m vardera)\n"
                 "6x80m med fokus på avslappnad sprintteknik\n"
                 "Nedjogg: 10 min + stretch"),
                ("Löpskola & koordination", "teknik", 55, "medel",
                 "Uppvärmning: 10 min jogg + dynamisk stretch\n"
                 "Huvudpass: A-skip, B-skip, sidestepp 4x30m vardera\n"
                 "Ankelpendel och häl-tå-rullning 3x20m\n"
                 "4x60m med fokus på högt knälyft och aktiv fotisättning\n"
                 "Nedjogg: 10 min + stretch"),
            ],
            "easy": [
                ("Lugn löpning", "uthållighet", 35, "låg",
                 "35 min lugn löpning i zon 2 (puls under 150)\n"
                 "Fokus: avslappnad löpstil, jämn andning"),
                ("Återhämtning & rörlighet", "återhämtning", 40, "låg",
                 "15 min lätt jogg\n"
                 "25 min stretch och rörlighetsövningar\n"
                 "Fokus: höftrörlighet, hamstrings, vader"),
            ],
        },
        "uppbyggnad": {
            "hard": [
                ("Maxfart 60m", "snabbhet", 50, "hög",
                 "Uppvärmning: 15 min jogg + dynamisk stretch + 4x80m stigande\n"
                 "Huvudpass: 5x60m på 95% (vila 5 min)\n"
                 "3x30m från block på maxfart (vila 4 min)\n"
                 "Nedjogg: 10 min + stretch"),
                ("Fartuthållighet sprint", "snabbhet", 55, "hög",
                 "Uppvärmning: 15 min jogg + dynamisk stretch\n"
                 "Huvudpass: 3x200m på 95% (vila 8 min)\n"
                 "4x80m stigande till max (vila 3 min)\n"
                 "Nedjogg: 10 min + stretch"),
            ],
            "medium": [
                ("Teknik & starts", "teknik", 55, "medel",
                 "Uppvärmning: 15 min jogg + dynamisk stretch\n"
                 "Huvudpass: Blockstarter 6x20m (fokus teknik)\n"
                 "Löpsteg och koordination 4x40m\n"
                 "Nedjogg: 10 min + stretch"),
                ("Startteknik och acceleration", "teknik", 55, "medel",
                 "Uppvärmning: 15 min jogg + dynamisk stretch\n"
                 "Huvudpass: Blockstarter 6x20m (fokus teknik och reaktion)\n"
                 "Acceleration 4x40m med stigande fart\n"
                 "Flyvande löpningar 3x30m med fokus på hög frekvens\n"
                 "Nedjogg: 10 min + stretch"),
            ],
            "easy": [
                ("Lätt jogg", "uthållighet", 30, "låg",
                 "30 min lugn löpning\nFokus: återhämtning"),
                ("Aktiv vila", "återhämtning", 30, "låg",
                 "15 min promenad/lätt jogg\n15 min stretch och foam rolling"),
            ],
        },
        "tävling": {
            "hard": [
                ("Tävlingsförberedelse", "snabbhet", 40, "hög",
                 "Uppvärmning: 15 min jogg + dynamisk stretch\n"
                 "Huvudpass: 3x30m på max (vila 4 min)\n"
                 "2x60m på 95% (vila 5 min)\n"
                 "Nedjogg: 10 min + stretch"),
            ],
            "medium": [
                ("Aktivering", "teknik", 40, "medel",
                 "Uppvärmning: 10 min jogg + dynamisk stretch\n"
                 "Huvudpass: Löpsteg 4x60m, 3x30m stigande\n"
                 "Nedjogg: 10 min + stretch"),
            ],
            "easy": [
                ("Lätt löpning", "uthållighet", 25, "låg",
                 "25 min lugn jogg\nFokus: håll kroppen lös inför tävling"),
                ("Vila + stretch", "återhämtning", 20, "låg",
                 "20 min stretch och mental förberedelse"),
            ],
        },
        "återhämtning": {
            "hard": [],
            "medium": [
                ("Lätt teknik", "teknik", 40, "låg",
                 "Uppvärmning: 10 min jogg\n"
                 "Huvudpass: Löpsteg i lugnt tempo 6x50m\n"
                 "Nedjogg: 10 min + stretch"),
            ],
            "easy": [
                ("Lätt jogg", "uthållighet", 25, "låg",
                 "25 min lugn löpning i zon 1-2"),
                ("Stretch & rörlighet", "återhämtning", 30, "låg",
                 "30 min stretch, foam rolling, rörlighetsövningar"),
            ],
        },
    },

    # --- MEDELDISTANS (400m-1500m) ---
    "medel": {
        "grundträning": {
            "hard": [
                ("Tröskelpass", "uthållighet", 60, "hög",
                 "Uppvärmning: 15 min jogg + dynamisk stretch\n"
                 "Huvudpass: 20 min löpning i tröskeltempo (puls ~85% av max)\n"
                 "Nedjogg: 15 min + stretch"),
                ("Intervaller 400m", "snabbhet", 65, "hög",
                 "Uppvärmning: 15 min jogg + dynamisk stretch + 4x100m stigande\n"
                 "Huvudpass: 8x400m (vila 90s mellan)\n"
                 "Nedjogg: 15 min + stretch"),
            ],
            "medium": [
                ("Fartlek", "uthållighet", 50, "medel",
                 "Uppvärmning: 10 min jogg\n"
                 "Huvudpass: 30 min fartlek (2 min hårt / 2 min lugnt)\n"
                 "Nedjogg: 10 min + stretch"),
                ("Löpteknik och stegfrekvens", "teknik", 50, "medel",
                 "Uppvärmning: 10 min jogg + löpskola\n"
                 "Huvudpass: 6x100m med fokus på hög stegfrekvens och avslappning\n"
                 "Löpsteg och koordinationsövningar 4x40m\n"
                 "Nedjogg: 10 min + stretch"),
            ],
            "easy": [
                ("Lugn distanslöpning", "uthållighet", 45, "låg",
                 "45 min lugn löpning i zon 2\nJämn puls, avslappnat"),
                ("Återhämtningsjogg", "återhämtning", 30, "låg",
                 "30 min mycket lugn jogg + 10 min stretch"),
            ],
        },
        "uppbyggnad": {
            "hard": [
                ("VO2max-intervaller", "snabbhet", 60, "hög",
                 "Uppvärmning: 15 min jogg + dynamisk stretch\n"
                 "Huvudpass: 5x1000m på 90-95% (vila 3 min)\n"
                 "Nedjogg: 15 min + stretch"),
                ("Tempointervaller 600m", "snabbhet", 55, "hög",
                 "Uppvärmning: 15 min jogg + dynamisk stretch\n"
                 "Huvudpass: 6x600m (vila 2 min)\n"
                 "Nedjogg: 10 min + stretch"),
            ],
            "medium": [
                ("Progressiv löpning", "uthållighet", 50, "medel",
                 "Uppvärmning: 10 min jogg\n"
                 "Huvudpass: 30 min löpning med stigande tempo\n"
                 "(börja lugnt, avsluta i tröskeltempo)\n"
                 "Nedjogg: 10 min + stretch"),
                ("Tempojogg med stegringar", "uthållighet", 50, "medel",
                 "Uppvärmning: 10 min jogg\n"
                 "Huvudpass: 25 min löpning i zon 3 med 4x100m stegringar inlagda\n"
                 "Fokus: kontrollerat löpsteg i stigande tempo\n"
                 "Nedjogg: 10 min + stretch"),
            ],
            "easy": [
                ("Lugn löpning", "uthållighet", 40, "låg",
                 "40 min lugn löpning i zon 2"),
                ("Aktiv vila", "återhämtning", 30, "låg",
                 "20 min lätt jogg + 10 min stretch"),
            ],
        },
        "tävling": {
            "hard": [
                ("Tävlingsspecifikt", "snabbhet", 50, "hög",
                 "Uppvärmning: 15 min jogg + dynamisk stretch\n"
                 "Huvudpass: 3x300m i tävlingsfart (vila 5 min)\n"
                 "2x200m snabbt (vila 4 min)\n"
                 "Nedjogg: 10 min + stretch"),
            ],
            "medium": [
                ("Aktivering", "teknik", 40, "medel",
                 "Uppvärmning: 10 min jogg\n"
                 "Huvudpass: 4x200m i lugnt tempo + löpsteg\n"
                 "Nedjogg: 10 min + stretch"),
            ],
            "easy": [
                ("Lätt löpning", "uthållighet", 30, "låg",
                 "30 min lugn jogg inför tävling"),
                ("Vila + förberedelse", "återhämtning", 20, "låg",
                 "20 min stretch och mental förberedelse"),
            ],
        },
        "återhämtning": {
            "hard": [],
            "medium": [
                ("Lätt fartlek", "uthållighet", 40, "låg",
                 "Uppvärmning: 10 min jogg\n"
                 "Huvudpass: 20 min lätt fartlek (30s snabbare / 2 min lugnt)\n"
                 "Nedjogg: 10 min + stretch"),
            ],
            "easy": [
                ("Lugn jogg", "uthållighet", 30, "låg",
                 "30 min lugn löpning i zon 1-2"),
                ("Stretch & rörlighet", "återhämtning", 30, "låg",
                 "30 min stretch, foam rolling, rörlighetsövningar"),
            ],
        },
    },

    # --- DISTANS (3000m+) ---
    "distans": {
        "grundträning": {
            "hard": [
                ("Tröskelpass långt", "uthållighet", 70, "hög",
                 "Uppvärmning: 15 min jogg + dynamisk stretch\n"
                 "Huvudpass: 2x15 min i tröskeltempo (vila 3 min)\n"
                 "Nedjogg: 15 min + stretch"),
                ("Intervaller 1000m", "snabbhet", 70, "hög",
                 "Uppvärmning: 15 min jogg + dynamisk stretch\n"
                 "Huvudpass: 6x1000m (vila 2 min)\n"
                 "Nedjogg: 15 min + stretch"),
            ],
            "medium": [
                ("Medelstark löpning", "uthållighet", 55, "medel",
                 "Uppvärmning: 10 min jogg\n"
                 "Huvudpass: 35 min löpning i zon 3 (medelhög puls)\n"
                 "Nedjogg: 10 min + stretch"),
                ("Backlöpning och kuperad terräng", "uthållighet", 50, "medel",
                 "Uppvärmning: 10 min jogg\n"
                 "Huvudpass: 6x200m uppförsbacke i medelhård fart (vila: jogg ner)\n"
                 "Fokus: framåtlutning, knälyft och drivkraft från höft\n"
                 "Nedjogg: 10 min + stretch"),
            ],
            "easy": [
                ("Lång löpning", "uthållighet", 60, "låg",
                 "60 min lugn löpning i zon 2\nBygg aerob bas"),
                ("Återhämtningsjogg", "återhämtning", 30, "låg",
                 "30 min mycket lugn jogg + stretch"),
            ],
        },
        "uppbyggnad": {
            "hard": [
                ("VO2max 1200m", "snabbhet", 70, "hög",
                 "Uppvärmning: 15 min jogg + dynamisk stretch\n"
                 "Huvudpass: 5x1200m på 90-95% (vila 3 min)\n"
                 "Nedjogg: 15 min + stretch"),
                ("Tempolöpning", "uthållighet", 65, "hög",
                 "Uppvärmning: 15 min jogg\n"
                 "Huvudpass: 25 min i tröskeltempo\n"
                 "Nedjogg: 15 min + stretch"),
            ],
            "medium": [
                ("Fartlek i terräng", "uthållighet", 55, "medel",
                 "Uppvärmning: 10 min jogg\n"
                 "Huvudpass: 35 min fartlek i kuperad terräng\n"
                 "(1 min hårt i backar, lugnt emellan)\n"
                 "Nedjogg: 10 min + stretch"),
            ],
            "easy": [
                ("Lugn distanslöpning", "uthållighet", 50, "låg",
                 "50 min lugn löpning"),
                ("Aktiv vila", "återhämtning", 30, "låg",
                 "20 min lätt jogg + 10 min stretch"),
            ],
        },
        "tävling": {
            "hard": [
                ("Tävlingsspecifikt", "snabbhet", 55, "hög",
                 "Uppvärmning: 15 min jogg + dynamisk stretch\n"
                 "Huvudpass: 3x1000m i tävlingsfart (vila 3 min)\n"
                 "Nedjogg: 15 min + stretch"),
            ],
            "medium": [
                ("Aktivering", "uthållighet", 40, "medel",
                 "Uppvärmning: 10 min jogg\n"
                 "20 min lugn löpning med 4x30s inflikar\n"
                 "Nedjogg: 10 min"),
            ],
            "easy": [
                ("Lätt löpning", "uthållighet", 30, "låg",
                 "30 min lugn löpning"),
                ("Vila", "återhämtning", 20, "låg",
                 "20 min stretch och mental förberedelse"),
            ],
        },
        "återhämtning": {
            "hard": [],
            "medium": [
                ("Lätt löpning", "uthållighet", 40, "låg",
                 "40 min lugn löpning i zon 1-2"),
            ],
            "easy": [
                ("Mycket lugn jogg", "uthållighet", 30, "låg",
                 "30 min lugn jogg"),
                ("Stretch & rörlighet", "återhämtning", 30, "låg",
                 "30 min stretch och foam rolling"),
            ],
        },
    },
}

# Fallback: om grenen inte matchar sprint/medel/distans
# Mappa discipline till löpkategori
DISCIPLINE_TO_RUNNING = {
    "sprint": "sprint",
    "medel": "medel",
    "distans": "distans",
    "hopp": "sprint",       # Hoppare tränar ofta som sprinters
    "kast": "sprint",       # Kastare gör ofta sprintliknande
    "mangkamp": "medel",    # Mångkamp = blandning
}

PACE_DISTANCE_LABELS = {
    200: "200 m",
    300: "300 m",
    400: "400 m",
    600: "600 m",
    800: "800 m",
    1000: "1000 m",
    1500: "1500 m",
    3000: "3000 m",
    5000: "5 km",
    10000: "10 km",
}


# ============================================================
# VECKOPLANERINGSSYSTEM
# ============================================================

def get_week_template(days_per_week: int) -> list[dict]:
    """
    Returnerar en mall för veckan baserat på antal träningsdagar.
    Varje dag har en 'difficulty': 'hard', 'medium', 'easy', eller 'rest'.
    """
    templates = {
        3: [
            {"day": 0, "difficulty": "hard"},     # Måndag
            {"day": 1, "difficulty": "rest"},      # Tisdag
            {"day": 2, "difficulty": "medium"},    # Onsdag
            {"day": 3, "difficulty": "rest"},      # Torsdag
            {"day": 4, "difficulty": "hard"},      # Fredag
            {"day": 5, "difficulty": "rest"},      # Lördag
            {"day": 6, "difficulty": "rest"},      # Söndag
        ],
        4: [
            {"day": 0, "difficulty": "hard"},      # Måndag
            {"day": 1, "difficulty": "easy"},       # Tisdag
            {"day": 2, "difficulty": "medium"},     # Onsdag
            {"day": 3, "difficulty": "rest"},       # Torsdag
            {"day": 4, "difficulty": "hard"},       # Fredag
            {"day": 5, "difficulty": "easy"},       # Lördag
            {"day": 6, "difficulty": "rest"},       # Söndag
        ],
        5: [
            {"day": 0, "difficulty": "hard"},      # Måndag
            {"day": 1, "difficulty": "easy"},       # Tisdag
            {"day": 2, "difficulty": "medium"},     # Onsdag
            {"day": 3, "difficulty": "easy"},       # Torsdag
            {"day": 4, "difficulty": "hard"},       # Fredag
            {"day": 5, "difficulty": "medium"},     # Lördag
            {"day": 6, "difficulty": "rest"},       # Söndag
        ],
        6: [
            {"day": 0, "difficulty": "hard"},      # Måndag
            {"day": 1, "difficulty": "easy"},       # Tisdag
            {"day": 2, "difficulty": "medium"},     # Onsdag
            {"day": 3, "difficulty": "easy"},       # Torsdag
            {"day": 4, "difficulty": "hard"},       # Fredag
            {"day": 5, "difficulty": "medium"},     # Lördag
            {"day": 6, "difficulty": "rest"},       # Söndag
        ],
    }
    return templates.get(days_per_week, templates[4])


def _get_session_types_for_difficulty(difficulty: str) -> list[str]:
    """Returnera vilka passtyper som passar för en viss svårighet."""
    if difficulty == "hard":
        return ["snabbhet", "uthållighet"]
    elif difficulty == "medium":
        return ["teknik", "uthållighet"]
    else:
        return ["uthållighet", "återhämtning"]


def _parse_time_to_seconds(value: str) -> Optional[float]:
    if not value:
        return None
    text = str(value).strip().lower().replace(",", ".")
    if not text:
        return None
    if ":" in text:
        parts = text.split(":")
        try:
            seconds = 0.0
            for part in parts:
                seconds = seconds * 60 + float(part)
            return seconds
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_distance_to_meters(value: str) -> Optional[int]:
    if not value:
        return None
    text = str(value).strip().lower().replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(km|m)?", text)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2) or "m"
    return int(round(amount * 1000)) if unit == "km" else int(round(amount))


def _event_to_meters(event_name: str) -> Optional[int]:
    cleaned = (event_name or "").replace("män", "").replace("kvinnor", "").strip()
    return _parse_distance_to_meters(cleaned)


def _estimate_time_for_distance(source_distance_m: int, source_time_s: float, target_distance_m: int) -> float:
    return source_time_s * ((target_distance_m / source_distance_m) ** 1.06)


def _format_seconds(seconds: float) -> str:
    rounded = int(round(seconds))
    minutes, sec = divmod(rounded, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes}:{sec:02d}"


def _format_pace_seconds(seconds_per_km: float) -> str:
    minutes = int(seconds_per_km // 60)
    seconds = int(round(seconds_per_km % 60))
    if seconds == 60:
        minutes += 1
        seconds = 0
    return f"{minutes}:{seconds:02d} min/km"


def _format_pace_range(low_seconds: float, high_seconds: float) -> str:
    low, high = sorted((low_seconds, high_seconds))
    return f"{_format_pace_seconds(low)}–{_format_pace_seconds(high)}"


def _format_rep_range(distance_m: int, low_seconds_per_km: float, high_seconds_per_km: float) -> str:
    low, high = sorted((low_seconds_per_km, high_seconds_per_km))
    factor = distance_m / 1000
    label = PACE_DISTANCE_LABELS.get(distance_m, f"{distance_m} m")
    return f"{_format_seconds(low * factor)}–{_format_seconds(high * factor)} per {label}"


def _choose_performance_anchor(athlete_info: dict, running_type: str) -> tuple[Optional[int], Optional[float], str]:
    best_5k = _parse_time_to_seconds(athlete_info.get("best_5k_time", ""))
    if best_5k:
        return 5000, best_5k, "manuell 5 km-tid"

    alt_distance = _parse_distance_to_meters(athlete_info.get("best_alt_distance", ""))
    alt_time = _parse_time_to_seconds(athlete_info.get("best_alt_time", ""))
    if alt_distance and alt_time:
        return alt_distance, alt_time, "manuell alternativ distans"

    pb_map = athlete_info.get("competition_results", {}).get("personal_bests", {}) or {}
    if pb_map:
        preferred = [1500, 800, 3000, 5000, 10000] if running_type == "medel" else [5000, 3000, 10000, 1500, 800]
        parsed = []
        for event_name, pb in pb_map.items():
            event_distance = _event_to_meters(event_name)
            event_time = _parse_time_to_seconds(pb.get("result", ""))
            if event_distance and event_time:
                parsed.append((event_distance, event_time, event_name))
        for target in preferred:
            for event_distance, event_time, event_name in parsed:
                if event_distance == target:
                    return event_distance, event_time, f"tävlingsresultat {event_name}"
    return None, None, ""


def _build_pace_model(athlete_info: dict, running_type: str) -> dict:
    if running_type not in {"medel", "distans"}:
        return {}

    model = {
        "running_type": running_type,
        "training_surface": athlete_info.get("training_surface", ""),
        "tempo_model_runner_key": athlete_info.get("tempo_model_runner_key", ""),
        "has_external_training_data": bool(athlete_info.get("has_external_training_data")),
    }
    easy_pace_raw = (athlete_info.get("easy_pace") or "").strip()
    threshold_pace_raw = (athlete_info.get("threshold_pace") or "").strip()
    source_distance, source_time, source_label = _choose_performance_anchor(athlete_info, running_type)

    if source_distance and source_time:
        time_1500 = _estimate_time_for_distance(source_distance, source_time, 1500)
        time_3000 = _estimate_time_for_distance(source_distance, source_time, 3000)
        time_5000 = _estimate_time_for_distance(source_distance, source_time, 5000)
        time_10000 = _estimate_time_for_distance(source_distance, source_time, 10000)

        model.update({
            "source_label": source_label,
            "pace_1500": time_1500 / 1.5,
            "pace_3000": time_3000 / 3,
            "pace_5000": time_5000 / 5,
            "threshold_low": (time_10000 / 10) * 0.99,
            "threshold_high": (time_5000 / 5) * 1.03,
        })

        experience = athlete_info.get("training_experience_level", "")
        easy_offset = (50, 80) if experience == "jag är ny till att träna" else (40, 70)
        model["easy_low"] = model["threshold_low"] + easy_offset[0]
        model["easy_high"] = model["threshold_high"] + easy_offset[1]

    if easy_pace_raw:
        model["easy_text"] = easy_pace_raw
    elif model.get("easy_low") and model.get("easy_high"):
        model["easy_text"] = _format_pace_range(model["easy_low"], model["easy_high"])

    if threshold_pace_raw:
        model["threshold_text"] = threshold_pace_raw
    elif model.get("threshold_low") and model.get("threshold_high"):
        model["threshold_text"] = _format_pace_range(model["threshold_low"], model["threshold_high"])

    if model.get("pace_5000"):
        model["vo2_text"] = _format_pace_range(model["pace_5000"] * 0.99, model["pace_5000"] * 1.02)
    if model.get("pace_3000"):
        model["speed_endurance_text"] = _format_pace_range(model["pace_3000"] * 0.99, model["pace_3000"] * 1.02)
    if model.get("pace_1500"):
        model["fast_rep_text"] = _format_pace_range(model["pace_1500"] * 0.99, model["pace_1500"] * 1.03)
    return model


def _extract_rep_distance(text: str) -> Optional[int]:
    matches = re.findall(r"(\d{2,4})\s*m", (text or "").lower())
    if not matches:
        return None
    candidates = [int(match) for match in matches if 150 <= int(match) <= 2000]
    return candidates[0] if candidates else None


def _extract_main_work_text(description: str) -> str:
    for raw_line in (description or "").splitlines():
        line = raw_line.strip()
        if line.lower().startswith("huvudpass:"):
            return line.lower()
    return (description or "").lower()


def _has_positive_threshold_signal(text: str) -> bool:
    lowered = (text or "").lower()
    for match in re.finditer(r"(tröskel(?:fart|tempo)?|snabbdistans|tempolöp|tempopass)", lowered):
        prefix = lowered[max(0, match.start() - 24):match.start()]
        if "undvik" in prefix or "inte" in prefix:
            continue
        return True
    return False


def _session_pace_profile(
    session_name: str,
    session_type: str,
    intensity: str,
    description: str,
) -> dict:
    text = " ".join([session_name or "", session_type or "", intensity or "", description or ""]).lower()
    main_work_text = " ".join([
        (session_name or "").lower(),
        _extract_main_work_text(description),
    ]).strip()
    rep_distance = _extract_rep_distance(main_work_text or text)
    is_threshold_like = _has_positive_threshold_signal(main_work_text)
    is_easy_like = any(token in main_work_text for token in [
        "aerob zon", "zon 1", "zon 2", "lugn", "jogg", "distans", "lång löpning", "långpass"
    ])
    is_long_like = any(token in main_work_text for token in [
        "kontinuerligt", "stabil aerob", "volym", "grunduthållighet"
    ])
    return {
        "text": text,
        "main_work_text": main_work_text,
        "rep_distance": rep_distance,
        "is_threshold_like": is_threshold_like,
        "is_easy_like": is_easy_like,
        "is_long_like": is_long_like,
    }


def _garmin_pace_hint_for_session(
    session_name: str,
    session_type: str,
    intensity: str,
    description: str,
    pace_model: dict,
) -> tuple[str, str, str]:
    runner_key = (pace_model.get("tempo_model_runner_key") or "").strip()
    has_external_data = bool(pace_model.get("has_external_training_data"))
    if not runner_key and not has_external_data:
        return "", "", ""

    prediction = predict_session_tempo(
        session_name=session_name,
        session_type=session_type,
        intensity=intensity,
        description=description,
        training_surface=pace_model.get("training_surface", ""),
        runner_key=runner_key,
    )
    assumptions = [
        f"passmedel-IF {prediction['if']:.2f}",
        f"stigning {prediction['stigning_per_km']:.0f} m/km",
        f"nedför {prediction['nedfor_per_km']:.0f} m/km",
    ]
    if prediction.get("rep_adjustment", 1.0) != 1.0:
        assumptions.append(f"rep-justering {prediction['rep_adjustment']:.3f}x")
    if runner_key:
        assumptions.append(f"profil {runner_key}")
    assumptions_text = ", ".join(assumptions)
    pace_text = _format_pace_range(
        prediction["low_seconds_per_km"],
        prediction["high_seconds_per_km"],
    )
    return f"Tempo ungefär {pace_text}.", prediction["source"], assumptions_text


def _pace_hint_for_session(
    session_name: str,
    session_type: str,
    intensity: str,
    description: str,
    pace_model: dict,
) -> tuple[str, str, str]:
    profile = _session_pace_profile(session_name, session_type, intensity, description)
    text = profile["text"]
    main_work_text = profile["main_work_text"]
    rep_distance = profile["rep_distance"]
    is_threshold_like = profile["is_threshold_like"]
    is_easy_like = profile["is_easy_like"]
    is_long_like = profile["is_long_like"]

    prefer_garmin = (
        not is_threshold_like
        and not rep_distance
        and intensity != "hög"
        and (intensity == "låg" or is_easy_like or is_long_like or intensity == "medel")
    )

    if prefer_garmin:
        garmin_hint, garmin_source, garmin_assumptions = _garmin_pace_hint_for_session(
            session_name=session_name,
            session_type=session_type,
            intensity=intensity,
            description=description,
            pace_model=pace_model,
        )
        if garmin_hint:
            return garmin_hint, garmin_source, garmin_assumptions

    if any(token in main_work_text for token in ["återhämtnings", "lugn", "zon 1", "zon 2", "aerob zon"]):
        if pace_model.get("easy_text"):
            return f"Tempo ungefär {pace_model['easy_text']}.", "race_based_heuristic", ""
    if is_threshold_like:
        if pace_model.get("threshold_text"):
            return f"Tempo ungefär {pace_model['threshold_text']}.", "race_based_heuristic", ""
    if rep_distance:
        if rep_distance <= 300 and pace_model.get("pace_1500"):
            return f"Tempo ungefär {_format_pace_range(pace_model['pace_1500'] * 0.99, pace_model['pace_1500'] * 1.03)}.", "race_based_heuristic", ""
        if rep_distance <= 600 and pace_model.get("pace_3000"):
            return f"Tempo ungefär {_format_pace_range(pace_model['pace_3000'] * 0.99, pace_model['pace_3000'] * 1.02)}.", "race_based_heuristic", ""
        if rep_distance >= 800 and pace_model.get("pace_5000"):
            return f"Tempo ungefär {_format_pace_range(pace_model['pace_5000'] * 0.99, pace_model['pace_5000'] * 1.02)}.", "race_based_heuristic", ""
    if intensity == "låg" and pace_model.get("easy_text"):
        return f"Tempo ungefär {pace_model['easy_text']}.", "race_based_heuristic", ""
    if intensity == "hög" and pace_model.get("threshold_text"):
        return f"Håll ungefär {pace_model['threshold_text']} på längre arbetsblock.", "race_based_heuristic", ""

    garmin_hint, garmin_source, garmin_assumptions = _garmin_pace_hint_for_session(
        session_name=session_name,
        session_type=session_type,
        intensity=intensity,
        description=description,
        pace_model=pace_model,
    )
    if garmin_hint:
        return garmin_hint, garmin_source, garmin_assumptions
    return "", "", ""


def _append_pace_hint_to_description(description: str, pace_hint: str, pace_source: str = "") -> str:
    if not description or not pace_hint:
        return description

    lower = description.lower()
    pace_patterns = [
        r"\d+:\d{2}\s*(?:min/)?km",
        r"\d+:\d{2}\s*[–-]\s*\d+:\d{2}\s*(?:min/)?km",
        r"\d+:\d{2}\s*[–-]\s*\d+:\d{2}\s*/km",
        r"\d+:\d{2}\s*(?:per)\s*\d+\s*m",
        r"\d+:\d{2}\s*[–-]\s*\d+:\d{2}\s*(?:per)\s*\d+\s*m",
    ]
    if any(re.search(pattern, lower) for pattern in pace_patterns):
        return description

    source_text = ""
    if pace_source == "garmin_model_offset":
        source_text = " (Garmin-modell med personlig profil)"
    elif pace_source == "garmin_model_population":
        source_text = " (Garmin-modell)"
    elif pace_source == "race_based_heuristic":
        source_text = " (tävlings-/profilbaserad uppskattning)"
    pace_hint_with_source = f"{pace_hint.rstrip('.')}{source_text}."

    lines = description.split("\n")
    for index, line in enumerate(lines):
        if line.startswith("Huvudpass:"):
            lines[index] = f"{line} {pace_hint_with_source}".strip()
            return "\n".join(lines)
    return description + f"\nTempoindikation: {pace_hint_with_source}"


def _normalize_pace_text_to_min_per_km(description: str) -> str:
    if not description:
        return description

    def normalize_line(line: str) -> str:
        distance_match = re.search(r"(\d{2,4})\s*m", line, flags=re.IGNORECASE)
        if not distance_match:
            return line
        rep_distance = int(distance_match.group(1))

        line = re.sub(
            r"(\d+):(\d{2})\s*[–-]\s*(\d+):(\d{2})\s*per\s*\d+\s*m",
            lambda m: _format_pace_range(
                (int(m.group(1)) * 60 + int(m.group(2))) * (1000 / rep_distance),
                (int(m.group(3)) * 60 + int(m.group(4))) * (1000 / rep_distance),
            ),
            line,
            flags=re.IGNORECASE,
        )
        line = re.sub(
            r"(\d+):(\d{2})\s*per\s*\d+\s*m",
            lambda m: _format_pace_seconds(
                (int(m.group(1)) * 60 + int(m.group(2))) * (1000 / rep_distance)
            ),
            line,
            flags=re.IGNORECASE,
        )
        line = re.sub(
            r"(\d+)\s*[–-]\s*(\d+)\s*sek/rep",
            lambda m: _format_pace_range(
                int(m.group(1)) * (1000 / rep_distance),
                int(m.group(2)) * (1000 / rep_distance),
            ),
            line,
            flags=re.IGNORECASE,
        )
        line = re.sub(
            r"(\d+)\s*sek/rep",
            lambda m: _format_pace_seconds(int(m.group(1)) * (1000 / rep_distance)),
            line,
            flags=re.IGNORECASE,
        )
        return line

    return "\n".join(normalize_line(line) for line in description.splitlines())


def _rounded_volume_split(duration: int, ratios: tuple[float, float, float]) -> tuple[int, int, int]:
    total = max(0, int(duration or 0))
    low = int(round(total * ratios[0]))
    medium = int(round(total * ratios[1]))
    high = max(0, total - low - medium)
    if low + medium + high != total:
        high = max(0, total - low - medium)
    return low, medium, high


def estimate_intensity_distribution(
    session_name: str,
    session_type: str,
    planned_duration: int,
    planned_intensity: str,
    description: str,
) -> dict:
    """
    Heuristisk uppskattning av hur passets minuter fördelas över låg, mellan och hög intensitet.
    Används för 80/20 och mellanzonskontroll på periodnivå.
    """
    duration = max(0, int(planned_duration or 0))
    text = " ".join([
        session_name or "",
        session_type or "",
        planned_intensity or "",
        description or "",
    ]).lower()

    is_sprint_like = any(token in text for token in [
        "sprint", "acceleration", "block", "maxfart", "flygande", "startteknik"
    ])
    is_recovery = any(token in text for token in [
        "återhämt", "aktiv vila", "mycket lugn", "stretch", "rörlighet"
    ])
    is_threshold = any(token in text for token in [
        "tröskel", "snabbdistans", "tempo", "tröskelfart"
    ])
    is_fartlek = "fartlek" in text
    is_interval = any(token in text for token in [
        "intervall", "x400", "x600", "x800", "x1000", "x1200", "vo2"
    ])

    if duration == 0:
        return {
            "low": 0,
            "medium": 0,
            "high": 0,
            "source": "heuristic",
        }

    if is_recovery or planned_intensity == "låg":
        ratios = (0.9, 0.1, 0.0)
    elif is_sprint_like and planned_intensity == "hög":
        ratios = (0.65, 0.10, 0.25)
    elif is_sprint_like:
        ratios = (0.7, 0.2, 0.1)
    elif is_threshold:
        ratios = (0.45, 0.4, 0.15)
    elif is_fartlek:
        ratios = (0.5, 0.35, 0.15)
    elif is_interval or planned_intensity == "hög":
        ratios = (0.45, 0.15, 0.40)
    elif planned_intensity == "medel":
        ratios = (0.6, 0.3, 0.1)
    else:
        ratios = (0.75, 0.2, 0.05)

    low, medium, high = _rounded_volume_split(duration, ratios)
    return {
        "low": low,
        "medium": medium,
        "high": high,
        "source": "heuristic",
    }


def _build_athlete_info(athlete: object) -> dict:
    """
    Bygg ett athlete_info-dict med grundprofil + tävlingsresultat om de finns.
    Tävlingsresultaten används av AI:n för att anpassa träningen efter faktisk prestationsnivå.
    """
    info: dict = {}
    if hasattr(athlete, 'birth_year') and athlete.birth_year:
        info["age"]        = date.today().year - athlete.birth_year
        info["birth_year"] = athlete.birth_year
    if hasattr(athlete, 'discipline') and athlete.discipline:
        info["discipline"] = athlete.discipline
    if hasattr(athlete, 'running_focus') and athlete.running_focus:
        info["running_focus"] = athlete.running_focus
    if hasattr(athlete, 'training_phase') and athlete.training_phase:
        info["training_phase"] = athlete.training_phase
    if hasattr(athlete, 'training_days_per_week') and athlete.training_days_per_week:
        info["training_days_per_week"] = athlete.training_days_per_week
    if hasattr(athlete, 'club') and athlete.club:
        info["club"] = athlete.club
    if hasattr(athlete, 'training_experience_level') and athlete.training_experience_level:
        info["training_experience_level"] = athlete.training_experience_level
    for field in [
        "weekly_training_amount",
        "primary_goal",
        "injury_constraints",
        "best_5k_time",
        "best_alt_distance",
        "best_alt_time",
        "easy_pace",
        "threshold_pace",
        "training_surface",
        "tempo_model_runner_key",
        "response_notes",
        "best_60m_time",
        "best_100m_time",
        "best_200m_time",
        "primary_sprint_event",
    ]:
        value = getattr(athlete, field, None)
        if value:
            info[field] = value
    info["has_external_training_data"] = bool(getattr(athlete, 'has_external_training_data', False))
    logs = list(getattr(athlete, 'logs', []) or [])
    planned_sessions = list(getattr(athlete, 'planned_sessions', []) or [])
    info["recent_log_count"] = len(logs[-28:])
    info["planned_session_count"] = len(planned_sessions)
    info["experience_level"] = "nybörjare"
    info["performance_level"] = "utvecklande"

    # Hämta tävlingsresultat om de finns
    name = getattr(athlete, 'name', None)
    birth_year = getattr(athlete, 'birth_year', None)
    club = getattr(athlete, 'club', None)
    if name and birth_year and club:
        try:
            from competition_results import get_results_summary
            summary = get_results_summary(name, birth_year, club)
            if summary.get('found'):
                info["competition_results"] = {
                    "total_results": summary["total_results"],
                    "events": summary["events"],
                    "personal_bests": summary["personal_bests"],
                    "recent_results": summary["recent_results"],
                }
                info["performance_level"] = "tävlingsaktiv"
        except Exception:
            pass  # Tävlingsresultat är valfritt — fortsätt utan om det misslyckas

    if info.get("competition_results", {}).get("total_results", 0) >= 3:
        info["experience_level"] = "tävlingsaktiv"
    elif info.get("training_experience_level") == "jag är ny till att träna":
        info["experience_level"] = "nybörjare"
    elif info["recent_log_count"] >= 8 or info["planned_session_count"] >= 12:
        info["experience_level"] = "van"

    if info.get("competition_results", {}).get("personal_bests"):
        info["performance_level"] = "tävlingsaktiv"
    elif info["recent_log_count"] >= 8:
        info["performance_level"] = "etablerad"

    running_type = info.get("running_focus") or DISCIPLINE_TO_RUNNING.get(info.get("discipline", ""), "medel")
    pace_model = _build_pace_model(info, running_type)
    if pace_model:
        info["pace_model"] = pace_model

    return info


def generate_week_schedule(
    athlete,
    db,
    week_start: Optional[date] = None,
    use_rag: bool = True,
    fallback_reason_override: str = "",
) -> list:
    """
    Generera ett veckoschema för en atlet och spara det i databasen.
    Använder RAG + Claude API om tillgängligt, annars regelbaserade mallar.

    Args:
        athlete: Athlete-objekt
        db: DataStore-instans
        week_start: Startdatum (måndag). Om None, nästa måndag.
        use_rag: Försök använda RAG (True) eller enbart regler (False)
        fallback_reason_override: Exakt orsak som ska användas om ett tidigare
            högre nivå-fel redan har triggat fallback

    Returns:
        Lista med skapade PlannedSession-objekt
    """
    if week_start is None:
        today = date.today()
        # Hitta nästa måndag (eller idag om det är måndag)
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0 and today.weekday() == 0:
            week_start = today
        else:
            week_start = today + timedelta(days=days_until_monday if days_until_monday > 0 else 7)

    # Bestäm löpkategori
    running_type = getattr(athlete, 'running_focus', '') or DISCIPLINE_TO_RUNNING.get(athlete.discipline, "medel")
    phase = getattr(athlete, 'training_phase', 'grundträning')
    days_per_week = getattr(athlete, 'training_days_per_week', 4)

    # Hämta passmallar för denna gren och fas (fallback)
    category_workouts = RUNNING_WORKOUTS.get(running_type, RUNNING_WORKOUTS["medel"])
    phase_workouts = category_workouts.get(phase, category_workouts["grundträning"])

    # Hämta veckotemplet
    week_template = get_week_template(days_per_week)

    # Atletens info för RAG (inkl. tävlingsresultat om de finns)
    athlete_info = _build_athlete_info(athlete)

    # ===== FÖRSÖK RAG: HELA VECKAN I ETT CLAUDE-ANROP =====
    rag_week = None
    rag_failure_reason = ""
    if use_rag:
        try:
            from rag_knowledge import get_retriever, generate_week_plan_rag, resolve_allowed_doc_keys
            rag_retriever = get_retriever()
            if rag_retriever.chunks:
                doc_keys = resolve_allowed_doc_keys(getattr(athlete, 'rag_documents', None), running_type)
                rag_week = generate_week_plan_rag(
                    discipline=running_type,
                    phase=phase,
                    days_per_week=days_per_week,
                    retriever=rag_retriever,
                    athlete_info=athlete_info,
                    allowed_doc_keys=doc_keys,
                )
                if rag_week and not rag_week.get("plan"):
                    rag_failure_reason = rag_week.get("error", "")
                elif not rag_week:
                    rag_failure_reason = "RAG returnerade inget användbart veckoschema"
            else:
                print("⚠️ RAG: Ingen kunskapsbas laddad, använder regelbaserade mallar")
                rag_failure_reason = "Ingen kunskapsbas kunde laddas"
        except Exception as e:
            print(f"⚠️ RAG ej tillgängligt: {e}")
            rag_failure_reason = f"RAG ej tillgängligt: {e}"

    created_sessions = []

    # ===== OM RAG LYCKADES: Spara RAG-genererade pass =====
    if rag_week and rag_week.get("plan"):
        rag_sessions = rag_week.get("plan", [])
        rag_metadata = rag_week.get("metadata", {})
        coach_notes = rag_metadata.get("coach_notes", f"Planstatus: {rag_metadata.get('status', 'RAG-genererad')}")
        pace_model = athlete_info.get("pace_model", {})
        # Mappning från dagnamn till nummer i veckan (måndag = 0)
        day_map = {
            "Måndag": 0, "Tisdag": 1, "Onsdag": 2,
            "Torsdag": 3, "Fredag": 4, "Lördag": 5, "Söndag": 6
        }
        for session_data in rag_sessions:
            day_name = session_data.get("day_name", "Måndag")
            day_offset = day_map.get(day_name, 0)
            session_date = week_start + timedelta(days=day_offset)

            description = session_data.get("description", "")
            description = _normalize_pace_text_to_min_per_km(description)
            pace_hint, pace_source, pace_assumptions = _pace_hint_for_session(
                session_name=session_data.get("name", ""),
                session_type=session_data.get("type", ""),
                intensity=session_data.get("intensity", ""),
                description=description,
                pace_model=pace_model,
            )
            exercises = [{
                "id": "ai_generated",
                "name": "Passbeskrivning",
                "description": _append_pace_hint_to_description(description, pace_hint, pace_source)
            }]
            final_description = exercises[0]["description"]
            distribution = estimate_intensity_distribution(
                session_name=session_data.get("name", "AI-pass"),
                session_type=session_data.get("type", "uthållighet"),
                planned_duration=session_data.get("duration_min", 60),
                planned_intensity=session_data.get("intensity", "medel"),
                description=final_description,
            )

            session = db.add_planned_session(
                athlete_id=athlete.id,
                session_date=session_date,
                template_id="ai_schedule",
                session_name=session_data.get("name", "AI-pass"),
                session_type=session_data.get("type", "uthållighet"),
                planned_duration=session_data.get("duration_min", 60),
                planned_intensity=session_data.get("intensity", "medel"),
                exercises=exercises,
                coach_notes=coach_notes,
                source="ai",
                is_key_session=bool(session_data.get("is_key_session")),
                week_theme=rag_metadata.get("week_theme", ""),
                training_phase=phase,
                estimated_low_minutes=distribution["low"],
                estimated_medium_minutes=distribution["medium"],
                estimated_high_minutes=distribution["high"],
                intensity_distribution_source=distribution["source"],
                tempo_source=pace_source,
                tempo_assumptions=pace_assumptions,
            )
            if session:
                created_sessions.append(session)

    # ===== FALLBACK: REGELBASERADE MALLAR PASS FÖR PASS =====
    else:
        effective_failure_reason = rag_failure_reason or fallback_reason_override
        used_hard = 0
        used_medium = 0
        used_easy = 0
        pace_model = athlete_info.get("pace_model", {})

        key_session_assigned = False
        for day_info in week_template:
            difficulty = day_info["difficulty"]
            session_date = week_start + timedelta(days=day_info["day"])

            if difficulty == "rest":
                continue

            available = phase_workouts.get(difficulty, [])
            if not available:
                if difficulty == "hard":
                    available = phase_workouts.get("medium", phase_workouts.get("easy", []))
                elif difficulty == "medium":
                    available = phase_workouts.get("easy", [])
            if not available:
                continue

            if difficulty == "hard":
                workout = available[used_hard % len(available)]
                used_hard += 1
            elif difficulty == "medium":
                workout = available[used_medium % len(available)]
                used_medium += 1
            else:
                workout = available[used_easy % len(available)]
                used_easy += 1

            name, session_type, duration, intensity, description = workout
            description = _normalize_pace_text_to_min_per_km(description)

            pace_hint, pace_source, pace_assumptions = _pace_hint_for_session(
                session_name=name,
                session_type=session_type,
                intensity=intensity,
                description=description,
                pace_model=pace_model,
            )
            exercises = [{
                "id": "ai_generated",
                "name": "Passbeskrivning",
                "description": _append_pace_hint_to_description(description, pace_hint, pace_source)
            }]
            final_description = exercises[0]["description"]
            distribution = estimate_intensity_distribution(
                session_name=name,
                session_type=session_type,
                planned_duration=duration,
                planned_intensity=intensity,
                description=final_description,
            )

            session = db.add_planned_session(
                athlete_id=athlete.id,
                session_date=session_date,
                template_id="ai_schedule",
                session_name=name,
                session_type=session_type,
                planned_duration=duration,
                planned_intensity=intensity,
                exercises=exercises,
                coach_notes=(
                    "Planstatus: Regelbaserad fallback\n"
                    f"Veckofokus: {phase}\n"
                    "Nyckelpass: regelbaserat upplägg\n"
                    "Källor: Inga externa källor\n"
                    f"Coachförklaring: Ett säkert reservupplägg användes eftersom RAG inte kunde användas fullt ut. Orsak: {effective_failure_reason or 'okänd orsak'}."
                ),
                source="ai",
                is_key_session=(difficulty == "hard" and not key_session_assigned),
                week_theme=phase,
                training_phase=phase,
                estimated_low_minutes=distribution["low"],
                estimated_medium_minutes=distribution["medium"],
                estimated_high_minutes=distribution["high"],
                intensity_distribution_source=distribution["source"],
                tempo_source=pace_source,
                tempo_assumptions=pace_assumptions,
            )
            if session:
                created_sessions.append(session)
                if difficulty == "hard" and not key_session_assigned:
                    key_session_assigned = True

    return created_sessions or []


def generate_schedule_for_weeks(
    athlete,
    db,
    num_weeks: int = 1,
    start_date: Optional[date] = None,
    use_rag: bool = True,
    fallback_reason_override: str = "",
) -> list:
    """
    Generera schema för flera veckor (vecka för vecka).
    Används som fallback om månadsplanen misslyckas.
    """
    all_sessions = []

    if start_date is None:
        today = date.today()
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0 and today.weekday() == 0:
            start_date = today
        else:
            start_date = today + timedelta(days=days_until_monday if days_until_monday > 0 else 7)

    for week in range(num_weeks):
        week_start = start_date + timedelta(weeks=week)
        try:
            sessions = generate_week_schedule(
                athlete,
                db,
                week_start,
                use_rag=use_rag,
                fallback_reason_override=fallback_reason_override,
            ) or []
        except Exception as e:
            print(f"⚠️ Veckogenerering misslyckades för vecka {week + 1}, använder tomt reservresultat: {e}")
            sessions = []
        all_sessions.extend(sessions)

    return all_sessions or []


def _next_monday(from_date: Optional[date] = None) -> date:
    """Returnera nästa måndag från ett givet datum (eller idag)."""
    today = from_date or date.today()
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0 and today.weekday() == 0:
        return today
    return today + timedelta(days=days_until_monday if days_until_monday > 0 else 7)


def generate_month_schedule(athlete, db, start_date: Optional[date] = None, use_rag: bool = True) -> list:
    """
    Generera ett komplett månadsschema (4 veckor) för en atlet.

    Försöker använda RAG + Claude för hela månaden i ett anrop.
    Faller tillbaka på vecka-för-vecka om det misslyckas.

    Args:
        athlete: Athlete-objekt
        db: DataStore-instans
        start_date: Startdatum (måndag). Om None, nästa måndag.
        use_rag: Använd RAG + Claude API

    Returns:
        Lista med alla skapade PlannedSession-objekt
    """
    if start_date is None:
        start_date = _next_monday()

    running_type = getattr(athlete, 'running_focus', '') or DISCIPLINE_TO_RUNNING.get(athlete.discipline, "medel")
    phase = getattr(athlete, 'training_phase', 'grundträning')
    days_per_week = getattr(athlete, 'training_days_per_week', 4)

    # Atletens info för RAG (inkl. tävlingsresultat om de finns)
    athlete_info = _build_athlete_info(athlete)

    all_sessions = []
    rag_failure_reason = ""

    # ===== FÖRSÖK RAG-MÅNADSPLAN =====
    if use_rag:
        try:
            from rag_knowledge import get_retriever, generate_month_plan_rag, resolve_allowed_doc_keys
            retriever = get_retriever()

            if retriever.chunks:
                doc_keys = resolve_allowed_doc_keys(getattr(athlete, 'rag_documents', None), running_type)
                month_plan = generate_month_plan_rag(
                    discipline=running_type,
                    phase=phase,
                    days_per_week=days_per_week,
                    retriever=retriever,
                    athlete_info=athlete_info,
                    allowed_doc_keys=doc_keys,
                )
                if month_plan and not month_plan.get("plan"):
                    rag_failure_reason = month_plan.get("error", "")

                if month_plan and month_plan.get("plan"):
                    month_weeks = month_plan.get("plan") or []
                    month_metadata = month_plan.get("metadata", {})
                    pace_model = athlete_info.get("pace_model", {})
                    # Spara alla pass från alla 4 veckor i databasen
                    day_map = {
                        "Måndag": 0, "Tisdag": 1, "Onsdag": 2,
                        "Torsdag": 3, "Fredag": 4, "Lördag": 5, "Söndag": 6
                    }

                    for week_data in month_weeks:
                        week_num = week_data.get("week_number", 1)
                        week_theme = week_data.get("week_theme", "")
                        week_start = start_date + timedelta(weeks=week_num - 1)
                        coach_notes = (
                            f"{month_metadata.get('coach_notes', 'Planstatus: RAG-genererad')}\n"
                            f"Veckofokus: {week_theme or month_metadata.get('week_theme', phase)}"
                        ).strip()

                        for session_data in (week_data.get("sessions") or []):
                            day_name = session_data.get("day_name", "Måndag")
                            day_offset = day_map.get(day_name, 0)
                            session_date = week_start + timedelta(days=day_offset)

                            description = session_data.get("description", "")
                            description = _normalize_pace_text_to_min_per_km(description)
                            pace_hint, pace_source, pace_assumptions = _pace_hint_for_session(
                                session_name=session_data.get("name", ""),
                                session_type=session_data.get("type", ""),
                                intensity=session_data.get("intensity", ""),
                                description=description,
                                pace_model=pace_model,
                            )
                            exercises = [{
                                "id": "ai_generated",
                                "name": "Passbeskrivning",
                                "description": _append_pace_hint_to_description(description, pace_hint, pace_source)
                            }]
                            final_description = exercises[0]["description"]
                            distribution = estimate_intensity_distribution(
                                session_name=session_data.get("name", "AI-pass"),
                                session_type=session_data.get("type", "uthållighet"),
                                planned_duration=session_data.get("duration_min", 60),
                                planned_intensity=session_data.get("intensity", "medel"),
                                description=final_description,
                            )

                            session = db.add_planned_session(
                                athlete_id=athlete.id,
                                session_date=session_date,
                                template_id="ai_schedule",
                                session_name=session_data.get("name", "AI-pass"),
                                session_type=session_data.get("type", "uthållighet"),
                                planned_duration=session_data.get("duration_min", 60),
                                planned_intensity=session_data.get("intensity", "medel"),
                                exercises=exercises,
                                coach_notes=coach_notes,
                                source="ai",
                                is_key_session=bool(session_data.get("is_key_session")),
                                week_theme=week_theme or month_metadata.get("week_theme", ""),
                                training_phase="återhämtning" if "återhämt" in (week_theme or "").lower() else phase,
                                estimated_low_minutes=distribution["low"],
                                estimated_medium_minutes=distribution["medium"],
                                estimated_high_minutes=distribution["high"],
                                intensity_distribution_source=distribution["source"],
                                tempo_source=pace_source,
                                tempo_assumptions=pace_assumptions,
                            )
                            if session:
                                all_sessions.append(session)

                    return all_sessions or []

        except Exception as e:
            print(f"⚠️ RAG-månadsplan misslyckades, faller tillbaka på veckoplanering: {e}")
            rag_failure_reason = f"RAG-månadsplan misslyckades: {e}"

    # ===== FALLBACK: Generera 4 veckor en i taget =====
    if rag_failure_reason:
        print(f"ℹ️ Fallbackorsak: {rag_failure_reason}")
    try:
        return generate_schedule_for_weeks(
            athlete,
            db,
            num_weeks=4,
            start_date=start_date,
            use_rag=False,
            fallback_reason_override=rag_failure_reason,
        ) or []
    except Exception as e:
        print(f"⚠️ Veckovis fallback misslyckades för månadsplan: {e}")
        return []
