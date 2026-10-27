"""Exercise Tinta with the installed KOReader font API and framebuffer scaling."""
from pathlib import Path
import re
import tempfile

from lupa.luajit21 import LuaRuntime
from prepare_runtime import ROOT, prepare

koreader = ROOT / ".deps/install-stage-pw3/koreader"
framebuffer = (koreader / "ffi/framebuffer.lua").read_text(encoding="utf-8")
scale = re.search(r"function fb:scaleBySize\(px\).*?^end", framebuffer, re.M | re.S)
assert scale, "Pinned KOReader framebuffer scaling function not found"

with tempfile.TemporaryDirectory(prefix="font-regression-", dir=ROOT / ".deps") as temp:
    plugin = prepare(Path(temp) / "tinta.koplugin")
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().PLUGIN = plugin.as_posix()
    lua.globals().KOREADER_FONT = (koreader / "frontend/ui/font.lua").as_posix()
    lua.globals().KOREADER_SCALE = lua.execute("local fb = {}\n" + scale.group() + "\nreturn fb.scaleBySize")
    lua.execute((ROOT / "tests/font_scaling.lua").read_text(encoding="utf-8"))
