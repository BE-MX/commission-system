import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


def _load(name):
    path = Path(__file__).parents[1] / "project-radar-bot" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RadarPayloadTest(unittest.TestCase):
    def test_single_chat_text_maps_to_idempotent_inbound_contract(self):
        message = SimpleNamespace(conversation_type="1", text=SimpleNamespace(content=" https://github.com/a/b "),
                                  message_id="msg-1", sender_staff_id="staff-1")
        self.assertEqual(_load("payload").message_payload(message), {
            "message_id": "msg-1", "dingtalk_id": "staff-1", "text": "https://github.com/a/b",
        })

    def test_group_and_empty_messages_are_not_forwarded(self):
        base = dict(text=SimpleNamespace(content="hello"), message_id="m", sender_staff_id="s")
        self.assertIsNone(_load("payload").message_payload(SimpleNamespace(conversation_type="2", **base)))
        self.assertIsNone(_load("payload").message_payload(SimpleNamespace(conversation_type="1", **{**base, "text": SimpleNamespace(content=" ")})))


if __name__ == "__main__":
    unittest.main()
