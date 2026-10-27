"""Run the upstream headless UI harness with the packaged host and Ark app on Windows."""
from pathlib import Path
import os
import re
import shutil
import tempfile
import argparse

from lupa.luajit21 import LuaRuntime
from prepare_runtime import ROOT, prepare


class LuaExit(Exception):
    pass

parser = argparse.ArgumentParser()
parser.add_argument("--scenario", action="store_true")
parser.add_argument("--full-ui", action="store_true", help="Run upstream's complete bundled-app UI flow")
parser.add_argument("--chinese-ui", action="store_true", help="Exercise the Chinese settings and bundled apps")
args = parser.parse_args()


with tempfile.TemporaryDirectory(prefix="runtime-", dir=ROOT / ".deps") as temporary:
    directory = Path(temporary)
    prepare(directory / "tinta.koplugin")
    # The upstream full-suite fixtures assume only upstream's bundled apps.
    # Ark has its own smoke/scenario runs, including its extra wake requests.
    if not args.full_ui:
        shutil.copytree(ROOT / "client/ark_board", directory / "tinta.koplugin/apps/ark_board")
    shutil.copytree(ROOT / ".deps/tinta/tests", directory / "tests")
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute('package.path = "tinta.koplugin/?.lua;" .. package.path')
    lua.globals().PY_TEMP = temporary.replace("\\", "/")
    lua.globals().ARK_SCENARIO = args.scenario
    lua.globals().FULL_UI = args.full_ui
    lua.globals().CHINESE_UI = args.chinese_ui
    lua.globals().CLIENT_ROOT = ROOT.as_posix()
    framebuffer = (ROOT / ".deps/install-stage-pw3/koreader/ffi/framebuffer.lua").read_text(encoding="utf-8")
    scale = re.search(r"function fb:scaleBySize\(px\).*?^end", framebuffer, re.M | re.S)
    assert scale, "Pinned KOReader framebuffer scaling function not found"
    lua.globals().KOREADER_SCALE = lua.execute("local fb = {}\n" + scale.group() + "\nreturn fb.scaleBySize")
    def tmpname():
        handle, name = tempfile.mkstemp(dir=temporary)
        os.close(handle)
        return name.replace("\\", "/")
    def shell(command):
        match = re.fullmatch(r'(mkdir -p|rm -rf) "([^"]+)"', command)
        if not match:
            raise RuntimeError("Unsupported test shell command")
        target = Path(match[2]).resolve()
        if not target.is_relative_to(directory.resolve()):
            raise RuntimeError("Test filesystem escape")
        if match[1] == "mkdir -p":
            target.mkdir(parents=True, exist_ok=True)
        elif target.exists():
            shutil.rmtree(target)
        return 0
    def listdir(command):
        match = re.fullmatch(r'ls -1 "([^"]+)"', command)
        if not match:
            raise RuntimeError("Unsupported test inventory")
        return lua.table_from(sorted(p.name for p in Path(match[1]).iterdir()))
    lua.globals().py_tmpname = tmpname
    lua.globals().py_shell = shell
    lua.globals().py_listdir = listdir
    lua.globals().py_exit = lambda code: (_ for _ in ()).throw(LuaExit(int(code)))
    lua.execute('''
        os.tmpname = py_tmpname
        os.execute = py_shell
        os.exit = py_exit
        local env = os.getenv
        os.getenv = function(key) if key == "SMOKE_APP" then return not (ARK_SCENARIO or FULL_UI or CHINESE_UI) and "ark_board" or nil elseif key == "QUIET" then return "1" end; return env(key) end
        if CHINESE_UI then SMOKE_SCENARIO = assert(loadfile(CLIENT_ROOT .. "/tests/chinese_ui_scenario.lua"))()
        elseif ARK_SCENARIO then SMOKE_SCENARIO = assert(loadfile(CLIENT_ROOT .. "/tests/runtime_scenario.lua"))() end
        io.popen = function(command)
            local rows = py_listdir(command)
            return { lines = function() local i = 0; return function() i = i + 1; return rows[i] end end,
                close = function() end, read = function() return table.concat(rows, "\\n") end }
        end
    ''')
    previous = Path.cwd()
    try:
        os.chdir(directory)
        try:
            smoke = (directory / "tests/tinta_ui_smoke.lua").read_text(encoding="utf-8")
            # Upstream's font stub skipped KOReader's screen scaling, hiding the
            # PW3 double-scaling bug. Model that external API before drawing.
            old = 'return { name = name, size = size }'
            assert smoke.count(old) == 1
            smoke = smoke.replace(old, 'return { name = name, size = require("device").screen:scaleBySize(size) }')
            marker = 'local battery = { pct = 82, charging = false }'
            assert smoke.count(marker) == 1
            smoke = smoke.replace(marker, 'Screen.scaleBySize = KOREADER_SCALE\n' + marker)
            lua.execute(smoke)
        except LuaExit as result:
            if result.args[0] != 0:
                raise SystemExit(result.args[0])
    finally:
        os.chdir(previous)
