# Widget Renderer

A food-ordering chat, in English and Arabic, where the agent replies with ChatKit widget payloads. The page validates each payload before rendering it.

## Requirements

- Python 3.13 and [uv](https://docs.astral.sh/uv/)
- Node.js 20+
- An OpenRouter API key (only the chat needs it; the payload playground works without one)

## Run with Docker (quickest)

Only Docker is needed. From the project root:

```bash
cp .env.example .env   # set OPEN_ROUTE_API_KEY for the chat; optional for the playground
docker compose up --build
```

Then open http://localhost:5173.

## Run

**1. Add your key.** From the project root:

```bash
cp .env.example .env
```

Then set `OPEN_ROUTE_API_KEY` in `.env`.

**2. Start the backend** in one terminal:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**3. Start the frontend** in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

**4. Open http://localhost:5173.** Use this address exactly: the backend only accepts requests from port 5173.

## Try it

- **Paste a payload:** use the playground at the top of the page. Paste any ChatKit JSON, or pick a built-in example, to see the rendered widget next to its validation issues.
- **Order through chat:** send "Show me the menu", set quantities in the menu, then review and confirm the order.
- **Switch language:** change it to العربية at any point. The order is kept.
- **Make an item sell out:** in the demo menu at the bottom of the page, click "Mark sold out" while you're choosing. The chat menu updates in place and keeps your edits. Opening a second tab works too.
- **Stream a card:** ask "Give me a summary card comparing the dishes with their prices". The card fills in as the model writes it.

## Test

```bash
cd backend
PYTHONPATH=.:tests uv run python -m unittest discover -s tests
```

```bash
cd frontend
npm run build
```

`npm run build` type-checks and builds the frontend.

## Documents

- `docs/payload-test-cases.md`: the broken payloads and how each one renders.
- `SPEC.md`: product decisions and the fallback policy behind them.
- `docs/widget-format.md`: the supported ChatKit subset.
