from __future__ import annotations

import interviewer_api


def test_package_exposes_a_version() -> None:
    assert interviewer_api.__version__
