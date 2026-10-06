"""Annex A Source Precedence Policy, in code. Owner: A."""


def resolve(chunks: list[dict], as_of_date: str, student: dict | None) -> dict:
    """applicability -> explicit supersession (level 1-2) -> authority -> recency -> unresolved."""
    return {"applicable": chunks, "excluded_future": [], "superseded": [],
            "conflicts": [], "decision": "stub: no policy applied yet", "unresolved": False}
