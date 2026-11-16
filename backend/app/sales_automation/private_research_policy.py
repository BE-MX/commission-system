"""Scope and schema identifiers shared by private research v2 entry points."""

PRIVATE_RESEARCH_POLICY = "private-research-v2"
PRIVATE_RESEARCH_RESULT = "private_research_v2"
LEGACY_ENRICHMENT_POLICY = "private-enrichment-v1"
PRIVATE_RESEARCH_POLICIES = frozenset({PRIVATE_RESEARCH_POLICY, LEGACY_ENRICHMENT_POLICY})


def is_private_research_v2(task) -> bool:
    return (
        task.research_policy_version == PRIVATE_RESEARCH_POLICY
        and task.task_type == "full_research"
        and task.source_ref_type == "manual"
    )
