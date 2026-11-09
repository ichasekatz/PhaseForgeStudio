# Contributing

## Development setup

```bash
git clone https://github.com/ichasekatz/PhaseForgeStudio
cd PhaseForgeStudio
uv sync --group dev
pre-commit install
```

## Running tests

```bash
uv run pytest -v -m "not integration and not slow"
```

## Linting

```bash
uv run ruff check .
uv run ruff format .
```

## Submitting changes

1. Fork the repository and create a feature branch from `wip`.
2. Write tests for new server-side logic.
3. Ensure `ruff check` and `ruff format --check` pass.
4. Open a pull request against `wip`.

## Code style

- Follow [ruff](https://docs.astral.sh/ruff/) settings in `pyproject.toml`.
- Server-side code lives in `server.py`; frontend in `index.html`.
- No external Python build step — keep the server importable with just stdlib + numpy.
