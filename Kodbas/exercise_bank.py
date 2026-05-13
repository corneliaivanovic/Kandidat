"""
Övnings- och passbank.
Innehåller fördefinierade övningar och passmallar för friidrott.
"""

from dataclasses import dataclass


@dataclass
class Exercise:
    """En övning i övningsbanken."""
    id: str
    name: str
    category: str  # "uthållighet", "styrka", "teknik", "snabbhet", "rörlighet"
    description: str
    duration_minutes: int
    intensity: str  # "låg", "medel", "hög"
    equipment: list[str]
    disciplines: list[str]  # Vilka grenar den passar för


@dataclass
class SessionTemplate:
    """En passmall byggd av övningar."""
    id: str
    name: str
    category: str
    description: str
    total_duration: int
    intensity: str
    exercises: list[str]  # Lista av exercise IDs
    suitable_for: list[str]  # Rekommendationer: "återhämtning", "normal", "peak"


# Övningsbank
EXERCISES = {
    # Uthållighet
    "uv01": Exercise(
        id="uv01",
        name="Lugn löpning",
        category="uthållighet",
        description="Lätt joggning i jämnt tempo. Puls ca 60-70% av max.",
        duration_minutes=30,
        intensity="låg",
        equipment=[],
        disciplines=["medel", "distans", "hopp", "kast", "mångkamp"]
    ),
    "uv02": Exercise(
        id="uv02",
        name="Tempolöpning",
        category="uthållighet",
        description="Löpning i tävlingstempo eller strax under. Puls ca 80-85% av max.",
        duration_minutes=20,
        intensity="medel",
        equipment=[],
        disciplines=["medel", "distans"]
    ),
    "uv03": Exercise(
        id="uv03",
        name="Fartlek",
        category="uthållighet",
        description="Varierad löpning med inslag av snabbare och långsammare partier.",
        duration_minutes=40,
        intensity="medel",
        equipment=[],
        disciplines=["medel", "distans", "mångkamp"]
    ),

    # Styrka
    "st01": Exercise(
        id="st01",
        name="Bålstabilitet",
        category="styrka",
        description="Plankan, sidoplankan, rygglyft och andra bålövningar.",
        duration_minutes=15,
        intensity="medel",
        equipment=["matta"],
        disciplines=["medel", "distans", "hopp", "kast", "mångkamp"]
    ),
    "st02": Exercise(
        id="st02",
        name="Benpress & Knäböj",
        category="styrka",
        description="Tung styrketräning för benen. 4x6-8 reps.",
        duration_minutes=30,
        intensity="hög",
        equipment=["skivstång", "rack"],
        disciplines=["hopp", "kast", "mångkamp"]
    ),
    "st03": Exercise(
        id="st03",
        name="Medicinbollskast",
        category="styrka",
        description="Explosiv styrka med medicinboll. Olika kastvarianter.",
        duration_minutes=20,
        intensity="hög",
        equipment=["medicinboll"],
        disciplines=["kast", "mångkamp"]
    ),
    "st04": Exercise(
        id="st04",
        name="Kroppsviktsträning",
        category="styrka",
        description="Armhävningar, dips, chins och utfallssteg.",
        duration_minutes=25,
        intensity="medel",
        equipment=[],
        disciplines=["medel", "distans", "hopp", "kast", "mångkamp"]
    ),

    # Teknik
    "te01": Exercise(
        id="te01",
        name="Löpteknik ABC",
        category="teknik",
        description="Skipping, knälyft, hälar i bak, löpskola.",
        duration_minutes=20,
        intensity="låg",
        equipment=[],
        disciplines=["medel", "distans", "mångkamp"]
    ),
    "te02": Exercise(
        id="te02",
        name="Hoppteknik",
        category="teknik",
        description="Grenspecifik hoppteknik: ansats, avhopp, landning.",
        duration_minutes=30,
        intensity="medel",
        equipment=["hoppmatta", "ribba"],
        disciplines=["hopp", "mångkamp"]
    ),
    "te03": Exercise(
        id="te03",
        name="Kastteknik",
        category="teknik",
        description="Grenspecifik kastteknik med lätt redskap.",
        duration_minutes=30,
        intensity="medel",
        equipment=["kula", "diskus", "spjut"],
        disciplines=["kast", "mångkamp"]
    ),
    "te04": Exercise(
        id="te04",
        name="Startträning",
        category="teknik",
        description="Starthålsträning och reaktionsövningar.",
        duration_minutes=25,
        intensity="medel",
        equipment=["startblock"],
        disciplines=["mångkamp"]
    ),

    # Snabbhet
    "sn01": Exercise(
        id="sn01",
        name="Flygande sprinter",
        category="snabbhet",
        description="10-30m sprinter med flygande start. Full intensitet.",
        duration_minutes=20,
        intensity="hög",
        equipment=[],
        disciplines=["hopp", "mångkamp"]
    ),
    "sn02": Exercise(
        id="sn02",
        name="Accelerationssprinter",
        category="snabbhet",
        description="20-40m sprinter från stillastående. Fokus på acceleration.",
        duration_minutes=25,
        intensity="hög",
        equipment=["startblock"],
        disciplines=["mångkamp"]
    ),
    "sn03": Exercise(
        id="sn03",
        name="Intervaller 200m",
        category="snabbhet",
        description="6-8 x 200m med 2-3 min vila. 90-95% intensitet.",
        duration_minutes=35,
        intensity="hög",
        equipment=[],
        disciplines=["medel", "mångkamp"]
    ),

    # Rörlighet
    "ro01": Exercise(
        id="ro01",
        name="Dynamisk uppvärmning",
        category="rörlighet",
        description="Dynamisk stretching och rörlighetsövningar.",
        duration_minutes=15,
        intensity="låg",
        equipment=[],
        disciplines=["medel", "distans", "hopp", "kast", "mångkamp"]
    ),
    "ro02": Exercise(
        id="ro02",
        name="Yoga/Stretching",
        category="rörlighet",
        description="Längre stretchingpass för återhämtning.",
        duration_minutes=30,
        intensity="låg",
        equipment=["matta"],
        disciplines=["medel", "distans", "hopp", "kast", "mångkamp"]
    ),
}


# Passmallar
SESSION_TEMPLATES = {
    # Återhämtningspass
    "rec01": SessionTemplate(
        id="rec01",
        name="Aktiv återhämtning",
        category="vila",
        description="Lätt pass för att främja återhämtning utan att belasta.",
        total_duration=45,
        intensity="låg",
        exercises=["ro01", "uv01", "ro02"],
        suitable_for=["återhämtning"]
    ),
    "rec02": SessionTemplate(
        id="rec02",
        name="Rörlighet & Bål",
        category="vila",
        description="Fokus på rörlighet och bålstabilitet.",
        total_duration=40,
        intensity="låg",
        exercises=["ro01", "st01", "ro02"],
        suitable_for=["återhämtning", "normal"]
    ),

    # Uthållighetspass
    "end01": SessionTemplate(
        id="end01",
        name="Grundläggande uthållighet",
        category="uthållighet",
        description="Lugn löpning för att bygga aerob bas.",
        total_duration=50,
        intensity="låg",
        exercises=["ro01", "uv01", "st01"],
        suitable_for=["normal"]
    ),
    "end02": SessionTemplate(
        id="end02",
        name="Fartlekspass",
        category="uthållighet",
        description="Varierad löpning med tempoväxlingar.",
        total_duration=60,
        intensity="medel",
        exercises=["ro01", "uv03", "ro02"],
        suitable_for=["normal", "peak"]
    ),

    # Styrkepass
    "str01": SessionTemplate(
        id="str01",
        name="Benträning",
        category="styrka",
        description="Tung styrketräning med fokus på ben.",
        total_duration=60,
        intensity="hög",
        exercises=["ro01", "st02", "st01"],
        suitable_for=["normal", "peak"]
    ),
    "str02": SessionTemplate(
        id="str02",
        name="Explosiv styrka",
        category="styrka",
        description="Explosiv styrka med medicinboll och plyometri.",
        total_duration=45,
        intensity="hög",
        exercises=["ro01", "st03", "st04"],
        suitable_for=["normal", "peak"]
    ),

    # Teknikpass
    "tec01": SessionTemplate(
        id="tec01",
        name="Löpteknik",
        category="teknik",
        description="Fokus på löpteknik och koordination.",
        total_duration=50,
        intensity="låg",
        exercises=["ro01", "te01", "uv01"],
        suitable_for=["återhämtning", "normal"]
    ),
    "tec02": SessionTemplate(
        id="tec02",
        name="Grenspecifik teknik",
        category="teknik",
        description="Teknikträning för din gren.",
        total_duration=60,
        intensity="medel",
        exercises=["ro01", "te01", "te02"],  # Anpassas efter gren
        suitable_for=["normal"]
    ),

    # Snabbhetspass
    "spd01": SessionTemplate(
        id="spd01",
        name="Sprintträning",
        category="snabbhet",
        description="Korta sprinter med full intensitet.",
        total_duration=50,
        intensity="hög",
        exercises=["ro01", "te01", "sn01", "sn02"],
        suitable_for=["peak"]
    ),
    "spd02": SessionTemplate(
        id="spd02",
        name="Intervaller",
        category="snabbhet",
        description="Längre intervaller för snabbhetsuthållighet.",
        total_duration=60,
        intensity="hög",
        exercises=["ro01", "sn03", "ro02"],
        suitable_for=["normal", "peak"]
    ),
}


def get_exercise(exercise_id: str) -> Exercise | None:
    """Hämta en övning via ID."""
    return EXERCISES.get(exercise_id)


def get_session_template(template_id: str) -> SessionTemplate | None:
    """Hämta en passmall via ID."""
    return SESSION_TEMPLATES.get(template_id)


def get_sessions_by_category(category: str) -> list[SessionTemplate]:
    """Hämta alla passmallar av en viss kategori."""
    return [s for s in SESSION_TEMPLATES.values() if s.category == category]


def get_sessions_for_recommendation(recommendation: str) -> list[SessionTemplate]:
    """
    Hämta passmallar baserat på rekommendation.
    recommendation: "vila", "lätt", "normal", "hårt"
    """
    suitable_map = {
        "vila": ["återhämtning"],
        "lätt": ["återhämtning", "normal"],
        "normal": ["normal"],
        "hårt": ["normal", "peak"]
    }

    suitable_for = suitable_map.get(recommendation, ["normal"])

    matching = []
    for session in SESSION_TEMPLATES.values():
        if any(s in session.suitable_for for s in suitable_for):
            matching.append(session)

    return matching


def get_suggested_sessions(recommendation: str, focus_type: str) -> list[dict]:
    """
    Hämta föreslagna pass baserat på rekommendation och fokus.
    Returnerar 2-3 passförslag med detaljer.
    """
    all_matching = get_sessions_for_recommendation(recommendation)

    # Prioritera pass som matchar fokustyp
    primary = [s for s in all_matching if s.category == focus_type]
    secondary = [s for s in all_matching if s.category != focus_type]

    # Ta max 3 förslag
    suggestions = primary[:2] + secondary[:1]
    if len(suggestions) < 2:
        suggestions = (primary + secondary)[:3]

    result = []
    for session in suggestions:
        exercises = [get_exercise(eid) for eid in session.exercises if get_exercise(eid)]
        result.append({
            "id": session.id,
            "name": session.name,
            "category": session.category,
            "description": session.description,
            "duration": session.total_duration,
            "intensity": session.intensity,
            "exercises": [
                {"name": ex.name, "duration": ex.duration_minutes, "description": ex.description}
                for ex in exercises
            ]
        })

    return result
