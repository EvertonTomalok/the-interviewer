# ADR 0007: the camera is preview-only

## Status

Accepted.

## Context

PRD §2 lists video processing as a non-goal. `interview.html` still turns the
camera on (`getUserMedia({video: true})`) and renders it to a local
`<video>` element — the question is why a product with no video feature
touches the camera API at all.

## Decision

The camera exists for **presence only**: a candidate looking at a live
self-view behaves like someone being interviewed, not someone talking to a
form. No frame is read (no `<canvas>` capture, no `MediaRecorder` on the
video track — the recorder attaches to the microphone stream only), uploaded,
or stored. `interview.html`'s own comment states this at the point the
stream is opened, and `apps/web/CONTEXT.md` states it as an invariant a
future change must not break.

## Consequences

- Nothing in the backend has a video ingestion path: `POST
  /session/turns` accepts one audio blob, `Artifact.kind` never takes a
  video value, `BlobStore` never sees a video mime type. This is enforced by
  absence, not by a check — there is no code to bypass because none exists.
- Toggling the camera off never affects the interview: it changes nothing
  server-side, because the server was never told the camera existed.
- If video analysis ever became a real feature (engagement scoring, a
  second modality for the LLM), it would need a new port, a new artifact
  kind, and — per PRD §2 — an explicit decision to reverse this one, not a
  quiet extension of the existing camera toggle.
