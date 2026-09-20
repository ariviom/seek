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
database. The supported retrieval schema remains 11: additive application migrations such
as the settings table do not change this corpus or cause it to be migrated. The manifest
and actual snapshot must both match that explicitly supported schema.
It calls production `Search` and the existing CUDA model wrappers directly; it
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

The real run on 2026-09-18, 23:02:32–23:02:55 UTC passed **10/10 questions** on clean
source revision `673849dfe42b2dd0b197689914b6798c258991cd`. Full per-Segment rankings,
scores, model revisions, dependencies and source hashes are in
[`baselines/build-0-cuda.json`](baselines/build-0-cuda.json). Model-status cache paths alone
were replaced with repository names in that committed artifact; the original report remains
beside the private snapshot as `cuda-results.json`.

The command above was run with `MENTOR_RETRIEVAL_RESULTS` set to
`/home/drew/.local/share/mentor-baselines/build-0/cuda-results.json`. Mentor was active before
the run, stopped and confirmed inactive before model loading, then restored by the EXIT trap.
The RTX 3090 had **21,590 MiB free / 24,576 MiB total** after stopping Mentor; driver
595.84, CUDA 13.0, precision bfloat16. No unrelated workload was evicted. After the run,
Mentor was active and `/api/health` reported both models ready. The live Group count remains
zero, confirming the approved scope preparation was confined to the copy.

| Question | Required Video | First matching Segment rank | Result |
| --- | --- | ---: | --- |
| SaaS pricing | JUB5t1SuIMo | 1 | pass |
| LinkedIn outreach | OWvDbX5Fmps | 1 | pass |
| Localized app pricing | UcJnr_z20Cw | 1 | pass |
| Music and retention | osYXbQ41TmQ | 1 | pass |
| Positioning alternatives | BDkpuQps4nk | 1 | pass |
| Testing positioning | D9pf_iEomjY | 1 | pass |
| Raising existing prices | Gy-RmpRif-I | 1 | pass |
| Retention benchmarks | -j8_YCWZ05Q | 2 | pass |
| Overtime and profit | H-vDOxOIML8 | 1 | pass |
| Estimating assumptions | UR8O8TeI4ys | 1 | pass |

Snapshot SHA-256 after the run matches the manifest. The expected Videos, question text,
limits and recency inputs were not changed after seeing rankings.
