format:
    uv run ruff check --select I --fix .
    uv run ruff check --fix .
    uv run ruff format .
    uv run pylintsql fix .

test:
    uv run pytest
