# BuildHarvey

BuildHarvey is an observation-based desktop agent that captures work sessions, groups them into Episodes, and surfaces them for review in a web application.

## Structure

```
/               — Next.js web app (episode viewer)
agent/          — Python desktop agent (screen capture, OCR, episode engine, sync)
```

## Web App

```bash
npm install
npm run dev
```

Requires `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` in `.env.local`.

## Desktop Agent

```bash
cd agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Requires `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` in `agent/.env`.
