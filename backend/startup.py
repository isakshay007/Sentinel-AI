"""
SentinelAI — Startup Utilities
Run migrations and health checks.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def run_migrations() -> bool:
    """
    Run Alembic migrations (upgrade head) on startup.
    Returns True if successful, False otherwise.
    """
    project_root = Path(__file__).resolve().parent.parent
    alembic_ini = project_root / "backend" / "alembic.ini"
    if not alembic_ini.exists():
        logger.warning("alembic.ini not found at %s — skipping migrations", alembic_ini)
        return False
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", str(alembic_ini), "upgrade", "head"],
            cwd=str(project_root),
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            logger.info("Migrations completed successfully")
            return True
        logger.error("Migrations failed: %s", result.stderr or result.stdout)
        return False
    except subprocess.TimeoutExpired:
        logger.error("Migrations timed out after 60s")
        return False
    except Exception as e:
        logger.exception("Migrations failed: %s", e)
        return False
