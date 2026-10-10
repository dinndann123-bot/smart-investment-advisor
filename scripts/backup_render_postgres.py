"""Export PostgreSQL to a local custom-format dump without modifying source.

Run in a trusted environment with network access to the source database:
  DATABASE_URL=... python scripts/backup_render_postgres.py
Requires PostgreSQL client pg_dump installed. Never commit the resulting dump.
"""
import os
import pathlib
import subprocess
import sys

url = os.environ.get('DATABASE_URL')
if not url:
    sys.exit('DATABASE_URL missing; aborting')
path = pathlib.Path(os.environ.get('BACKUP_PATH', 'private-backups/learning-backup.dump'))
path.parent.mkdir(parents=True, exist_ok=True)
if path.exists():
    sys.exit('Backup path exists; refusing to overwrite')
try:
    subprocess.run(['pg_dump', '--format=custom', '--no-owner', '--no-acl', '--file', str(path), url], check=True, timeout=900)
    if path.stat().st_size < 100:
        sys.exit('Backup unexpectedly small; verify before migration')
    print(f'Backup created: {path} ({path.stat().st_size} bytes). Verify with pg_restore --list.')
except Exception:
    path.unlink(missing_ok=True)
    raise
