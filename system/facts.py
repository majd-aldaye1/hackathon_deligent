"""A fact and where it came from.

POLICY.md principle 9: "Every decision names the records it relied on by their IDs ...
Cite what decided the hit, not everything you looked at."  So every fact carries the
record ids it was read from, and the `evidence` of a decision is assembled from the facts
the firing rule actually used — there is no separate evidence logic to keep in step.
"""


class Fact(object):
    """A value, and the record ids it came from."""

    __slots__ = ("value", "source_ids")

    def __init__(self, value, source_ids=()):
        self.value = value
        if isinstance(source_ids, str):
            source_ids = (source_ids,)
        self.source_ids = tuple(sorted({s for s in source_ids if s}))

    def with_sources(self, more):
        return Fact(self.value, tuple(self.source_ids) + tuple(more))

    def __eq__(self, other):
        return (
            isinstance(other, Fact)
            and self.value == other.value
            and self.source_ids == other.source_ids
        )

    def __hash__(self):
        return hash((self.value, self.source_ids))

    def __repr__(self):
        return "Fact(%r, %r)" % (self.value, list(self.source_ids))


def merge(facts):
    """Collapse facts that share a value, keeping every source.  Order is by value."""
    by_value = {}
    for fact in facts:
        if fact is None or fact.value is None:
            continue
        key = _key(fact.value)
        if key in by_value:
            by_value[key] = by_value[key].with_sources(fact.source_ids)
        else:
            by_value[key] = fact
    return [by_value[key] for key in sorted(by_value)]


def _key(value):
    getter = getattr(value, "key", None)
    if callable(getter):
        return getter()
    return value


def sources(*facts):
    """Every record id behind a group of facts, sorted and deduplicated."""
    out = set()
    for fact in facts:
        if fact is None:
            continue
        if isinstance(fact, (list, tuple, set, frozenset)):
            out |= set(sources(*fact))
        else:
            out |= set(fact.source_ids)
    return sorted(out)


def values(facts):
    return [f.value for f in facts]
