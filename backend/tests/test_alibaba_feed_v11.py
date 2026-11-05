"""Strict registered v1.1 envelope and truthful activity-window semantics."""
import copy
from datetime import datetime

import pytest

from app.alibaba_feed.errors import FeedError
from app.alibaba_feed.validation import parse_envelope
from app.alibaba_feed.v11_validation import quality
from tests.test_alibaba_feed_core import payload, raw, NOW


def v11_payload(run_id="v11-a", *, selection="created_window", revision=1):
    data = payload(run_id)
    data.update(schema="ark_alibaba_feed_v1.1", source_account_uid="test-shop")
    data["run"].update(collector_id="test-collector", collector_version="1",
                       coverage={"selection": selection, "all_pages_read": True,
                                 "activity_scan_complete": selection == "activity_window",
                                 "activity_window_start": None, "activity_window_end": None})
    if selection == "activity_window":
        data["run"]["window"]["basis"] = "conversation_last_activity_at"
        data["run"]["coverage"].update(activity_window_start=data["run"]["window"]["start"],
                                        activity_window_end=data["run"]["window"]["end"])
    record = data["records"][0]
    record.update(buyer_id="buyer-a", conversation_id="conv-a", assignee_external_user_id=None,
                  observed_at=data["run"]["reply_status_snapshot_at"], snapshot_revision=revision,
                  conversation_revision=revision, last_activity_at="2026-11-04T06:00:00+08:00",
                  coverage={"history_complete": True, "latest_complete": True, "has_more": False,
                            "covered_from": "2026-11-04T05:00:00+08:00",
                            "covered_through": data["run"]["reply_status_snapshot_at"],
                            "edits_observable": True, "deletions_observable": True})
    record["messages"][0].update(message_id="msg-a", source_order=1, actor_type="human",
                                  sender_external_user_id=None, message_revision=1, deleted_at=None)
    return data


def test_v11_valid_and_unregistered_fields_rejected():
    data = v11_payload()
    assert parse_envelope(raw(data), "v11-a", NOW)["schema"] == "ark_alibaba_feed_v1.1"
    data["records"][0]["messages"][0]["execute_url"] = "https://invalid.example/"
    with pytest.raises(FeedError):
        parse_envelope(raw(data), "v11-a", NOW)


@pytest.mark.parametrize("change", ["revision_bool", "revision_overflow", "naive_observed", "invalid_role", "float_order", "wrong_basis", "mismatched_activity"])
def test_v11_rejects_invalid_semantics(change):
    data = v11_payload(selection="activity_window")
    record = data["records"][0]
    if change == "revision_bool":
        record["snapshot_revision"] = True
    elif change == "revision_overflow":
        record["conversation_revision"] = 2**63
    elif change == "naive_observed":
        record["observed_at"] = "2026-11-05T05:20:00"
    elif change == "invalid_role":
        record["messages"][0]["actor_type"] = "salesperson"
    elif change == "float_order":
        record["messages"][0]["source_order"] = 1.5
    elif change == "wrong_basis":
        data["run"]["window"]["basis"] = "inquiry_created_at"
    else:
        data["run"]["coverage"]["activity_window_end"] = None
    with pytest.raises(FeedError):
        parse_envelope(raw(data), "v11-a", NOW)


def test_activity_window_uses_last_activity_instead_of_old_creation():
    data = v11_payload(selection="activity_window")
    record = data["records"][0]
    record.update(created_at="2023-01-01", created_at_precision="day")
    parse_envelope(raw(data), "v11-a", NOW)
    assert quality(record, data["run"]["window"], "activity_window", 65536) == ("in_window", [])
    record["last_activity_at"] = None
    window, issues = quality(record, data["run"]["window"], "activity_window", 65536)
    assert window == "uncertain" and "ACTIVITY_TIME_UNKNOWN" in issues and "WINDOW_OUTSIDE" not in issues


def test_missing_stable_identity_is_archivable_but_not_invented():
    data = v11_payload()
    record = data["records"][0]
    record.update(conversation_id=None, conversation_revision=None, buyer_id=None)
    record["messages"][0].update(message_id=None, source_order=None, actor_type="unknown")
    assert parse_envelope(raw(data), "v11-a", NOW)["records"][0]["conversation_id"] is None
