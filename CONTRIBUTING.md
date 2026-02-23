# Contributing to SpotDownload

## Development setup

1. Clone the repo and follow the main [README](README.md) setup (backend + frontend).
2. Backend: use a virtualenv and install dev deps:
   ```bash
   cd backend && pip install -r requirements.txt
   ```
3. Frontend: `cd frontend && npm install`

## Running tests

- **Backend**: from `backend/`, run:
  ```bash
  pytest tests/ -v
  ```
  Use a test DB (tests set `DATABASE_URL` to a file in conftest).
- **Frontend**: from `frontend/`, run:
  ```bash
  npm run test:run
  ```

## Code style

- **Backend**: [Ruff](https://docs.astral.sh/ruff/) for lint and format.
  ```bash
  cd backend && ruff check . && ruff format .
  ```
- **Frontend**: ESLint.
  ```bash
  cd frontend && npm run lint
  ```
- **Pre-commit** (optional): `pip install pre-commit && pre-commit install`. Hooks run ruff and eslint.

## Database migrations

- Create a new migration after changing `backend/models.py`:
  ```bash
  cd backend && alembic revision --autogenerate -m "description"
  ```
- Apply migrations: `alembic upgrade head`
- Existing DBs: if you already have tables, run `alembic stamp head` to mark current, or run migrations and fix conflicts manually.

## API

- Open http://localhost:8000/docs for interactive API docs (FastAPI Swagger).
- Export/import: `GET /api/export` and `POST /api/import` for playlist backup.

## Pull requests

- Keep changes focused; prefer smaller PRs.
- Ensure tests pass and lint is clean before submitting.
