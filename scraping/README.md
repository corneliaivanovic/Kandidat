# Friidrottsstatistik-verktyget

Hämtar resultat automatiskt från friidrottsstatistik.se (Göteborgs distrikt).

## Vad behövs?

1. **Python 3** (finns redan på de flesta Mac/Linux-datorer)
2. **requests-paketet**: kör `pip3 install requests` i terminalen

## Kommandon

Öppna Terminal (Mac) eller Kommandotolken (Windows) och navigera till denna mapp.

### Hämta alla resultat (inne + ute, alla grenar, 2026)
```
python3 friidrottsstatistik-api.py scrape
```
Sparar en JSON-fil med alla resultat i samma mapp.

### Sök en atlet
```
python3 friidrottsstatistik-api.py search "Anna Svensson"
```

### Hämta en atletes fullständiga profil
```
python3 friidrottsstatistik-api.py athlete 294270
```
(Numret hittar du i sökresultaten)

## Filen som redan finns

`friidrottsstatistik-goteborg-2026.json` innehåller alla resultat som redan hämtats.
Du kan öppna den i valfri texteditor eller ladda in den i Excel/Google Sheets.

## JSON-strukturen

Varje resultat ser ut ungefär så här:
```json
{
  "event": "K 60 m",
  "ranking": 1,
  "result": "7.85",
  "name": "Anna Exempelsson",
  "birth_year": "2005",
  "club": "IFK Göteborg",
  "competition": "Stenhammarloppet",
  "date": "2026-01-15",
  "indoor": true
}
```

## Tips

- Vill du ha datan i Excel? Öppna JSON-filen i Google Sheets via "Importera" eller använd ett gratis online-verktyg som https://json-csv.com
- Du kan filtrera datan i Python, Excel, eller vilken chattbot som helst (ChatGPT, Claude etc.)
