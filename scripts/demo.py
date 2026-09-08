#!/usr/bin/env python3
"""`make demo` -- a headless interview through the same routes the browser
uses: seed an admin, an area and one persona version; publish an invite;
claim it with the passkey exactly as `interview.html` does; answer every
question; finish; then read the report back through the admin routes.

One command after `git clone` and a filled `.env`:

    python scripts/demo.py
    python scripts/demo.py --reply-mode voice --out-dir ./var/demo-audio

Talks only to the running API (`PUBLIC_BASE_URL`) -- it posts and polls the
same way a browser does, so it exercises `WORKFLOW_PROVIDER` and every other
adapter exactly as configured, never a shortcut through the engine directly.
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from interviewer_core.config import load_settings
from interviewer_core.errors import ConfigError

_POLL_INTERVAL_SECONDS = 0.5
_POLL_TIMEOUT_SECONDS = 60.0

_PERSONA = {
    "name": "Backend Engineer Screen",
    "language": "en",
    "voice": None,
    "llm_provider": "fake",
    "llm_model": "fake-model",
    "temperature": 0.4,
    "max_tokens": 500,
    "timeout_seconds": 60,
    "greeting_text": (
        "Hi, thanks for taking the time. This is a short screen for the "
        "backend engineer role -- a handful of questions, no pressure. "
        "What's your name?"
    ),
    "intake_prompt_text": "Sorry, I didn't catch that -- what's your name?",
    "farewell_text": "That's everything I need. Thanks so much for your time!",
    "questions": [
        {
            "ref": "q1",
            "topic": "http",
            "text": "What's the difference between a 401 and a 403 response?",
            "expected_answer": (
                "401 means the request has no valid credentials (unauthenticated); "
                "403 means the credentials are valid but not allowed to do this "
                "(unauthorized)."
            ),
            "weight": 1.0,
            "follow_up_depth": 1,
        },
        {
            "ref": "q2",
            "topic": "databases",
            "text": "What's a database index, and what does it cost you?",
            "expected_answer": (
                "An index is a data structure (often a B-tree) that speeds up reads "
                "by avoiding a full table scan, at the cost of extra storage and "
                "slower writes since every insert/update also updates the index."
            ),
            "weight": 1.0,
            "follow_up_depth": 1,
        },
        {
            "ref": "q3",
            "topic": "concurrency",
            "text": "What's a race condition, and how would you guard against one?",
            "expected_answer": (
                "A race condition happens when two operations touch shared state "
                "concurrently and the outcome depends on timing; guard with a lock, "
                "an atomic operation, or a transaction with the right isolation level."
            ),
            "weight": 1.0,
            "follow_up_depth": 1,
        },
    ],
    "policy": "guided",
    "min_coverage": 0.3,
    "max_questions": 8,
    "rubric": (
        "Score each answer 0-1 on how much of the expected concept it actually "
        "covers, not on phrasing. A partial, correct answer beats a fluent, "
        "wrong one."
    ),
}


def _silent_wav(seconds: float = 1.0, *, sample_rate: int = 16_000) -> bytes:
    """A minimal, valid 16-bit mono PCM WAV -- the demo has no microphone,
    so every "recording" it sends is this, standing in for whatever a
    browser would have captured. `FakeSTT` (or a real STT under a cheap
    real model, PRD §12.3) doesn't need the content to be meaningful."""
    frame_count = int(sample_rate * seconds)
    data = b"\x00\x00" * frame_count
    byte_rate = sample_rate * 2
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(data))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, byte_rate, 2, 16)
        + b"data"
        + struct.pack("<I", len(data))
    )
    return header + data


class DemoError(RuntimeError):
    pass


def _unwrap(response: httpx.Response, *, expect: tuple[int, ...] = (200,)) -> Any:
    if response.status_code not in expect:
        raise DemoError(
            f"{response.request.method} {response.request.url} -> "
            f"{response.status_code}: {response.text[:500]}"
        )
    body = response.json()
    if not body.get("success", True) and body.get("error"):
        raise DemoError(f"{response.request.url} returned an error envelope: {body['error']}")
    return body.get("data", body)


class DemoClient:
    def __init__(self, base_url: str) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=30.0)

    def close(self) -> None:
        self._client.close()

    # -- admin setup --------------------------------------------------------

    def register_or_login_admin(self, email: str, password: str) -> str:
        register = self._client.post("/auth/register", json={"email": email, "password": password})
        if register.status_code == 201 or register.status_code == 200:
            data = _unwrap(register, expect=(200, 201))
            print(f"seeded admin: {email}")
            return str(data["access_token"])

        login = self._client.post("/auth/login", json={"email": email, "password": password})
        data = _unwrap(login, expect=(200,))
        print(f"admin already existed, logged in: {email}")
        return str(data["access_token"])

    def create_area(self, admin_token: str, *, slug: str, name: str) -> str:
        response = self._client.post(
            "/areas",
            json={"slug": slug, "name": name, "description": "Seeded by scripts/demo.py"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        data = _unwrap(response, expect=(200, 201))
        print(f"created area: {name} ({slug})")
        return str(data["id"])

    def create_persona(self, admin_token: str, *, area_id: str) -> str:
        response = self._client.post(
            f"/areas/{area_id}/personas",
            json=_PERSONA,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        data = _unwrap(response, expect=(200, 201))
        print(f"published persona: {_PERSONA['name']} ({len(_PERSONA['questions'])} questions)")
        return str(data["id"])

    def create_invite(self, admin_token: str, *, persona_id: str) -> tuple[str, str]:
        response = self._client.post(
            "/invites",
            json={"persona_id": persona_id, "max_sessions": 1, "ttl_hours": 24},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        data = _unwrap(response, expect=(200, 201))
        print(f"published invite: {data['url']}")
        return str(data["slug"]), str(data["passkey"])

    # -- candidate path -------------------------------------------------

    def claim(self, slug: str, passkey: str) -> tuple[str, dict[str, Any]]:
        response = self._client.post(f"/i/{slug}/claim", json={"passkey": passkey})
        data = _unwrap(response, expect=(200,))
        return str(data["access_token"]), data

    def send_turn(self, candidate_token: str, *, language: str | None = None) -> dict[str, Any]:
        files = {"file": ("answer.wav", _silent_wav(), "audio/wav")}
        form: dict[str, str] = {"language": language} if language else {}
        response = self._client.post(
            "/session/turns",
            files=files,
            data=form,
            headers={"Authorization": f"Bearer {candidate_token}"},
        )
        return _unwrap(response, expect=(200, 202))

    def finish(self, candidate_token: str) -> dict[str, Any]:
        response = self._client.post(
            "/session/finish", headers={"Authorization": f"Bearer {candidate_token}"}
        )
        return _unwrap(response, expect=(200, 202))

    def poll_run(self, token: str, run_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            response = self._client.get(
                f"/session/runs/{run_id}", headers={"Authorization": f"Bearer {token}"}
            )
            data = _unwrap(response, expect=(200,))
            if data.get("status") in ("succeeded", "failed"):
                return data
            time.sleep(_POLL_INTERVAL_SECONDS)
        raise DemoError(f"run {run_id} did not finish within {_POLL_TIMEOUT_SECONDS}s")

    def fetch_artifact(self, token: str, artifact_id: str) -> bytes:
        response = self._client.get(
            f"/session/artifacts/{artifact_id}", headers={"Authorization": f"Bearer {token}"}
        )
        if response.status_code != 200:
            raise DemoError(f"could not fetch artifact {artifact_id}: {response.status_code}")
        return response.content

    def admin_session_report(self, admin_token: str, session_id: str) -> dict[str, Any]:
        response = self._client.get(
            f"/admin/sessions/{session_id}", headers={"Authorization": f"Bearer {admin_token}"}
        )
        return _unwrap(response, expect=(200,))

    def latest_admin_session_id(self, admin_token: str) -> str | None:
        """The just-finished session's id, read back off the admin listing
        rather than assumed from the candidate-facing responses (PRD §8: a
        candidate token carries no session id a reader could correlate)."""
        response = self._client.get(
            "/admin/sessions", headers={"Authorization": f"Bearer {admin_token}"}
        )
        rows = _unwrap(response, expect=(200,))
        if not rows:
            return None
        newest = max(rows, key=lambda row: row.get("date") or row.get("started_at") or "")
        session_id = newest.get("id") or newest.get("session_id")
        return str(session_id) if session_id else None


def _print_report(report: dict[str, Any]) -> None:
    print()
    print("=" * 60)
    print("REPORT (admin view -- never shown to the candidate)")
    print("=" * 60)
    scores = report.get("scores") or []
    if not scores:
        print("no report yet")
        return
    for entry in scores:
        print(f"  [{entry['question_ref']}] {entry['verdict']:>12}  score={entry['score']:.2f}")
        print(f"      {entry['rationale']}")
    print(f"overall: {report['overall_score']:.2f}")
    print(report.get("summary", ""))


def run(args: argparse.Namespace) -> int:
    settings = load_settings()
    stt_note = (
        " (FakeSTT -- no real STT provider configured)" if settings.stt_provider == "fake" else ""
    )

    client = DemoClient(settings.public_base_url)
    try:
        suffix = uuid.uuid4().hex[:8]
        admin_email = f"demo-admin-{suffix}@example.com"
        admin_token = client.register_or_login_admin(admin_email, "demo-password-not-real")

        area_id = client.create_area(admin_token, slug=f"backend-{suffix}", name="Backend")
        persona_id = client.create_persona(admin_token, area_id=area_id)
        slug, passkey = client.create_invite(admin_token, persona_id=persona_id)

        print()
        print(f"claiming invite {slug!r} with its passkey -- exactly what the public link does")
        candidate_token, claim_data = client.claim(slug, passkey)
        print(f"  greeting: {claim_data['greeting_text']}")
        print(f"  ({claim_data['question_total']} questions)")

        turn_index = 0
        state: dict[str, Any] = {}
        while True:
            label = "candidate's name" if turn_index == 0 else "answering a question"
            print()
            print(f"--- turn {turn_index}: {label} ---")
            result = client.send_turn(candidate_token, language=settings.stt_language or None)
            state = client.poll_run(candidate_token, result["run_id"])
            if state["status"] != "succeeded":
                raise DemoError(f"turn {turn_index} failed: {state.get('error')}")
            print(f"  transcript{stt_note}: [{'name' if turn_index == 0 else 'answer'} given]")

            if state.get("phase") == "closing":
                print(f"  interviewer: {state.get('question_text')}")
                break

            print(f"  interviewer asks: {state.get('question_text')}")
            if state.get("question_number") is not None:
                print(f"  ({state['question_number']} of {state.get('question_total')})")

            audio_id = state.get("audio_artifact_id")
            if args.reply_mode == "voice" and audio_id:
                out_dir = Path(args.out_dir)
                out_dir.mkdir(parents=True, exist_ok=True)
                audio_bytes = client.fetch_artifact(candidate_token, audio_id)
                out_path = out_dir / f"reply-{turn_index}.wav"
                out_path.write_bytes(audio_bytes)
                print(f"  reply audio written: {out_path}")

            turn_index += 1

        print()
        print("finishing the session")
        finish_result = client.finish(candidate_token)
        eval_state = client.poll_run(candidate_token, finish_result["run_id"])
        if eval_state["status"] != "succeeded":
            raise DemoError(f"evaluation failed: {eval_state.get('error')}")
        print("  status: sent for review (no score, no rationale -- candidate never sees one)")

        session_id = client.latest_admin_session_id(admin_token)
        if session_id:
            report_view = client.admin_session_report(admin_token, session_id)
            _print_report(report_view.get("report") or {})
        else:
            print("(could not find the session in the admin listing -- skipping report readback)")

        return 0
    except DemoError as exc:
        print(f"demo failed: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reply-mode",
        choices=["text", "voice"],
        default="text",
        help="text (default): print only. voice: also write reply audio under --out-dir.",
    )
    parser.add_argument(
        "--out-dir",
        default="./var/demo-audio",
        help="where --reply-mode voice writes reply audio (default: ./var/demo-audio)",
    )
    args = parser.parse_args()
    try:
        return run(args)
    except ConfigError as exc:
        print(f"demo: {exc}", file=sys.stderr)
        return 1
    except httpx.ConnectError as exc:
        print(f"demo: could not reach the API -- is it running? ({exc})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
