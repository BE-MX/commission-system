from datetime import datetime

from app.whatsapp import service
from app.whatsapp.models import WhatsAppAccount, WhatsAppConversation, WhatsAppPullCursor


def test_pull_messages_uses_per_conversation_cursors(db, monkeypatch):
    account = WhatsAppAccount(account_uid="wa_acc_test", ark_user_id=1, status="active")
    db.add(account)
    db.add_all(
        [
            WhatsAppConversation(
                conversation_uid="wa_acc_test:chat_a",
                account_uid="wa_acc_test",
                chat_id="chat_a",
                last_message_at=datetime(2026, 6, 16, 10, 0, 0),
            ),
            WhatsAppConversation(
                conversation_uid="wa_acc_test:chat_b",
                account_uid="wa_acc_test",
                chat_id="chat_b",
                last_message_at=datetime(2026, 6, 16, 9, 0, 0),
            ),
        ]
    )
    db.flush()

    calls = []

    class FakeConnectorClient:
        def pull_messages(self, account_uid, cursor, limit, chat_id=None):
            calls.append(
                {
                    "account_uid": account_uid,
                    "cursor": cursor,
                    "limit": limit,
                    "chat_id": chat_id,
                }
            )
            return {
                "items": [
                    {
                        "external_message_id": f"{chat_id}_msg_1",
                        "conversation_uid": f"wa_acc_test:{chat_id}",
                        "direction": "inbound",
                        "content_text": "hello",
                        "sent_at": "2026-06-16T10:30:00",
                    }
                ],
                "next_cursor": f"{chat_id}:cursor",
            }

    monkeypatch.setattr(service, "WhatsAppConnectorClient", FakeConnectorClient)

    count, synced_conversations, errors = service._pull_messages_for_account(
        db,
        account,
        per_chat_limit=25,
        conversation_limit=2,
    )

    assert count == 2
    assert synced_conversations == 2
    assert errors == 0
    assert [item["chat_id"] for item in calls] == ["chat_a", "chat_b"]
    assert all(item["limit"] == 25 for item in calls)

    cursors = {
        item.scope_uid: item.cursor_value
        for item in db.query(WhatsAppPullCursor).filter(WhatsAppPullCursor.resource == "messages").all()
    }
    assert cursors == {
        "wa_acc_test:chat_a": "chat_a:cursor",
        "wa_acc_test:chat_b": "chat_b:cursor",
    }
