"""Check every shipped Chinese string against the pinned English interface keys."""
from pathlib import Path
import argparse
import json
import re
import shutil
import tempfile

from lupa.luajit21 import LuaRuntime
from prepare_runtime import ROOT, prepare

parser = argparse.ArgumentParser()
parser.add_argument("--upstream", action="store_true", help="Confirm the original runtime lacks Chinese")
args = parser.parse_args()
with tempfile.TemporaryDirectory(prefix="chinese-regression-", dir=ROOT / ".deps") as temp:
    plugin = Path(temp) / "tinta.koplugin"
    if args.upstream:
        shutil.copytree(ROOT / ".deps/tinta/tinta.koplugin", plugin)
    else:
        prepare(plugin)
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("package.path = " + json.dumps(plugin.as_posix() + "/?.lua;") + " .. package.path")
    groups = {"core": "core/i18n.lua", "ui": "ui/strings.lua"}
    groups.update({p.parent.name: p.relative_to(ROOT / ".deps/tinta/tinta.koplugin").as_posix()
                   for p in (ROOT / ".deps/tinta/tinta.koplugin/apps").glob("*/strings.lua")
                   if not p.parent.name.startswith("_")})
    formatter = lua.eval("string.format")
    def specs(s):
        return re.findall(r"%[-+0 #]*\d*(?:\.\d+)?[dsfxq]", s.replace("%%", ""))
    count = 0
    for group, relative in groups.items():
        original = lua.execute((ROOT / ".deps/tinta/tinta.koplugin" / relative).read_text(encoding="utf-8"))
        patched = lua.execute((plugin / relative).read_text(encoding="utf-8"))
        english = original["STRINGS"]["en"] if group == "core" else original["en"]
        chinese = patched["STRINGS"]["zh"] if group == "core" else patched["zh"]
        assert chinese is not None, f"{group}: Chinese interface is missing"
        expected = json.loads((ROOT / f"client/locales/zh/{group}.json").read_text(encoding="utf-8"))
        assert set(expected) == set(english), f"{group}: missing or stale translation keys"
        for key, source in english.items():
            value = chinese[key]
            assert value == expected[key] and value.strip(), f"{group}.{key}: missing translation"
            assert specs(value) == specs(source), f"{group}.{key}: changed format arguments"
            sample = [3 if spec[-1] in "dfx" else "示例" for spec in specs(source)]
            formatter(value, *sample)
            count += 1
    core = lua.eval('require("core/i18n")')
    ui = lua.eval('require("ui/strings")')
    core.set_lang("zh"); ui.set_lang("zh")
    assert core.get_lang() == "zh" and ui.get_lang() == "zh"
    assert core.t("nav_home") == "首页" and ui.t("menu_system") == "系统设置"
    assert ui["LANG_NAMES"]["en"] == "英语" and ui["LANG_NAMES"]["zh"] == "简体中文"
    print(f"Chinese localization: {count} texts complete; format arguments and language selection passed")
