"""Small, non-secret runtime snapshot shared between GUI and Streamlit."""
import json
from datetime import datetime, timezone
from pathlib import Path


def write_runtime_state(path: str | Path, *, running: bool, environment: str, mode: str, strategy: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"running": running, "environment": environment, "mode": mode,
            "strategy": strategy, "updated_at": datetime.now(timezone.utc).isoformat()}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_runtime_state(path: str | Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except (OSError, ValueError, TypeError):
        return {}
