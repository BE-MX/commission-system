"""Pin and adapt Tinta's host without changing the downloaded source checkout."""
from pathlib import Path
import hashlib
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PIN = "9c70aa08132ccb7a12d4eb1bf639809fa8740d74"


def prepare(destination):
    source = ROOT / ".deps/tinta"
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if actual != PIN:
        raise RuntimeError(f"Unexpected Tinta revision: {actual}")
    if destination.exists():
        raise FileExistsError(destination)
    shutil.copytree(source / "tinta.koplugin", destination)
    host = destination / "ui/host.lua"
    text = host.read_text(encoding="utf-8")
    old = "                wake_at = function(ts) self:wakeRequest(id, ts) end,"
    new = old + '''
                -- Ark callbacks only run after the host's outer SQLite transaction commits.
                after_commit = function(fn)
                    assert(self.after_commit_queue, "after_commit outside refresh")
                    self.after_commit_queue[#self.after_commit_queue + 1] = { id = id, fn = fn }
                end,
                is_durable = function() return self.c and self.c.store and self.c.store.kind == "sqlite" end,
                dismiss_popup = function()
                    if self.window and self.window.dialog and self.window.dialog.owner == id then
                        self.window.dialog = nil
                        self.window:clearBanner()
                        self.window:render("full")
                    end
                end,'''
    text = replace(text, old, new)
    text = replace(text, "    C.transaction(self.c, function()\n        for _, id in ipairs(ids) do", "    self.after_commit_queue = {}\n    local committed = C.transaction(self.c, function()\n        for _, id in ipairs(ids) do")
    text = replace(text, "    looping = false\n    if pending == 0 then finish()", '''    local callbacks = self.after_commit_queue
    self.after_commit_queue = nil
    if not committed then
        -- Invalidate per-app memoized caches after rollback before the next retry.
        for _, id in ipairs(ids) do
            local ctx = self.c.registry:ctx(id)
            if ctx and ctx.cache and ctx.cache.reset then ctx.cache.reset() end
        end
        -- A scheduled sleep refresh has already opened Wi-Fi and marked itself busy.
        -- Its completion callback must run on storage failure as well as success.
        if on_done then finish() end
        logger.warn("Tinta local storage transaction did not commit")
        return false
    end
    for _, callback in ipairs(callbacks) do self:callAppFn(callback.id, callback.fn, "after_commit") end
    looping = false
    if pending == 0 then finish()''')
    old = "            if known[id] and not have[id] then have[id] = true; picked[#picked + 1] = id end"
    new = old + '\n            local app = self:app(id)\n            if known[id] and app and app.net then need_net = true end'
    text = replace(text, old, new)
    host.write_text(text, encoding="utf-8", newline="\n")
    drawing = destination / "ui/draw.lua"
    text = drawing.read_text(encoding="utf-8")
    text = replace(text, 'local Font = require("ui/font")',
                   'local Font = require("ui/font")\nlocal Screen = require("device").screen')
    text = replace(text, "function M.face(size) return Font:getFace(T.FONT, size) end", '''-- Theme font sizes are already physical pixels. Font:getFace applies
-- Screen:scaleBySize again, including any KOReader DPI override. Undo that
-- conversion here rather than modifying KOReader's global settings.
function M.face(size)
    -- Sample at 1024 units so scaleBySize's ceil does not quantize the factor
    -- at small font sizes. The epsilon avoids an extra pixel from float noise.
    local scale = Screen:scaleBySize(1024) / 1024
    return Font:getFace(T.FONT, (size - 1e-6) / scale)
end''')
    drawing.write_text(text, encoding="utf-8", newline="\n")
    from localize_runtime import apply_chinese
    apply_chinese(destination)
    return destination


def replace(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Pinned runtime patch context changed")
    return text.replace(old, new)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(prepare(args.destination))
