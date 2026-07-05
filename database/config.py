import os
from pathlib import Path

from sqlspec import SQLSpec
from sqlspec.adapters.asyncpg import AsyncpgConfig

spec = SQLSpec()
config = spec.add_config(
    AsyncpgConfig(
        connection_config={"dsn": os.environ["DSN"]},
        pool_config={"min_size": 1, "max_size": 5},
        migration_config={
            "script_location": str(Path(__file__).parent / "migrations"),
        },
    )
)
