import os
from pathlib import Path

import omni.usd


PROJECT_DIR_NAME = "cctv_sim"
STAGE_FILES = {
    "city": "city_demo_street_only_stage.usda",
    "light": "light_street_stage.usda",
}


def _project_root_from_override(root_value):
    if not root_value:
        return None
    root = Path(root_value).expanduser().resolve()
    if (root / "assets" / "usd").exists() and (root / "scripts").exists():
        return root
    return None


def _resolve_project_root():
    file_value = globals().get("__file__")
    if file_value:
        root = Path(file_value).resolve().parent.parent
        if (root / "assets" / "usd").exists():
            return root

    for root_override in (globals().get("CCTV_SIM_ROOT"), os.environ.get("CCTV_SIM_ROOT")):
        root = _project_root_from_override(root_override)
        if root is not None:
            return root

    cwd = Path.cwd().resolve()
    for base in (cwd, *cwd.parents):
        for candidate in (base, base / PROJECT_DIR_NAME):
            if (candidate / "assets" / "usd").exists() and (candidate / "scripts").exists():
                return candidate

    raise RuntimeError("Unable to locate cctv_sim project root.")


variant = str(globals().get("STREET_STAGE_VARIANT", "city")).strip().lower()
if variant not in STAGE_FILES:
    raise ValueError(f"Unknown STREET_STAGE_VARIANT={variant!r}. Use one of: {', '.join(STAGE_FILES)}")

project_root = _resolve_project_root()
stage_path = project_root / "assets" / "usd" / STAGE_FILES[variant]
if not stage_path.exists():
    raise FileNotFoundError(stage_path)

opened = omni.usd.get_context().open_stage(str(stage_path).replace("\\", "/"))
print(f"[open_street_stage] variant={variant} path={stage_path}")
print(f"[open_street_stage] open_stage returned: {opened}")
print("[open_street_stage] After the stage finishes loading, run start_demo.py.")
