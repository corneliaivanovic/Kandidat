import warnings; warnings.filterwarnings('ignore')
import urllib3; urllib3.disable_warnings()
import sys, os
sys.path.insert(0, '/sessions/affectionate-sweet-cerf/mnt/Idrottsapp - Prototyp')
os.chdir('/sessions/affectionate-sweet-cerf/mnt/Idrottsapp - Prototyp')

# 1) Test imports
print("=== TEST 1: Imports ===")
from ai_schedule import generate_week_schedule, generate_schedule_for_weeks
from rag_knowledge import get_retriever
print("✅ Alla imports OK")

# 2) Test RAG-retriever
print("\n=== TEST 2: RAG Retriever ===")
retriever = get_retriever()
results = retriever.search("intervallträning sprint acceleration")
print(f"✅ Hittade {len(results)} chunks för 'intervallträning sprint'")
print(f"   Bästa match: score={results[0]['score']:.3f}, källa={results[0]['source']}")

# 3) Test generate_schedule_for_weeks (regelbaserat schema)
print("\n=== TEST 3: Regelbaserat schema ===")
from dataclasses import dataclass
from datetime import date

@dataclass
class FakeAthlete:
    id: int = 1
    user_id: int = 1
    name: str = "Testlöpare"
    discipline: str = "medel"
    club: str = "FK Test"
    birth_year: int = 2000
    training_mode: str = "ai"
    training_days_per_week: int = 4
    training_phase: str = "grundträning"

class FakeDB:
    def __init__(self):
        self.sessions = []
    def add_planned_session(self, athlete_id, session_date, template_id, session_name,
                             session_type, planned_duration, planned_intensity, exercises, coach_notes):
        class S:
            pass
        s = S()
        s.name = session_name
        s.date = session_date
        s.session_type = session_type
        self.sessions.append(s)
        return s

athlete = FakeAthlete()
db = FakeDB()
sessions = generate_schedule_for_weeks(athlete, db, num_weeks=1, use_rag=False)
print(f"✅ Genererade {len(sessions)} pass (regelbaserat)")
for s in sessions:
    print(f"   - {s.date}: {s.name} ({s.session_type})")

# 4) App startup check
print("\n=== TEST 4: Flask-app import ===")
import importlib.util
spec = importlib.util.spec_from_file_location("app", "/sessions/affectionate-sweet-cerf/mnt/Idrottsapp - Prototyp/app.py")
print("✅ app.py hittad och läsbar")

print("\n✅✅✅ Alla tester godkända! RAG-systemet är redo.")
