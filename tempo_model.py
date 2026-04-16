"""
Garmin-baserad tempomodell för medel- och distanspass.

Modellen bygger på koefficienter och personliga offsets från den delade
GEE-notebooken i tempo_model_repo. Den används som ett extra tempolager
ovanpå AI-planeringen och ersätter inte RAG- eller fallbacklogiken.
"""

from __future__ import annotations

from typing import Optional
import re


TEMPO_MODEL_RUNNERS = [
    "Ebba 3",
    "Fabian",
    "Daniel",
    "Daniel 53",
    "Viktor",
    "Olle",
    "John",
    "Erik 52",
    "Jan 50",
    "Fredrik 37",
]

_INTERCEPT = 551.5705
_STIGNING_COEF = 1.0270
_NEDFOR_COEF = 2.6847
_IF_COEF = -301.6413

_RUNNER_OFFSETS = {
    "Ebba 3": 59.599417,
    "Fabian": 78.625447,
    "Daniel": 60.669021,
    "Daniel 53": 7.087680,
    "Viktor": 67.477308,
    "Olle": -28.380656,
    "John": -26.457450,
    "Erik 52": 9.496869,
    "Jan 50": 2.746194,
    "Fredrik 37": -40.110421,
}

_SURFACE_PROFILE = {
    "bana": (0.0, 0.0),
    "löpband": (0.0, 0.0),
    "väg": (5.0, 5.0),
    "terräng": (20.0, 20.0),
    "kuperat": (35.0, 35.0),
}


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


def get_surface_profile(training_surface: str) -> tuple[float, float]:
    return _SURFACE_PROFILE.get((training_surface or "").strip().lower(), (5.0, 5.0))


def infer_if(
    session_name: str,
    session_type: str,
    intensity: str,
    description: str,
) -> float:
    description_text = description or ""
    text = " ".join([
        session_name or "",
        session_type or "",
        intensity or "",
        description_text,
    ]).lower()
    main_work_text = " ".join([
        (session_name or "").lower(),
        _extract_main_work_text(description_text),
    ]).strip()
    rep_distance = _extract_rep_distance(main_work_text or text)

    is_threshold_like = any(token in main_work_text for token in [
        "tröskel", "tröskelfart", "snabbdistans", "tempolöp", "tempopass"
    ])
    is_aerobic_zone = any(token in main_work_text for token in [
        "aerob zon", "zon 2", "70-80%", "70–80%"
    ])

    if is_aerobic_zone:
        return 0.80
    if is_threshold_like:
        return 0.90
    if "fartlek" in main_work_text:
        return 0.86
    if rep_distance and rep_distance >= 1000:
        return 0.93
    if rep_distance and rep_distance >= 600:
        return 0.91
    if rep_distance:
        return 0.89
    if intensity == "hög":
        return 0.92
    if intensity == "medel":
        return 0.84

    if any(token in text for token in ["återhämt", "aktiv vila", "mycket lugn", "rörlighet"]):
        return 0.72
    if any(token in text for token in ["lugn", "jogg", "distans", "zon 1", "zon 2"]):
        return 0.78
    return 0.78


def predict_seconds_per_km(
    if_val: float,
    stigning_per_km: float,
    nedfor_per_km: float,
    runner_key: str = "",
) -> dict:
    runner_offset = _RUNNER_OFFSETS.get((runner_key or "").strip(), 0.0)
    base_seconds = (
        _INTERCEPT
        + (_IF_COEF * float(if_val))
        + (_STIGNING_COEF * float(stigning_per_km))
        + (_NEDFOR_COEF * float(nedfor_per_km))
    )
    final_seconds = max(150.0, base_seconds + runner_offset)
    source = "garmin_model_offset" if runner_offset else "garmin_model_population"
    return {
        "seconds_per_km": final_seconds,
        "offset_seconds": runner_offset,
        "source": source,
    }


def predict_session_tempo(
    session_name: str,
    session_type: str,
    intensity: str,
    description: str,
    training_surface: str = "",
    runner_key: str = "",
) -> dict:
    if_val = infer_if(session_name, session_type, intensity, description)
    stigning, nedfor = get_surface_profile(training_surface)
    prediction = predict_seconds_per_km(
        if_val=if_val,
        stigning_per_km=stigning,
        nedfor_per_km=nedfor,
        runner_key=runner_key,
    )

    text = " ".join([
        session_name or "",
        session_type or "",
        intensity or "",
        description or "",
    ]).lower()
    rep_distance = _extract_rep_distance(text)

    main_work_text = " ".join([
        (session_name or "").lower(),
        _extract_main_work_text(description),
    ]).strip()

    is_threshold_like = any(token in main_work_text for token in [
        "tröskel", "tröskelfart", "snabbdistans", "tempolöp", "tempopass"
    ])
    is_aerobic_zone = any(token in main_work_text for token in [
        "aerob zon", "zon 2", "70-80%", "70–80%"
    ])

    if is_threshold_like:
        spread = 0.02
    elif rep_distance:
        spread = 0.025
    elif intensity == "hög":
        spread = 0.025
    elif any(token in text for token in ["återhämt", "lugn", "jogg"]):
        spread = 0.03
    else:
        spread = 0.03

    center = prediction["seconds_per_km"]
    rep_adjustment = 1.0
    if rep_distance:
        if is_threshold_like and rep_distance >= 1000:
            rep_adjustment = 0.97
        elif is_threshold_like:
            rep_adjustment = 0.965
        elif rep_distance >= 1000:
            rep_adjustment = 0.96
        elif rep_distance >= 600:
            rep_adjustment = 0.95
        else:
            rep_adjustment = 0.94
    elif is_aerobic_zone:
        rep_adjustment = 1.015

    center *= rep_adjustment
    low_seconds = center * (1.0 - spread)
    high_seconds = center * (1.0 + spread)

    prediction.update({
        "if": if_val,
        "stigning_per_km": stigning,
        "nedfor_per_km": nedfor,
        "low_seconds_per_km": low_seconds,
        "high_seconds_per_km": high_seconds,
        "rep_distance": rep_distance,
        "rep_adjustment": rep_adjustment,
    })
    return prediction
