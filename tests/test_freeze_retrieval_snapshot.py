import hashlib
import sqlite3
import subprocess
import sys
from pathlib import Path

import sqlite_vec


def test_snapshot_command_preserves_committed_wal_without_mutating_or_replacing_inputs(tmp_path: Path) -> None:
    source = tmp_path / "live.sqlite3"
    snapshot = tmp_path / "private" / "frozen.sqlite3"
    command = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "scripts" / "freeze_retrieval_snapshot.py"),
        "--source", str(source), "--destination", str(snapshot),
    ]
    with sqlite3.connect(source) as live:
        live.enable_load_extension(True)
        sqlite_vec.load(live)
        live.enable_load_extension(False)
        live.execute("PRAGMA journal_mode=WAL")
        live.execute("CREATE TABLE videos (youtube_id TEXT)")
        live.execute("CREATE VIRTUAL TABLE vectors USING vec0(embedding float[2])")
        live.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        live.execute("INSERT INTO videos VALUES ('committed-video')")
        live.execute("INSERT INTO vectors VALUES (1, '[0.25, 0.5]')")
        live.commit()
        wal = Path(f"{source}-wal")
        source_before, wal_before = source.read_bytes(), wal.read_bytes()
        assert len(wal_before) > 0

        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert source.read_bytes() == source_before
        assert wal.read_bytes() == wal_before
        assert snapshot.stat().st_mode & 0o777 == 0o444
        assert not Path(f"{snapshot}-wal").exists()
        with sqlite3.connect(f"{snapshot.as_uri()}?mode=ro&immutable=1", uri=True) as frozen:
            frozen.enable_load_extension(True)
            sqlite_vec.load(frozen)
            frozen.enable_load_extension(False)
            assert frozen.execute("SELECT * FROM videos").fetchall() == [("committed-video",)]
            assert frozen.execute("SELECT count(*) FROM vectors").fetchone() == (1,)
            assert frozen.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert frozen.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        assert digest in result.stdout
        retry = subprocess.run(command, capture_output=True, text=True)
        assert retry.returncode != 0
        assert "exists" in retry.stderr
        assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == digest
