"""Username helpers shared by demo seeding and account migrations."""
import re
import unicodedata


_TITLES = {"dr", "drs", "prof", "dokter"}


def simple_username(full_name: str) -> str:
    """Build a readable login name such as ``bima.setiawan`` from a profile name."""
    normalized = unicodedata.normalize("NFKD", full_name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii").casefold()
    parts = re.findall(r"[a-z0-9]+", ascii_name)
    while parts and parts[0] in _TITLES:
        parts.pop(0)
    return ".".join(parts)[:40].strip(".")
