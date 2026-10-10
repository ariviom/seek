"""Network-free checks at the frozen-corpus runner's configuration boundary."""

from pathlib import Path

import pytest
from retrieval_baseline import configured_snapshot


def test_absent_snapshot_is_explicitly_optional_but_empty_or_missing_is_an_error(tmp_path: Path) -> None:
    assert configured_snapshot({}) is None
    for value in ("", str(tmp_path / "missing.db"), str(tmp_path)):
        with pytest.raises(ValueError, match="SEEK_RETRIEVAL_SNAPSHOT"):
            configured_snapshot({"SEEK_RETRIEVAL_SNAPSHOT": value})


def test_snapshot_must_match_checksum_schema_and_embedding_before_a_copy_is_used(tmp_path: Path) -> None:
    import hashlib
    import sqlite3

    from retrieval_baseline import Manifest, prepare_snapshot

    source = tmp_path / "frozen.db"
    with sqlite3.connect(source) as conn:
        conn.executescript(
            "PRAGMA user_version=11; CREATE TABLE embedding_model(name TEXT, dimension INTEGER);"
            "INSERT INTO embedding_model VALUES('example/embedding', 1024);"
        )
    original = source.read_bytes()
    manifest = Manifest.model_validate({
        "snapshot": {"sha256": hashlib.sha256(original).hexdigest(), "schema_version": 11},
        "embedding": {"model": "example/embedding", "dimension": 1024, "revision": "a" * 40},
        "reranker": {"model": "example/reranker", "revision": "b" * 40},
    })
    copy = prepare_snapshot(source, tmp_path / "run.db", manifest)
    copy.write_bytes(b"run may write freely")
    assert source.read_bytes() == original
    for altered, message in (
        (manifest.model_copy(update={"snapshot": manifest.snapshot.model_copy(update={"sha256": "0" * 64})}), "checksum"),
        (manifest.model_copy(update={"snapshot": manifest.snapshot.model_copy(update={"schema_version": 10})}), "schema"),
        (manifest.model_copy(update={"embedding": manifest.embedding.model_copy(update={"dimension": 3})}), "embedding"),
    ):
        with pytest.raises(ValueError, match=message):
            prepare_snapshot(source, tmp_path / "rejected.db", altered)
        assert not (tmp_path / "rejected.db").exists()
    source.write_bytes(b"not sqlite")
    corrupt = manifest.model_copy(update={"snapshot": manifest.snapshot.model_copy(
        update={"sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    )})
    with pytest.raises(ValueError, match="SQLite"):
        prepare_snapshot(source, tmp_path / "rejected.db", corrupt)


@pytest.mark.parametrize("version", [10, 12])
def test_even_a_matching_manifest_cannot_authorize_an_unsupported_retrieval_schema(
    tmp_path: Path, version: int,
) -> None:
    import hashlib
    import sqlite3

    from retrieval_baseline import Manifest, prepare_snapshot

    source = tmp_path / "frozen.db"
    with sqlite3.connect(source) as conn:
        conn.execute(f"PRAGMA user_version={version}")
    original = source.read_bytes()
    manifest = Manifest.model_validate({
        "snapshot": {"sha256": hashlib.sha256(original).hexdigest(), "schema_version": version},
        "embedding": {"model": "example/embedding", "dimension": 1024, "revision": "a" * 40},
        "reranker": {"model": "example/reranker", "revision": "b" * 40},
    })
    destination = tmp_path / "rejected.db"
    with pytest.raises(ValueError, match="schema"):
        prepare_snapshot(source, destination, manifest)
    assert not destination.exists()
    assert source.read_bytes() == original
