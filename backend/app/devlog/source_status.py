"""P0 collection is complete only when every required source succeeded."""
REQUIRED_SOURCES = frozenset({"git", "fetch", "releases"})


def sources_complete(sources: list[dict]) -> bool:
    return (len(sources) == len(REQUIRED_SOURCES)
            and {source.get("name") for source in sources} == REQUIRED_SOURCES
            and all(source.get("ok") is True for source in sources))
