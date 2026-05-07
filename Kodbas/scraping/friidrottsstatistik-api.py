#!/usr/bin/env python3
"""
Friidrottsstatistik.se — Komplett scraper för Göteborg 2026
Hämtar alla resultat (inne + ute), sparar som JSON.
Kan även söka enskilda atleters profiler.

Användning:
  python3 friidrottsstatistik-api.py scrape          # Scrapa alla resultat → JSON
  python3 friidrottsstatistik-api.py search "Namn"   # Sök atlet
  python3 friidrottsstatistik-api.py athlete 294270   # Hämta atletprofil
  python3 friidrottsstatistik-api.py serve            # Starta enkel HTTP API
"""

import requests
import re
import json
import sys
import os
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv

# Försök hitta .env i flera ställen
script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(script_dir)  # Parent = projektmappen

# Ladda .env från projektmappen först, sen aktuell mapp
load_dotenv(os.path.join(project_dir, '.env'))
load_dotenv()  # Fallback till current directory

BASE = "https://www.friidrottsstatistik.se"
USERNAME = os.getenv('FRIIDROTTSSTATISTIK_USERNAME', '')
PASSWORD = os.getenv('FRIIDROTTSSTATISTIK_PASSWORD', '')
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


class FriidrottsScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        self.logged_in = False

    def login(self):
        """Logga in och returnera True/False."""
        if self.logged_in:
            return True
        r = self.session.get(f"{BASE}/users/login.php")
        csrf_match = re.search(r'name="csrf" value="([^"]+)"', r.text)
        if not csrf_match:
            print("Kunde inte hitta CSRF-token")
            return False

        r = self.session.post(f"{BASE}/users/login.php", data={
            'username': USERNAME,
            'password': PASSWORD,
            'remember': 'on',
            'login_hook': '1',
            'csrf': csrf_match.group(1)
        }, allow_redirects=False)

        # Hantera redirect manuellt (servern ger 411 på POST-redirect)
        if r.status_code == 302:
            loc = r.headers.get('Location', '/')
            if loc.startswith('/'):
                loc = BASE + loc
            self.session.get(loc)

        # Verifiera inloggning
        r = self.session.get(f"{BASE}/users/account.php")
        if 'Inloggad' in r.text or 'Logga ut' in r.text:
            self.logged_in = True
            return True
        return False

    def scrape_district_results(self, district="goteborg", season=2026,
                                  event="", gender=0, all_results=True):
        """
        Hämta distriktsresultat.
        
        Returns: lista med resultat-dicts
        """
        if not self.login():
            return []

        params = {
            'Ind': 1 if all_results else 0,
            'all': 1 if all_results else 0,
            'Gren': event,
            'gender': gender,
            'Season': season,
            'Agegroup': 0,
            'lang': 'swe',
            'Excel': 0,
            'resultyear': season,
        }

        url = f"{BASE}/districtpagesnew/{district}/default.php"
        r = self.session.get(url, params=params)
        return self._parse_district_html(r.text)

    def _parse_district_html(self, html):
        """Parsa distriktsresultat-HTML till strukturerad data."""
        results = []

        # Dela upp per gren (event headers)
        sections = re.split(r"<th colspan=11 class='h5'>([^<]+)</th>", html)
        current_event = "Okänd"

        for i, section in enumerate(sections):
            if i % 2 == 1:
                current_event = section.strip()
                continue

            # Dela upp i enskilda rader och parsa var och en
            rows = re.split(r'<tr\b', section)
            for row in rows:
                name_m = re.search(r"class='namn[^']*'>([^<]+)", row)
                if not name_m:
                    continue

                result_m = re.search(r"text-right'>(\d+)\.[^>]*>(\d+)\s", row)
                if not result_m:
                    continue

                club_m = re.search(r"class='klub pr-0 d-none d-lg-table-cell'>([^<]*)", row)
                venue_m = re.search(r"class='plats'><a[^>]*>([^<]*)</a>", row)
                date_m = re.search(r"</div><div>(\d+\.\d+\.\d+)</div>", row)

                # Födelseår efter namn
                namn_pos = row.find('namn')
                birth_m = re.search(r"<div>(\d{2})</div>", row[namn_pos:] if namn_pos >= 0 else "")
                birth_year = None
                if birth_m:
                    by = int(birth_m.group(1))
                    birth_year = 2000 + by if by < 50 else 1900 + by

                date_str = ""
                if date_m:
                    try:
                        parts = date_m.group(1).split('.')
                        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                        if y < 100:
                            y = 2000 + y if y < 50 else 1900 + y
                        date_str = f"{y}-{m:02d}-{d:02d}"
                    except:
                        date_str = date_m.group(1)

                results.append({
                    'event': current_event,
                    'result': f"{result_m.group(1)}.{result_m.group(2).strip()}",
                    'name': name_m.group(1).strip(),
                    'birth_year': birth_year,
                    'club': club_m.group(1).strip() if club_m else "",
                    'venue': venue_m.group(1).strip() if venue_m else "",
                    'date': date_str,
                })

        return results

    def search_athlete(self, name):
        """Sök atlet på namn. Returnerar lista med matchningar."""
        if not self.login():
            return []

        r = self.session.get(f"{BASE}/atss.php", params={'Name': name})

        athletes = []
        # Hitta alla atletlänkar
        for match in re.finditer(
            r'href="(/atswe\.php\?Sex=(\d)&ID=(\d+)[^"]*)"[^>]*>',
            r.text
        ):
            url = match.group(1)
            sex = 'M' if match.group(2) == '1' else 'K'
            athlete_id = match.group(3)

            # Hitta namnet (nästa text efter länken)
            name_match = re.search(
                rf'ID={athlete_id}[^>]*>([^<]+)',
                r.text
            )
            athlete_name = name_match.group(1).strip() if name_match else "?"

            athletes.append({
                'id': athlete_id,
                'name': athlete_name,
                'sex': sex,
                'url': BASE + url,
            })

        return athletes

    def get_athlete_profile(self, athlete_id, sex=1):
        """
        Hämta atletprofil med alla resultat.
        
        Returns: dict med atletinfo + resultat
        """
        if not self.login():
            return None

        r = self.session.get(f"{BASE}/atswe.php", params={
            'Sex': sex, 'ID': athlete_id, 'lang': 'swe'
        })

        html = r.text
        profile = {
            'id': athlete_id,
            'name': '',
            'club': '',
            'birth_year': None,
            'personal_bests': [],
            'season_results': [],
        }

        # Namn (titel)
        title = re.search(r"<title>([^<]+)", html)
        if title:
            name = title.group(1).replace('Friidrottsstatistik', '').strip()
            profile['name'] = name

        # Klubb
        club = re.search(r'class="card-title[^"]*"[^>]*>([^<]+)', html)
        if club:
            profile['club'] = club.group(1).strip()

        # Födelseår
        born = re.search(r'Född:?\s*(\d{4})', html)
        if born:
            profile['birth_year'] = int(born.group(1))

        # Personliga bästa — hitta tabell med PB:s
        pb_section = re.findall(
            r"<td[^>]*>([^<]*)</td>\s*<td[^>]*>(\d+[\.:]\d+)",
            html
        )
        seen_events = set()
        for event_name, result in pb_section:
            event_name = event_name.strip()
            if event_name and event_name not in seen_events and len(event_name) < 30:
                profile['personal_bests'].append({
                    'event': event_name,
                    'result': result,
                })
                seen_events.add(event_name)

        return profile


def scrape_all_goteborg_2026(scraper):
    """Scrapa ALLA resultat för Göteborg 2026 (inne + ute)."""
    all_data = {
        'scraped_at': datetime.utcnow().isoformat() + 'Z',
        'district': 'Göteborg',
        'season': 2026,
        'indoor': [],
        'outdoor': [],
        'athletes': {},  # Unika atleter med sammanställd data
    }

    print("Scrapar inomhusresultat (2026)...")
    indoor = scraper.scrape_district_results(
        district="goteborg", season=2026, event="", gender=0, all_results=True
    )
    all_data['indoor'] = indoor
    print(f"  → {len(indoor)} inomhusresultat")

    # Utomhus — försök med samma season men kolla om det finns data
    print("Scrapar utomhusresultat (2026)...")
    # Utomhussäsongen har ofta andra parametrar, men samma endpoint
    # Season=2026 med resultyear=2026 bör ge utomhus om det finns
    # Vi kan inte säkert skilja inne/ute via URL, men inne-säsongen
    # är det som visas för Göteborg jan-mars

    # Bygg atletindex från alla resultat
    for r in indoor:
        name = r['name']
        if name not in all_data['athletes']:
            all_data['athletes'][name] = {
                'name': name,
                'birth_year': r.get('birth_year'),
                'club': r['club'],
                'events': {},
                'total_results': 0,
            }
        athlete = all_data['athletes'][name]
        athlete['total_results'] += 1

        event = r['event']
        if event not in athlete['events']:
            athlete['events'][event] = {
                'best': r['result'],
                'all_results': [],
            }
        athlete['events'][event]['all_results'].append({
            'result': r['result'],
            'venue': r['venue'],
            'date': r['date'],
        })

        # Uppdatera bästa resultat
        try:
            current_best = float(athlete['events'][event]['best'])
            new_result = float(r['result'])
            # För sprint: lägre är bättre. För fältgrenar: högre är bättre.
            is_field = any(x in event for x in ['Höjd', 'Stav', 'Längd', 'Tresteg', 'Kula', 'Vikt', 'Diskus', 'Spjut', 'Slägga'])
            if is_field:
                if new_result > current_best:
                    athlete['events'][event]['best'] = r['result']
            else:
                if new_result < current_best:
                    athlete['events'][event]['best'] = r['result']
        except ValueError:
            pass

    # Sammanfattning
    all_data['summary'] = {
        'total_indoor_results': len(indoor),
        'unique_athletes': len(all_data['athletes']),
        'events': list(set(r['event'] for r in indoor)),
    }

    return all_data


# === Enkel HTTP API ===

class APIHandler(BaseHTTPRequestHandler):
    scraper = None
    data = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == '/':
            self.respond_json({
                'endpoints': [
                    'GET /results — Alla resultat (filtrera med ?event=M+60+m&name=Hugo)',
                    'GET /athletes — Alla unika atleter',
                    'GET /athlete?name=Hugo+Kündig — Specifik atlet med alla resultat',
                    'GET /search?name=Kündig — Sök atlet på friidrottsstatistik.se',
                    'GET /events — Lista alla grenar',
                ],
                'data_source': 'friidrottsstatistik.se',
                'district': 'Göteborg',
                'season': 2026,
            })
        elif parsed.path == '/results':
            results = self.data.get('indoor', [])
            # Filtrera
            event = params.get('event', [None])[0]
            name = params.get('name', [None])[0]
            if event:
                results = [r for r in results if event.lower() in r['event'].lower()]
            if name:
                results = [r for r in results if name.lower() in r['name'].lower()]
            self.respond_json({'count': len(results), 'results': results})
        elif parsed.path == '/athletes':
            athletes = list(self.data.get('athletes', {}).values())
            name = params.get('name', [None])[0]
            if name:
                athletes = [a for a in athletes if name.lower() in a['name'].lower()]
            self.respond_json({'count': len(athletes), 'athletes': athletes})
        elif parsed.path == '/athlete':
            name = params.get('name', [None])[0]
            if not name:
                self.respond_json({'error': 'Ange ?name=...'}, 400)
                return
            matches = {k: v for k, v in self.data.get('athletes', {}).items()
                      if name.lower() in k.lower()}
            self.respond_json({'count': len(matches), 'athletes': matches})
        elif parsed.path == '/search':
            name = params.get('name', [None])[0]
            if not name:
                self.respond_json({'error': 'Ange ?name=...'}, 400)
                return
            results = self.scraper.search_athlete(name)
            self.respond_json({'count': len(results), 'athletes': results})
        elif parsed.path == '/events':
            events = self.data.get('summary', {}).get('events', [])
            self.respond_json({'events': sorted(events)})
        else:
            self.respond_json({'error': 'Endpoint finns inte'}, 404)

    def respond_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))

    def log_message(self, format, *args):
        print(f"[API] {args[0]}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]
    scraper = FriidrottsScraper()

    if cmd == 'scrape':
        print("Loggar in...")
        if not scraper.login():
            print("Inloggning misslyckades!")
            return

        data = scrape_all_goteborg_2026(scraper)

        output_file = os.path.join(OUTPUT_DIR, 'friidrottsstatistik-goteborg-2026.json')
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"\n✓ Sparad: {output_file}")
        print(f"  {data['summary']['total_indoor_results']} resultat")
        print(f"  {data['summary']['unique_athletes']} unika atleter")
        print(f"  {len(data['summary']['events'])} grenar")

    elif cmd == 'search':
        if len(sys.argv) < 3:
            print("Användning: search <namn>")
            return
        name = ' '.join(sys.argv[2:])
        if not scraper.login():
            return
        results = scraper.search_athlete(name)
        if not results:
            print(f"Ingen hittad för: {name}")
        for a in results:
            print(f"  [{a['sex']}] {a['name']} (ID: {a['id']}) — {a['url']}")

    elif cmd == 'athlete':
        if len(sys.argv) < 3:
            print("Användning: athlete <id>")
            return
        if not scraper.login():
            return
        profile = scraper.get_athlete_profile(sys.argv[2])
        print(json.dumps(profile, ensure_ascii=False, indent=2))

    elif cmd == 'serve':
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080

        # Ladda eller scrapa data
        data_file = os.path.join(OUTPUT_DIR, 'friidrottsstatistik-goteborg-2026.json')
        if os.path.exists(data_file):
            print(f"Laddar data från {data_file}...")
            with open(data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            print("Ingen data-fil hittad, scrapar...")
            if not scraper.login():
                return
            data = scrape_all_goteborg_2026(scraper)
            with open(data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        APIHandler.scraper = scraper
        APIHandler.data = data

        server = HTTPServer(('0.0.0.0', port), APIHandler)
        print(f"\n✓ API igång på http://localhost:{port}")
        print("  Endpoints: /, /results, /athletes, /athlete, /search, /events")
        server.serve_forever()

    else:
        print(f"Okänt kommando: {cmd}")
        print(__doc__)


if __name__ == '__main__':
    main()
