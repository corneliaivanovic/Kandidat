"""
AI-veckosammanfattning.
Genererar textsammanfattning och rekommendationer med Claude API.
Med caching för att undvika onödiga API-anrop.
"""

import os
import hashlib
from pathlib import Path
from models import Athlete
from readiness import calculate_readiness, get_week_trend

# Ladda miljövariabler från .env-fil
def load_env_file():
    """Ladda .env-fil manuellt för att säkerställa att det fungerar."""
    env_paths = [
        Path(__file__).parent / '.env',
        Path('.env'),
    ]
    for env_path in env_paths:
        if env_path.exists():
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if '=' in line and not line.startswith('#'):
                        key, value = line.split('=', 1)
                        os.environ[key] = value
            break

load_env_file()

# Försök importera Anthropic
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except Exception:
    ANTHROPIC_AVAILABLE = False


# ============================================================
# CACHE FÖR AI-SAMMANFATTNINGAR
# Sparar AI-svar och återanvänder dem tills data ändras
# ============================================================

_summary_cache: dict[int, dict] = {}  # athlete_id -> {"hash": str, "summary": dict}


def _calculate_data_hash(athlete: Athlete) -> str:
    """
    Beräkna en hash baserat på idrottarens data.
    Om hashen ändras betyder det att ny data har lagts till.
    """
    logs = athlete.get_logs_last_n_days(30)
    injuries = athlete.get_active_injuries()

    # Skapa en sträng av relevant data
    data_string = f"{athlete.id}:{athlete.name}:{athlete.discipline}:"
    data_string += f"logs:{len(logs)}:"

    # Inkludera senaste loggens datum och data
    if logs:
        latest_log = max(logs, key=lambda x: x.date)
        data_string += f"latest:{latest_log.date}:{latest_log.load}:"

    # Inkludera skador
    data_string += f"injuries:{len(injuries)}:"
    for inj in injuries:
        data_string += f"{inj.body_part}:{inj.status}:"

    # Returnera hash
    return hashlib.md5(data_string.encode()).hexdigest()


def _get_cached_summary(athlete_id: int, data_hash: str) -> dict | None:
    """Hämta cachad sammanfattning om den finns och är aktuell."""
    if athlete_id in _summary_cache:
        cached = _summary_cache[athlete_id]
        if cached["hash"] == data_hash:
            return cached["summary"]
    return None


def _cache_summary(athlete_id: int, data_hash: str, summary: dict):
    """Spara sammanfattning i cache."""
    _summary_cache[athlete_id] = {
        "hash": data_hash,
        "summary": summary
    }


def invalidate_cache(athlete_id: int = None):
    """
    Rensa cache. Anropas när data ändras.
    Om athlete_id är None, rensas all cache.
    """
    global _summary_cache
    if athlete_id is None:
        _summary_cache = {}
    elif athlete_id in _summary_cache:
        del _summary_cache[athlete_id]


def generate_week_summary(athlete: Athlete, use_ai: bool = False) -> dict:
    """
    Generera en veckosammanfattning för en idrottare.
    Använder cache för att undvika onödiga API-anrop.

    Args:
        athlete: Idrottaren att generera sammanfattning för
        use_ai: Om True, använd Claude API. Om False, använd snabb regelbaserad logik.
    """
    # Kolla om vi har en cachad version som fortfarande är giltig
    if use_ai:
        data_hash = _calculate_data_hash(athlete)
        cached = _get_cached_summary(athlete.id, data_hash)
        if cached:
            # Data har inte ändrats, returnera cachad version
            return cached

    readiness = calculate_readiness(athlete)
    trend = get_week_trend(athlete)

    # Samla data för sammanfattning
    logs_7d = athlete.get_logs_last_n_days(7)
    session_counts = athlete.get_session_count_by_type(7)

    # Hämta aktiva skador
    active_injuries = athlete.get_active_injuries()
    injuries_text = ", ".join([f"{inj.body_part} ({inj.severity})" for inj in active_injuries]) if active_injuries else "Inga"

    context = {
        "name": athlete.name,
        "discipline": athlete.discipline,
        "sessions_this_week": len(logs_7d),
        "total_load": readiness.acute_load,
        "avg_load_4w": readiness.chronic_load,
        "acwr": readiness.acwr,
        "readiness_score": readiness.score,
        "readiness_level": readiness.level,
        "session_types": session_counts,
        "recommendation": readiness.recommendation,
        "injuries": injuries_text,
        "recent_logs": logs_7d[-5:] if logs_7d else []
    }

    # Använd API endast om explicit begärt (use_ai=True)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if use_ai and ANTHROPIC_AVAILABLE and api_key:
        summary = _generate_with_claude(context, api_key)
    else:
        summary = _generate_fallback(context)

    # Beräkna total duration
    total_duration = sum(log.duration_minutes for log in logs_7d)
    total_load = sum(log.load for log in logs_7d)

    result = {
        "summary": summary["text"],
        "ai_text": summary["text"],
        "next_focus": summary["next_focus"],
        "alternatives": summary["alternatives"],
        "readiness": {
            "score": readiness.score,
            "level": readiness.level,
            "message": readiness.message
        },
        "trend": trend,
        "session_types": session_counts,
        "total_sessions": len(logs_7d),
        "total_duration": total_duration,
        "total_load": total_load
    }

    # Spara i cache om vi använde AI
    if use_ai:
        data_hash = _calculate_data_hash(athlete)
        _cache_summary(athlete.id, data_hash, result)

    return result


def generate_coach_action_items(athletes_data: list, use_ai: bool = False) -> list[dict]:
    """
    Generera prioriterade åtgärder för coachen.

    Args:
        athletes_data: Lista med idrottardata
        use_ai: Om True, använd Claude API. Om False, använd snabb regelbaserad logik.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")

    if use_ai and ANTHROPIC_AVAILABLE and api_key and athletes_data:
        return _generate_action_items_with_claude(athletes_data, api_key)
    else:
        return _generate_action_items_fallback(athletes_data)


def _generate_with_claude(context: dict, api_key: str) -> dict:
    """Generera sammanfattning med Claude API."""
    try:
        client = anthropic.Anthropic(api_key=api_key)

        # Formatera senaste pass
        recent_logs_text = ""
        if context["recent_logs"]:
            logs = []
            for log in context["recent_logs"]:
                logs.append(f"- {log.date}: {log.session_type} ({log.duration_minutes}min, RPE {log.rpe})")
            recent_logs_text = "\n".join(logs)
        else:
            recent_logs_text = "Inga loggade pass"

        prompt = f"""Du är en erfaren friidrottstränare. Analysera denna idrottares vecka och ge rekommendationer.

IDROTTARDATA:
- Namn: {context['name']}
- Gren: {context['discipline']}
- Antal pass denna vecka: {context['sessions_this_week']}
- Total belastning (session-RPE): {context['total_load']}
- Genomsnittlig veckobelastning (4v): {context['avg_load_4w']}
- ACWR (acute:chronic ratio): {context['acwr']:.2f}
- Träningsberedskap: {context['readiness_score']}/100 ({context['readiness_level']})
- Aktiva skador: {context['injuries']}
- Passfördelning: {context['session_types']}

SENASTE PASS:
{recent_logs_text}

UPPGIFT:
Skriv en kort, personlig veckosammanfattning (2-3 meningar) som:
1. Sammanfattar hur veckan har varit
2. Ger ett konkret fokusområde för nästa vecka
3. Tar hänsyn till ACWR och eventuella skador

Svara på svenska. Var konkret, positiv och handlingsinriktad. Använd idrottarens namn."""

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )

        text = response.content[0].text

        return {
            "text": text,
            "next_focus": _get_recommended_focus_with_ai(context, api_key),
            "alternatives": _get_alternative_focuses(context)
        }

    except Exception as e:
        print(f"Claude API error: {e}")
        return _generate_fallback(context)


def _get_recommended_focus_with_ai(context: dict, api_key: str) -> dict:
    """Få AI-genererad rekommendation för nästa fokus."""
    try:
        client = anthropic.Anthropic(api_key=api_key)

        prompt = f"""Baserat på denna data, vad bör idrottaren fokusera på härnäst?

- Gren: {context['discipline']}
- ACWR: {context['acwr']:.2f}
- Readiness: {context['readiness_level']}
- Skador: {context['injuries']}
- Passtyper senaste veckan: {context['session_types']}

Svara med ETT fokusområde. Välj mellan: vila, teknik, uthållighet, styrka, snabbhet.
Ge svaret i detta format (på svenska):
FOKUS: [typ]
RUBRIK: [kort rubrik, 2-3 ord]
BESKRIVNING: [en mening om vad som bör göras]
INTENSITET: [låg/medel/hög]"""

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}]
        )

        text = response.content[0].text

        # Parsa svaret
        focus_type = "teknik"
        label = "Teknikträning"
        description = "Grenspecifik teknikträning"
        intensity = "medel"

        for line in text.split('\n'):
            line = line.strip()
            if line.startswith('FOKUS:'):
                focus_type = line.replace('FOKUS:', '').strip().lower()
            elif line.startswith('RUBRIK:'):
                label = line.replace('RUBRIK:', '').strip()
            elif line.startswith('BESKRIVNING:'):
                description = line.replace('BESKRIVNING:', '').strip()
            elif line.startswith('INTENSITET:'):
                intensity = line.replace('INTENSITET:', '').strip().lower()

        return {
            "type": focus_type,
            "label": label,
            "description": description,
            "intensity": intensity
        }

    except Exception as e:
        print(f"Focus AI error: {e}")
        return _get_recommended_focus(context)


def _generate_action_items_with_claude(athletes_data: list, api_key: str) -> list[dict]:
    """Generera action items med Claude API."""
    try:
        client = anthropic.Anthropic(api_key=api_key)

        # Bygg översikt av alla idrottare
        athletes_overview = []
        for data in athletes_data:
            athlete = data['athlete']
            readiness = data['readiness']
            days_since = data['days_since_log']
            injuries = athlete.get_active_injuries()

            athletes_overview.append(
                f"- {athlete.name} ({athlete.discipline}): "
                f"ACWR {readiness.acwr:.2f}, "
                f"Readiness: {readiness.level}, "
                f"Dagar sedan logg: {days_since}, "
                f"Skador: {len(injuries)}"
            )

        athletes_text = "\n".join(athletes_overview)

        prompt = f"""Du är en coach som ska prioritera sina idrottare. Analysera denna översikt och ge max 5 konkreta åtgärder.

IDROTTARE:
{athletes_text}

REGLER:
- Röd readiness eller ACWR > 1.5 = hög prioritet (risk för överbelastning)
- Ej loggat på 3+ dagar = medium prioritet (behöver uppföljning)
- Gul readiness = låg prioritet (håll koll)
- Aktiva skador = alltid relevant att följa upp

Svara med max 5 åtgärder i detta format (en per rad):
PRIORITET|NAMN|ÅTGÄRD|ANLEDNING|FÖRSLAG

Exempel:
hög|Emma|Prata om återhämtning|ACWR på 1.6|Justera veckans plan mot lättare pass

Svara på svenska."""

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )

        text = response.content[0].text
        action_items = []

        # Skapa en mapping från namn till athlete
        name_to_athlete = {data['athlete'].name: data['athlete'] for data in athletes_data}

        for line in text.split('\n'):
            line = line.strip()
            if '|' in line and not line.startswith('PRIORITET'):
                parts = line.split('|')
                if len(parts) >= 5:
                    name = parts[1].strip()
                    # Hitta matchande athlete
                    athlete = None
                    for full_name, ath in name_to_athlete.items():
                        if name.lower() in full_name.lower() or full_name.lower().startswith(name.lower()):
                            athlete = ath
                            break

                    if athlete:
                        action_items.append({
                            'priority': parts[0].strip().lower(),
                            'athlete': athlete,
                            'action': parts[2].strip(),
                            'reason': parts[3].strip(),
                            'suggestion': parts[4].strip()
                        })

        # Om vi inte fick några items, fall tillbaka
        if not action_items:
            return _generate_action_items_fallback(athletes_data)

        # Sortera efter prioritet
        priority_order = {'hög': 0, 'medium': 1, 'låg': 2}
        action_items.sort(key=lambda x: priority_order.get(x['priority'], 3))

        return action_items[:5]

    except Exception as e:
        print(f"Action items AI error: {e}")
        return _generate_action_items_fallback(athletes_data)


def _generate_action_items_fallback(athletes_data: list) -> list[dict]:
    """Regelbaserad fallback för action items."""
    action_items = []

    for data in athletes_data:
        athlete = data['athlete']
        readiness = data['readiness']
        days_since_log = data['days_since_log']

        if readiness.level == 'röd':
            action_items.append({
                'priority': 'hög',
                'athlete': athlete,
                'action': f"Prata med {athlete.name.split()[0]} om återhämtning",
                'reason': f"ACWR på {readiness.acwr} indikerar överbelastning",
                'suggestion': "Överväg att justera veckans plan mot lättare pass"
            })
        elif days_since_log >= 3:
            action_items.append({
                'priority': 'medium',
                'athlete': athlete,
                'action': f"Följ upp med {athlete.name.split()[0]}",
                'reason': f"Har inte loggat på {days_since_log} dagar",
                'suggestion': "Kolla om allt är okej och påminn om loggning"
            })
        elif readiness.level == 'gul':
            action_items.append({
                'priority': 'låg',
                'athlete': athlete,
                'action': f"Håll koll på {athlete.name.split()[0]}",
                'reason': "Förhöjd belastning senaste veckan",
                'suggestion': "Överväg ett lättare pass i veckan"
            })

    priority_order = {'hög': 0, 'medium': 1, 'låg': 2}
    action_items.sort(key=lambda x: priority_order.get(x['priority'], 3))

    return action_items[:5]


def _generate_fallback(context: dict) -> dict:
    """Regelbaserad fallback när API inte är tillgängligt."""
    if context['acwr'] > 1.5:
        text = (
            f"{context['name']} har haft en intensiv vecka med {context['sessions_this_week']} pass "
            f"och en belastning som är {int((context['acwr']-1)*100)}% högre än genomsnittet. "
            f"Kroppen behöver återhämtning för att undvika överbelastning."
        )
    elif context['acwr'] > 1.3:
        text = (
            f"{context['name']} har tränat bra med {context['sessions_this_week']} pass denna vecka. "
            f"Belastningen är något högre än normalt (ACWR: {context['acwr']:.2f}). "
            f"Överväg att lägga in fler lättare pass kommande vecka."
        )
    elif context['acwr'] >= 0.8:
        text = (
            f"{context['name']} har haft en balanserad träningsvecka med {context['sessions_this_week']} pass. "
            f"Belastningen ligger i optimal zon (ACWR: {context['acwr']:.2f}). "
            f"Fortsätt med nuvarande upplägg."
        )
    else:
        text = (
            f"{context['name']} har tränat lättare än vanligt med {context['sessions_this_week']} pass. "
            f"Belastningen är lägre än genomsnittet (ACWR: {context['acwr']:.2f}). "
            f"Det finns utrymme att öka intensiteten om kroppen känns redo."
        )

    return {
        "text": text,
        "next_focus": _get_recommended_focus(context),
        "alternatives": _get_alternative_focuses(context)
    }


def _get_recommended_focus(context: dict) -> dict:
    """Bestäm rekommenderat fokus baserat på data (fallback)."""
    rec = context['recommendation']
    session_types = context['session_types']

    if rec == "vila":
        return {
            "type": "vila",
            "label": "Återhämtning",
            "description": "Fokus på vila och aktiv återhämtning",
            "intensity": "låg"
        }
    elif rec == "lätt":
        return {
            "type": "teknik",
            "label": "Teknik & Rörlighet",
            "description": "Lättare pass med fokus på teknik och rörlighet",
            "intensity": "låg"
        }
    elif rec == "hårt":
        if session_types.get("snabbhet", 0) < 1:
            return {
                "type": "snabbhet",
                "label": "Snabbhetsträning",
                "description": "Intensiva intervaller eller sprintträning",
                "intensity": "hög"
            }
        else:
            return {
                "type": "styrka",
                "label": "Styrketräning",
                "description": "Progressiv styrketräning för grenspecifik styrka",
                "intensity": "hög"
            }
    else:
        if session_types.get("uthållighet", 0) < 2:
            return {
                "type": "uthållighet",
                "label": "Uthållighetsträning",
                "description": "Grundläggande uthållighetspass",
                "intensity": "medel"
            }
        else:
            return {
                "type": "teknik",
                "label": "Teknikträning",
                "description": "Grenspecifik teknikträning",
                "intensity": "medel"
            }


def _get_alternative_focuses(context: dict) -> list[dict]:
    """Ge 2 alternativa fokusområden."""
    alternatives = [
        {"type": "uthållighet", "label": "Uthållighet", "description": "Längre pass med lägre intensitet", "intensity": "låg-medel"},
        {"type": "styrka", "label": "Styrka", "description": "Gym eller kroppsviktsträning", "intensity": "medel-hög"},
        {"type": "snabbhet", "label": "Snabbhet", "description": "Korta, explosiva intervaller", "intensity": "hög"},
        {"type": "teknik", "label": "Teknik", "description": "Fokus på rörelsekvalitet", "intensity": "låg"},
        {"type": "vila", "label": "Vila", "description": "Aktiv återhämtning eller vilodag", "intensity": "låg"}
    ]

    recommended = _get_recommended_focus(context)
    filtered = [a for a in alternatives if a["type"] != recommended["type"]]
    return filtered[:2]
