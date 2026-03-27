# Contributing to Music Studio (SpotDownload)

## Development setup

**Primary flow — repository root:**

```bash
cp .env.example .env
# Fill in credentials (see README.md)

npm install
npm run dev
```

This starts FastAPI on **:8000** and Vite on **:5173** (see root `package.json`).

**Backend only** (virtualenv):

```bash
cd backend
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend only:**

```bash
cd frontend && npm install && npm run dev
```

## Running tests

- **Backend** (from `backend/`):

  ```bash
  pytest tests/ -v
  ```

  Tests use a separate SQLite DB via `conftest`.

- **Frontend** (from `frontend/`):

  ```bash
  npm run test:run
  ```

## Code style

- **Backend**: [Ruff](https://docs.astral.sh/ruff/)

  ```bash
  cd backend && ruff check . && ruff format .
  ```

- **Frontend**: ESLint

  ```bash
  cd frontend && npm run lint
  ```

- **Pre-commit** (optional): `pip install pre-commit && pre-commit install`

## Database migrations

After changing `backend/models.py`:

```bash
cd backend && alembic revision --autogenerate -m "description"
alembic upgrade head
```

## API

- Interactive docs: http://localhost:8000/docs
- Export/import: `GET /api/export`, `POST /api/import` for playlist backup

## Pull requests

Keep changes focused; run tests and lint before submitting.
