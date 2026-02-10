# SteuerPilot

**KI-gestützte Belegverarbeitung mit Source Grounding für DATEV Unternehmen Online**

> Middleware-Lösung: Dokumente → OCR → LangExtract (Source Grounding) → DATEV Buchungsvorschläge

## Das Problem

Steuerberater verbringen durchschnittlich **2 Stunden pro Mandant** mit der manuellen Belegverarbeitung in DATEV Unternehmen Online: Dokumente öffnen, klassifizieren, Beträge abtippen, Konten zuordnen – Beleg für Beleg.

## Die Lösung

SteuerPilot automatisiert die Belegvorverarbeitung und liefert fertige Buchungsvorschläge direkt an DATEV. Der entscheidende Unterschied: **Source Grounding** – jeder extrahierte Wert wird mit seiner exakten Position im Originaldokument verknüpft. Der Steuerberater sieht auf einen Blick, woher jede Zahl kommt.

```
Mandant scannt Belege
  → Tesseract OCR (Deutsch)
  → LangExtract + Ollama (lokal, DSGVO-konform)
    → Strukturierte Extraktion MIT Quellenreferenz
  → Maesn REST API
    → DATEV Rechnungsdatenservice 1.0
      → DATEV Unternehmen Online (Buchungsvorschläge)
        → Steuerberater: Massenverarbeitung statt Einzelbuchung
```

**Ergebnis: 2 Stunden → 15 Minuten pro Mandant**

## USPs

| Feature | SteuerPilot | DATEV Automatisierungsservice |
|---------|-------------|-------------------------------|
| Source Grounding | ✅ Jeder Wert mit Quellenreferenz | ❌ Blackbox |
| Belegtypen | Alle (Rechnungen, Lohnsteuer, Spenden, NK, §35a) | Nur Rechnungen |
| KI-Verarbeitung | Lokal (Ollama/Hetzner) – DSGVO | Azure OpenAI |
| Fehlende Belege | ✅ Proaktive Erkennung | ❌ |
| §35a-Erkennung | ✅ Automatisch Arbeitskosten | ❌ |
| SKR03 Auto-Kontierung | ✅ | ✅ (nur Rechnungen) |

## Tech Stack

- **Backend**: Python 3.11, FastAPI, SQLAlchemy, SQLite
- **OCR**: Tesseract (deutsch)
- **Extraktion**: Google LangExtract (Apache 2.0) + Ollama
- **LLM**: Llama 3.1 8B Q4_K_M (lokal, ~5 GB VRAM)
- **DATEV-Bridge**: Maesn REST API → RDS 1.0
- **Frontend**: Vanilla JS SPA (kein Build-Step)
- **Deployment**: Docker Compose für Hetzner GEX44

## Setup

### 1. Voraussetzungen
- Docker + Docker Compose
- Ollama mit `llama3.1:8b-instruct-q4_K_M` auf dem Host
- Optional: Maesn API Key (https://www.maesn.com)

### 2. Konfiguration
```bash
cp .env.example .env
# .env bearbeiten: MAESN_API_KEY eintragen
```

### 3. Starten
```bash
# Ollama Model laden (einmalig)
ollama pull llama3.1:8b-instruct-q4_K_M

# SteuerPilot starten
docker compose up -d
```

### 4. Öffnen
http://localhost:8470

## Workflow

1. **Mandant anlegen** (mit optionaler DATEV Berater-/Mandantennummer)
2. **Steuerjahr erstellen**
3. **Belege hochladen** (PDF, JPG, PNG – Drag & Drop)
4. **Automatische Verarbeitung**: OCR → Extraktion → Kontierung
5. **Prüfen**: Source-Grounding-Ansicht zeigt Herkunft jedes Wertes
6. **Freigeben** und an DATEV senden (oder CSV exportieren)

## API Endpoints

| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/dashboard` | Dashboard-Statistiken |
| GET/POST | `/api/mandanten` | Mandanten CRUD |
| GET/POST | `/api/steuerjahre` | Steuerjahre CRUD |
| POST | `/api/belege/upload/{sj_id}` | Belege hochladen |
| GET | `/api/belege/steuerjahr/{sj_id}` | Belege eines Steuerjahres |
| GET/PUT | `/api/belege/{id}` | Beleg Detail/Update |
| POST | `/api/belege/{id}/reprocess` | Beleg neu verarbeiten |
| GET | `/api/datev/status` | DATEV Verbindungsstatus |
| POST | `/api/datev/sync` | Belege an DATEV senden |
| GET | `/api/datev/export/csv/{sj_id}` | DATEV CSV Export |

## Architektur für DATEV-Pitch

```
┌─────────────────────────────────────────────────┐
│              SteuerPilot Middleware              │
│                                                 │
│  ┌──────────┐  ┌────────────┐  ┌────────────┐  │
│  │ Tesseract│→ │ LangExtract│→ │ Auto-      │  │
│  │ OCR (deu)│  │ + Ollama   │  │ Kontierung │  │
│  └──────────┘  │            │  │ SKR03/04   │  │
│                │ SOURCE     │  └────────────┘  │
│                │ GROUNDING  │        ↓         │
│                └────────────┘  ┌────────────┐  │
│                                │ Maesn API  │  │
│                                └─────┬──────┘  │
└──────────────────────────────────────┼──────────┘
                                       ↓
                          ┌────────────────────┐
                          │ DATEV Unternehmen   │
                          │ Online              │
                          │ → Buchungsvorschläge│
                          │ → Massenfreigabe    │
                          └────────────────────┘
```

## Lizenz

Proprietär – © 2025 David / voxdrop.live
