"""Migration seed helpers used only by regression tests, never runtime."""
import json
from copy import deepcopy
from pathlib import Path
from app.expo import ai_pipeline
from app.expo.models import ExpoPromptVersion
from app.expo.prompt_renderer import render_prompt, color_clause, wardrobe_clause

SEEDS = json.loads((Path(__file__).parents[1] / "alembic/data/139_expo_prompt_versions.json").read_text(encoding="utf-8"))
PROMPT_VARIANTS = ("real", "soft", "beauty")
DEFAULT_PROMPT_VARIANT = "real"
def config(variant="real"):
    return deepcopy(SEEDS[PROMPT_VARIANTS.index(variant)]["config_json"])
def seed_versions(db):
    db.add_all([ExpoPromptVersion(**deepcopy(row)) for row in SEEDS])
    db.commit()
def build_prompt(session, row, wig, variant="real"):
    return render_prompt(session, row, wig, config(variant), ai_pipeline.to_abs)
def finish(variant):
    return config(variant)["parts"]["finish"]
def color(value):
    return color_clause(config(), value)
def wardrobe(uniform=False):
    return wardrobe_clause(config(), uniform)
_OUTFIT_LOOKS = config()["outfit_options"]
