"""Upload validation at the API boundary -- a candidate's raw multipart
upload is checked once, here, before any workflow step trusts its shape.

`mime` is what the browser declared on upload, never sniffed from bytes:
browsers disagree on container format (Chrome hands you
`audio/webm;codecs=opus`, Safari hands you something else), and guessing
from bytes is how a boundary check turns into a boundary guess.
"""

from __future__ import annotations

from interviewer_core.config import Settings
from interviewer_core.errors import DomainError


def validate_upload(
    content: bytes,
    *,
    mime: str,
    settings: Settings,
    duration_seconds: float | None = None,
) -> None:
    """Raise `DomainError` naming what was wrong; return nothing otherwise."""
    base_mime = mime.split(";", 1)[0].strip()
    if base_mime not in settings.upload_allowed_mime_types:
        raise DomainError(
            f"unsupported upload mime {mime!r}; allowed: "
            f"{', '.join(settings.upload_allowed_mime_types)}"
        )
    if len(content) > settings.upload_max_bytes:
        raise DomainError(
            f"upload of {len(content)} bytes exceeds UPLOAD_MAX_BYTES={settings.upload_max_bytes}"
        )
    if duration_seconds is not None and duration_seconds > settings.upload_max_seconds:
        raise DomainError(
            f"upload of {duration_seconds:.1f}s exceeds "
            f"UPLOAD_MAX_SECONDS={settings.upload_max_seconds}"
        )
