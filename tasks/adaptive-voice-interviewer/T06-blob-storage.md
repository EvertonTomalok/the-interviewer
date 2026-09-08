# T06 — Blob storage: local, GCS, S3

**Wave 1 · lane D · depends on T02 · runs in parallel with T03, T04, T05 · covers PRD §11 T8**

```bash
git worktree add ../wt-t06-storage -b task/t06-blob-storage master
```

**Owns:** `packages/adapters/src/interviewer_adapters/storage/**`, its
`CONTEXT.md`, its tests. **Appends only** to `interviewer_adapters/__init__.py`
and `.env.example`.

> **This lane changed shape.** It used to carry a knowledge base, chunking and a
> lexical retriever; the PoC has **no corpus and no retrieval** (the persona
> carries the questions and the expected answers, PRD §4), so retrieval left for
> expansion `E1`. What stayed is the one thing the loop cannot run without —
> somewhere to keep the candidate's audio — and it grew: **three real adapters**,
> `local_fs`, `gcs` and `s3`, because where the recordings live is the first
> thing an operator wants to change and the last thing the engine should know
> about.

## Reference in this repo

| Read | For |
|---|---|
| `packages/shared-py/src/ama_shared/storage/gcs.py`, `repo.py` | a blob store behind an interface: put, fetch, signed URL, and the decision to return `None` instead of raising when the bucket is unavailable |
| `packages/shared-py/src/ama_shared/media.py` | why a caller is handed a signed URL or a proxied stream instead of a storage path, and where the mime and size are decided |
| `packages/shared-py/src/ama_shared/db/repos.py` | how an artifact row and its bytes stay in step: the row is written by the same step that wrote the blob |

## Deliverables

### `local_fs.py` — the default store

`BlobStore.put/get/signed_url`, rooted at `STORAGE__LOCAL_FS__ROOT`.

- **Paths are derived from the artifact id, never from user input.** A filename
  that arrives in a multipart upload is metadata, not a path component. A crafted
  id must not escape the root, and that is a test, not a review comment.
- `signed_url` is a short-lived token the API validates, not a raw filesystem
  path. The browser never learns where the file lives.
- `get` on an unknown id returns `None`; the caller decides whether that is a
  404 or a corrupt run. An adapter that raises here forces every caller into a
  `try`.

### `gcs.py` and `s3.py` — the cloud stores

Same three methods (`put`, `get`, `signed_url`), registered as data like every
other provider (`kind="storage"`, names `gcs` and `s3`). Each raises
`ConfigError` **naming its own missing variable** — `STORAGE__GCS__BUCKET`,
`STORAGE__S3__SECRET_ACCESS_KEY` — at process start, not at the first upload.

- `signed_url` is the **native** one (V4 signing on GCS, presigned GET on S3), so
  the audio streams from the bucket and never through the API process. On
  `local_fs` the same method returns the short-lived token above; the caller
  cannot tell, which is the whole point.
- `s3.py` honours `STORAGE__S3__ENDPOINT_URL`, so MinIO in `docker compose` and
  AWS in production are the **same adapter with a different variable** — that is
  what makes the swap drill (PRD §12.5) something a reviewer can actually run
  without an AWS account.
- Transport failures map onto `PortError(transient=…)` like every other adapter:
  a 503 from a bucket is a retry, a 403 is not. Neither one is a `botocore`
  exception escaping into the workflow.
- Tested against a **mock transport**, never a real bucket, so `make check` stays
  offline. An `integration`-marked test hits MinIO for whoever wants proof.

### `InMemoryBlobStore`

Dict-backed, same port, same semantics — including the unknown-id `None` and the
id-derived key. Every other lane's unit suite stores audio through it, so if it
is lenient where `local_fs` is strict the whole suite is a comfortable lie.

### Shared between two processes

With `STORAGE_PROVIDER=local_fs` the **worker writes** the artifact and the
**API streams** it. In `docker compose` they mount one volume (T01); on the host
they share one root. Say so in `storage/CONTEXT.md` under **Traps** — splitting
the services without splitting the store is how every playback starts 404-ing.

With `gcs` or `s3` that trap disappears — both processes talk to the same bucket
— which is a reason to prefer them for any deployment where the API and the
worker are not on one host.

## Tests

- Put/get round-trip on bytes with a declared mime and size.
- Unknown id returns `None`, not an exception.
- Signed URL: valid before expiry, refused after; a token for artifact A does not
  serve artifact B.
- **Path escape**: an artifact id containing `../` or an absolute path cannot
  read or write outside the storage root.
- **One contract suite over all four implementations**: `local_fs` (tmp dir),
  `gcs` and `s3` (mock transport), `InMemoryBlobStore`. If a behaviour is only
  asserted for one of them, the swap drill is a coin toss.
- Each cloud adapter with a missing variable raises `ConfigError` naming that
  variable, at build time.
- A 5xx from a bucket is `PortError(transient=True)`; a 403 is not; no vendor
  exception escapes.

## Done when

- The contract suite is green over all four implementations, with no network, no
  bucket and no database container.
- `STORAGE_PROVIDER` can be flipped between `local_fs`, `gcs` and `s3` with no
  code change (PRD §12.5 runs it against MinIO).
- `storage/CONTEXT.md` is complete and states under **Invariants** that paths
  come from ids only, and under **Traps** that on `local_fs` the API and the
  worker must see one root.

## Land it — worktree → `master`

`make check` inside the worktree first. No network, no containers, so there is
no excuse to skip it.

```bash
cd ../wt-t06-storage
make check                    # ruff, mypy --strict, tests, coverage, docs-check
git add -A && git commit -m "feat(storage): blob store with local_fs, gcs and s3 adapters (T06)"

cd <repo>                     # the main checkout, always on master
git switch master
git merge --no-ff task/t06-blob-storage -m "feat(storage): blob store with local_fs, gcs and s3 adapters (T06)"
make check                    # green on the trunk, not only on the branch

git worktree remove ../wt-t06-storage
git branch -d task/t06-blob-storage
```

Merged straight onto `master` — no pull request, no integration branch. If
`make check` fails on the trunk after the merge, fix it on `master` at once:
every later lane branches off it.
