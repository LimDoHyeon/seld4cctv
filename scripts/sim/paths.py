from pathlib import Path

# .../cctv_sim/scripts/sim/paths.py
THIS_FILE = Path(__file__).resolve()

SIM_DIR = THIS_FILE.parent                  # cctv_sim/scripts/sim
SCRIPTS_DIR = SIM_DIR.parent                # cctv_sim/scripts
PROJECT_ROOT = SCRIPTS_DIR.parent           # cctv_sim
OMNIVERSE_ROOT = PROJECT_ROOT.parent         # omniverse

KIT_ROOT = OMNIVERSE_ROOT / "kit-app-template"
ASSETS_DIR = PROJECT_ROOT / "assets"

USD_DIR = ASSETS_DIR / "usd"
WAV_DIR = ASSETS_DIR / "wav"
CITY_DIR = ASSETS_DIR / "city"

WALKING_MAN_USD = USD_DIR / "walking_man1.usd"
YELLING_MAN_USD = USD_DIR / "yelling_man1.usd"
SHOOTING_MAN_USD = USD_DIR / "shooting_man1.usd"
CCTV_USD = USD_DIR / "cctv.usda"
EXPLOSION_USD = USD_DIR / "explosion.usd"
GUNSHOT_WAV = WAV_DIR / "gunshot.wav"
CRASH_WAV = WAV_DIR / "crash.wav"
SCREAM_WAV = WAV_DIR / "scream.wav"
EXPLOSION_WAV = WAV_DIR / "explosion.wav"

def as_usd_path(path: Path) -> str:
    return str(path).replace("\\", "/")
