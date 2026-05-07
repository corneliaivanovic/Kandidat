"""
Tävlingsresultat-modul - Hämtar och matchar resultat från friidrottsstatistik.se

Matchar idrottare baserat på:
- Namn (case-insensitive)
- Födelseår
- Klubb
"""

import os
import json
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
import unicodedata

# Sökväg till JSON-filer med resultat
RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'scraping')
DEFAULT_RESULTS_FILE = os.path.join(RESULTS_DIR, 'friidrottsstatistik-goteborg-2026.json')


@dataclass
class CompetitionResult:
    """Ett tävlingsresultat."""
    event: str
    result: str
    name: str
    birth_year: Optional[int]
    club: str
    venue: str
    date: str
    indoor: bool = True

    @property
    def result_float(self) -> Optional[float]:
        """Konvertera resultat till float för jämförelse."""
        try:
            return float(self.result)
        except ValueError:
            return None

    @property
    def formatted_date(self) -> str:
        """Formaterat datum."""
        try:
            dt = datetime.strptime(self.date, '%Y-%m-%d')
            return dt.strftime('%d %b %Y')
        except:
            return self.date


def normalize_name(name: str) -> str:
    """
    Normalisera namn för jämförelse.
    - Lowercase
    - Ta bort accenter (ü → u, etc.)
    - Trimma whitespace
    """
    if not name:
        return ""
    # Lowercase
    name = name.lower().strip()
    # Normalisera unicode (ta bort accenter)
    # NFD delar upp tecken, vi filtrerar bort combining marks
    normalized = unicodedata.normalize('NFD', name)
    ascii_name = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
    return ascii_name


def load_results_data(filepath: str = None) -> dict:
    """Ladda resultatdata från JSON-fil."""
    filepath = filepath or DEFAULT_RESULTS_FILE

    if not os.path.exists(filepath):
        return {'indoor': [], 'outdoor': [], 'athletes': {}}

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Fel vid laddning av resultat: {e}")
        return {'indoor': [], 'outdoor': [], 'athletes': {}}


def find_athlete_results(name: str, birth_year: int = None, club: str = None,
                         data: dict = None) -> list[CompetitionResult]:
    """
    Hitta alla resultat för en idrottare.

    Matchar på:
    - Namn (case-insensitive, accent-insensitive)
    - Födelseår (om angivet)
    - Klubb (om angiven, partial match)

    Args:
        name: Idrottarens namn
        birth_year: Födelseår (valfritt)
        club: Klubbnamn (valfritt)
        data: Förladdat data (annars laddas från fil)

    Returns:
        Lista med CompetitionResult
    """
    if data is None:
        data = load_results_data()

    results = []
    search_name = normalize_name(name)
    search_club = normalize_name(club) if club else None

    # Sök i indoor-resultat
    for r in data.get('indoor', []):
        result_name = normalize_name(r.get('name', ''))

        # Namn måste matcha
        if search_name not in result_name and result_name not in search_name:
            # Försök med exakt match också
            if search_name != result_name:
                continue

        # Födelseår måste matcha om angivet
        if birth_year and r.get('birth_year'):
            if r['birth_year'] != birth_year:
                continue

        # Klubb måste matcha om angiven (partial match)
        if search_club:
            result_club = normalize_name(r.get('club', ''))
            if search_club not in result_club and result_club not in search_club:
                continue

        results.append(CompetitionResult(
            event=r.get('event', ''),
            result=r.get('result', ''),
            name=r.get('name', ''),
            birth_year=r.get('birth_year'),
            club=r.get('club', ''),
            venue=r.get('venue', ''),
            date=r.get('date', ''),
            indoor=True
        ))

    # Sök i outdoor-resultat om det finns
    for r in data.get('outdoor', []):
        result_name = normalize_name(r.get('name', ''))

        if search_name not in result_name and result_name not in search_name:
            if search_name != result_name:
                continue

        if birth_year and r.get('birth_year'):
            if r['birth_year'] != birth_year:
                continue

        if search_club:
            result_club = normalize_name(r.get('club', ''))
            if search_club not in result_club and result_club not in search_club:
                continue

        results.append(CompetitionResult(
            event=r.get('event', ''),
            result=r.get('result', ''),
            name=r.get('name', ''),
            birth_year=r.get('birth_year'),
            club=r.get('club', ''),
            venue=r.get('venue', ''),
            date=r.get('date', ''),
            indoor=False
        ))

    # Sortera efter datum (senaste först)
    results.sort(key=lambda x: x.date, reverse=True)

    return results


def get_personal_bests(name: str, birth_year: int = None, club: str = None,
                       data: dict = None) -> dict[str, CompetitionResult]:
    """
    Hämta personliga rekord för varje gren.

    Returns:
        Dict med gren som nyckel och bästa resultat som värde
    """
    results = find_athlete_results(name, birth_year, club, data)

    personal_bests = {}

    for r in results:
        event = r.event

        if event not in personal_bests:
            personal_bests[event] = r
            continue

        current_best = personal_bests[event]

        # Jämför resultat
        try:
            current_value = float(current_best.result)
            new_value = float(r.result)

            # För fältgrenar (höjd, längd, kast) är högre bättre
            is_field_event = any(x in event.lower() for x in [
                'höjd', 'stav', 'längd', 'tresteg', 'kula',
                'vikt', 'diskus', 'spjut', 'slägga'
            ])

            if is_field_event:
                if new_value > current_value:
                    personal_bests[event] = r
            else:
                # För löpning är lägre bättre
                if new_value < current_value:
                    personal_bests[event] = r
        except ValueError:
            # Kan inte jämföra, behåll nuvarande
            pass

    return personal_bests


def get_results_summary(name: str, birth_year: int = None, club: str = None) -> dict:
    """
    Hämta en sammanfattning av en idrottares resultat.

    Returns:
        Dict med sammanfattande statistik
    """
    data = load_results_data()
    results = find_athlete_results(name, birth_year, club, data)
    personal_bests = get_personal_bests(name, birth_year, club, data)

    if not results:
        return {
            'found': False,
            'name': name,
            'total_results': 0,
            'events': [],
            'personal_bests': {},
            'recent_results': []
        }

    # Hämta unika grenar
    events = list(set(r.event for r in results))

    # Hämta senaste resultat (max 5)
    recent = results[:5]

    return {
        'found': True,
        'name': results[0].name,  # Använd namnet från datan
        'birth_year': results[0].birth_year,
        'club': results[0].club,
        'total_results': len(results),
        'events': sorted(events),
        'personal_bests': {
            event: {
                'result': pb.result,
                'date': pb.date,
                'venue': pb.venue
            }
            for event, pb in personal_bests.items()
        },
        'recent_results': [
            {
                'event': r.event,
                'result': r.result,
                'date': r.date,
                'venue': r.venue,
                'indoor': r.indoor
            }
            for r in recent
        ]
    }


def search_athletes(query: str, data: dict = None) -> list[dict]:
    """
    Sök efter idrottare baserat på namn.

    Returns:
        Lista med matchande idrottare (unika)
    """
    if data is None:
        data = load_results_data()

    search_query = normalize_name(query)
    athletes = {}

    for r in data.get('indoor', []) + data.get('outdoor', []):
        result_name = normalize_name(r.get('name', ''))

        if search_query in result_name:
            # Skapa unik nyckel baserat på namn + födelseår + klubb
            key = f"{r.get('name', '')}_{r.get('birth_year', '')}_{r.get('club', '')}"

            if key not in athletes:
                athletes[key] = {
                    'name': r.get('name', ''),
                    'birth_year': r.get('birth_year'),
                    'club': r.get('club', ''),
                    'result_count': 0
                }

            athletes[key]['result_count'] += 1

    # Sortera efter antal resultat
    return sorted(athletes.values(), key=lambda x: x['result_count'], reverse=True)


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    print("=== Tävlingsresultat-modul ===\n")

    # Testa med Hugo Kündig
    name = "Hugo Kündig"
    birth_year = 2006
    club = "Örgryte IS"

    print(f"Söker efter: {name} ({birth_year}, {club})")

    summary = get_results_summary(name, birth_year, club)

    if summary['found']:
        print(f"\n✓ Hittade {summary['total_results']} resultat")
        print(f"  Grenar: {', '.join(summary['events'])}")
        print("\n  Personliga rekord:")
        for event, pb in summary['personal_bests'].items():
            print(f"    {event}: {pb['result']} ({pb['date']}, {pb['venue']})")
        print("\n  Senaste resultat:")
        for r in summary['recent_results']:
            indoor_str = "inne" if r['indoor'] else "ute"
            print(f"    {r['event']}: {r['result']} ({r['date']}, {r['venue']}, {indoor_str})")
    else:
        print(f"\n✗ Inga resultat hittades för {name}")
        print("  Kör först: cd scraping && python3 friidrottsstatistik-api.py scrape")
