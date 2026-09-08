#!/usr/bin/env python3
"""`make seed` -- admin user, one area, one persona version, one invite.

Ends by printing the invite link and its passkey, plainly, once -- the
passkey is not stored anywhere and this is the only time it is shown.

Placeholder until persistence (T05) and the API's auth wiring (T09) exist;
until then it says so and exits non-zero rather than pretending to seed
anything.
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "seed: not wired yet -- lands once persistence (T05) and auth (T09) are on master",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
