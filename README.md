# Träningsplattform för Friidrott - Prototyp

## Vad är detta?
En prototyp för ett AI-drivet träningsstöd där coachen får:
- Veckosammanfattning och dagsformsprognos för sina idrottare
- AI-genererade veckoplanförslag kopplade till en övningsbank
- Snabb och enkel planering

## Kom igång

### 1. Installera beroenden
```bash
pip install -r requirements.txt
```

### 2. Konfigurera OpenAI API (valfritt)
Skapa en fil `.env` med:
```
OPENAI_API_KEY=din-api-nyckel-här
```
Om du inte har en API-nyckel fungerar prototypen ändå med mock-data.

### 3. Starta appen
```bash
python app.py
```

### 4. Öppna i webbläsaren
Gå till: http://localhost:5000

## Struktur
- `app.py` - Huvudapplikationen (Flask)
- `models.py` - Datamodeller (idrottare, pass, logg)
- `readiness.py` - Readiness-score beräkning
- `ai_summary.py` - AI-veckosammanfattning
- `exercise_bank.py` - Övnings- och passbank
- `templates/` - HTML-mallar
- `static/` - CSS och JavaScript
