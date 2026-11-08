"""ULID generation without a network or external runtime dependency."""
from datetime import datetime, timezone
import secrets

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    timestamp = int(datetime.now(timezone.utc).timestamp() * 1000) & ((1 << 48) - 1)
    value = (timestamp << 80) | secrets.randbits(80)
    chars = ["0"] * 26
    for index in range(25, -1, -1):
        chars[index] = CROCKFORD[value & 31]
        value >>= 5
    return "".join(chars)
