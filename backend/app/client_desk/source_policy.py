"""Source policy follows the complete dependency tree, including inherited summaries."""


def manual_only(dependencies):
    if isinstance(dependencies, dict):
        return dependencies.get("policy") == "manual_only_v1" or any(
            manual_only(value) for value in dependencies.values()
        )
    if isinstance(dependencies, (list, tuple)):
        return any(manual_only(value) for value in dependencies)
    return False


def restricted_row(row):
    return bool(getattr(row, "selected_feed_item_ids", None)) or manual_only(
        row.source_dependencies
    )


def previous_brief(state, dependencies):
    # Exact complete-dependency equality prevents inherited text laundering.
    # A mixed summary is indivisible; fall back to an eligible previous version.
    for body, deps in (
        ("brief_md", "brief_dependencies"),
        ("brief_prev_md", "brief_prev_dependencies"),
    ):
        if state.get(deps) == dependencies:
            return state.get(body)
    return None
