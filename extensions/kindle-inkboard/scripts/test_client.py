"""Run real LuaJIT 2.1 code using an isolated local runtime, without a Kindle."""
from pathlib import Path
import os
import sys

from lupa.luajit21 import LuaRuntime

root = Path(__file__).resolve().parents[1]
lua = LuaRuntime(unpack_returned_tuples=True)
lua.globals().CLIENT_ROOT = root.as_posix()
lua.execute((root / "tests/client.lua").read_text(encoding="utf-8"))
lua.execute((root / "tests/transport.lua").read_text(encoding="utf-8"))
