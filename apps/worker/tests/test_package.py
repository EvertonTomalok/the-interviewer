from __future__ import annotations

import interviewer_worker


def test_package_exposes_a_version() -> None:
    assert interviewer_worker.__version__
