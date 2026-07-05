set dotenv-load

format:
    uv run ruff check --select I --fix .
    uv run ruff check --fix .
    uv run ruff format .
    uv run pylintsql fix .

test:
    uv run pytest

migrate:
    uv run sqlspec upgrade

migrate-status:
    uv run sqlspec show-current-revision --verbose
