# Frozen retrieval baseline

Ticket 01 freezes ten content-verified questions in `tests/fixtures/retrieval-baseline.json`.
Each requires its specified YouTube Video to appear in the first ten returned **Segments**.
The fixture fixes Group scope, result limit, recency preference, recency parameters and the
reference date (2026-09-18). Evidence notes refer to passages read from the real stored
transcripts before running search; expected IDs are not generated from current rankings.

The live library had five Channels but no Groups. Drew approved creating `SaaS marketing`
(MicroConf, App Masters, April Dunford) and `business growth` (Alex Hormozi,
Cabinetmakerprofitsystem) **only in a preparation copy**. SQLite's backup API copied the live
database, including committed WAL data; the only changes to that copy were these Groups and
their memberships. The live library was not changed. No Videos, transcripts, Segments or
vectors were regenerated. The final snapshot was made from the prepared copy with:

```sh
uv run python scripts/freeze_retrieval_snapshot.py \
  --source /home/drew/.local/share/mentor-baselines/build-0/preparation.db \
  --destination /home/drew/.local/share/mentor-baselines/build-0/retrieval.db
```

This command refuses overwrite, uses a consistent SQLite backup, checks integrity with
sqlite-vec loaded, and publishes a standalone database with permissions 0444. Its enclosing
directory is private (0700). The populated database stays outside git. The manifest is
`tests/fixtures/retrieval-baseline-manifest.json`; the exact snapshot SHA-256 is:

```text
5504c1b1e96d4a11a7e229be6d3c24d9201e598e8d8fcbe724792f56d524c7da
```

## Repeat the CUDA run

Use the locked dependencies (`uv sync --frozen`) and the pinned model revisions from the
manifest. Both revisions must already be complete in the Hugging Face cache. If transferring
the cache, dereference snapshot symlinks or include their blob targets. The runner resolves
exact revisions offline; it never refreshes a moving `main` model ref.

Stop Mentor before loading a second model set, inspect free GPU memory, and restore its
prior running state even on failure. Do not kill unrelated GPU workloads. On this Linux host,
the exact test invocation is:

```sh
MENTOR_RETRIEVAL_SNAPSHOT=/home/drew/.local/share/mentor-baselines/build-0/retrieval.db \
MENTOR_RETRIEVAL_RESULTS=/tmp/mentor-cuda-retrieval-results.json \
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
uv run pytest -q -s -m real_models tests/test_retrieval_baseline.py
```

For a service-managed repeat, use a shell trap so failure also restores the service:

```sh
(
  set -eu
  prior=$(systemctl --user is-active mentor.service || true)
  restore() { if [ "$prior" = active ]; then systemctl --user start mentor.service; fi; }
  trap restore EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  systemctl --user stop mentor.service
  nvidia-smi --query-gpu=name,memory.total,memory.free,driver_version --format=csv
  MENTOR_RETRIEVAL_SNAPSHOT=/home/drew/.local/share/mentor-baselines/build-0/retrieval.db \
  MENTOR_RETRIEVAL_RESULTS=/tmp/mentor-cuda-retrieval-results.json \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  uv run pytest -q -s -m real_models tests/test_retrieval_baseline.py
)
```

Ensure no scheduled Sync or foreground Mentor can start concurrently. At initial capture,
`mentor-sync.timer` and `mentor-sync.service` were inactive. After restoration, verify
`systemctl --user is-active mentor.service` and `/api/health` model readiness.

The runner validates checksum/schema/model identity before copying to a disposable writable
database. It calls production `Search` and the existing CUDA model wrappers directly; it
never starts application lifespan or a Sync worker. Time is frozen only at the search clock
boundary. CUDA precision and ranking implementation remain unchanged. A missing
`MENTOR_RETRIEVAL_SNAPSHOT` produces an explicit skip when this opt-in test is selected;
an empty, missing, corrupt, wrong-checksum or incompatible configured snapshot fails.
Normal `uv run pytest -q` excludes the `real_models` marker entirely. To demonstrate the
explicit skip, use `env -u MENTOR_RETRIEVAL_SNAPSHOT uv run pytest -q -rs -m real_models
tests/test_retrieval_baseline.py`.

## Ticket 03: transfer and compare

Transfer the existing `retrieval.db` privately to the Mac, verify the exact SHA-256 above,
keep it read-only outside the checkout, and set `MENTOR_RETRIEVAL_SNAPSHOT` to its absolute
path. Transfer these fixtures, manifest, locked dependencies and pinned model cache revisions
with it. Never take a replacement snapshot, re-Sync, re-embed, or regenerate required Videos.
There are no SQLite sidecars to transfer. The database can contain personal conversations;
do not upload it to git or attach it to public issues.

Ticket 02 will change inference device selection; this ticket's runner intentionally requires
the unchanged CUDA implementation. Ticket 03 must adapt that guard and hardware/precision
reporting for the actual MPS run while keeping the frozen inputs, clock, production retrieval
path and pass conditions identical. Select this test specifically, not the separate planted
fake-transcript real-model test. Compare per-question required-Video presence and retain the
full rankings, device/fallback, precision, dependency versions and source revision.

Stored passage vectors were embedded by production CUDA and are reused. This comparison
covers **query embedding and reranking**, not passage-embedding equivalence and not chat-model
quality. The database records passage model name/dimension, but not historical model commit
IDs per passage; the manifest explicitly distinguishes that limit from the pinned query and
reranker revisions used for this baseline.

## Recorded execution

Execution results and review evidence are recorded alongside this document after the real run.
