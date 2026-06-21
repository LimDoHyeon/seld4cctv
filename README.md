<div align="center">
  <h1>Omniverse: CCTV Sound Source Localization</h1>
  <table border="0" style="border-collapse: collapse; border: none;">
    <tr style="border: none; background: transparent;">
      <td align="center" style="border: none; padding: 0 32px;">
        <strong>Jongmoon Ryu</strong>
      </td>
      <td align="center" style="border: none; padding: 0 32px;">
        <strong>Dohyeon Lim</strong>
      </td>
    </tr>
  </table>
</div>

<br/>

<i> This repository provides an NVIDIA Omniverse-based CCTV simulation for sound event localization. It demonstrates how urban sound events such as yelling, crashes, explosions, and gunshots can be triggered in a virtual city environment, while nearby CCTV cameras automatically orient toward the estimated event position. </i>

<br/>

<div align="center">

![sample demonstration](./scripts/assets/demo.gif)

</div>

<br/>

## Installation

This project is designed to run with the NVIDIA Omniverse Kit App Template. 

First, download and set up the official Kit App Template by following the instructions from: https://github.com/NVIDIA-Omniverse/kit-app-template

Then, place this repository at the same directory level as `kit-app-template/`.

```
omniverse/
├── kit-app-template/
└── cctv_sim/
```

The expected workflow is to launch Omniverse from `kit-app-template/`, then run the CCTV simulation scripts from the Omniverse Script Editor.

<br/>

## Quick Start

From the `kit-app-template` directory, launch Omniverse with:

```sh
./repo.sh launch
```

After Omniverse is launched, open the **Script Editor** and run the following script to load the city stage and start the CCTV simulation runtime.

```py
from pathlib import Path
import omni.usd

CCTV_SIM_ROOT = Path("../cctv_sim").resolve()

city_usd = CCTV_SIM_ROOT / "assets" / "city" / "World_CityDemopack.usd"
stop_script = CCTV_SIM_ROOT / "scripts" / "stop_demo.py"
start_script = CCTV_SIM_ROOT / "scripts" / "start_demo.py"

def run_script(path):
    namespace = {
        "__name__": "__main__",
        "__file__": str(path),
        "CCTV_SIM_ROOT": str(CCTV_SIM_ROOT),
    }
    exec(
        compile(path.read_text(encoding="utf-8"), str(path), "exec"),
        namespace,
    )

opened = omni.usd.get_context().open_stage(str(city_usd).replace("\\", "/"))
if not opened:
    raise RuntimeError(f"Failed to open stage: {city_usd}")

run_script(stop_script)
run_script(start_script)
```

<br/>

## Windows

### CCTV Sound Event Demo

| Button | Behavior |
| --- | --- |
| `+CHAR1` | Adds a walking character on the first route. |
| `+CHAR2` | Adds a walking character on the second route. |
| `-CHAR` | Removes the most recently added character. |
| `yell` | Plays the yell animation on a random character and starts `scream.wav`. Nearby CCTV cameras aim at the event position. |
| `crash` | Shows one `/World/Events/CarCrash/crash_*` asset and plays `crash.wav`. |
| `explosion` | Selects an explosion source prim, creates a live reference to `assets/usd/explosion.usd`, and plays `explosion.wav`. The live prim is removed when the animation finishes. |
| `gun` | Plays the gunshot animation on a random character and plays `gunshot.wav` five times, starting at frame 5 with a 36-frame interval. |

<br/>

### CCTV Monitor

Live feeds are off by default to reduce resource usage. When the monitor first opens, a black panel with `LIVE STOPPED` is expected.

| Button | Behavior |
| --- | --- |
| `PERS` | Returns the main viewport to `/OmniverseKit_Persp`. |
| `LIVE` / `STOP` | Enables or disables live viewport rendering for the current monitor layout. |
| `ENTIRE` | Shows the 2x2 CCTV grid inside the monitor window. Pressing `ENTIRE` again while already in this mode swaps the monitor grid between outer views and ViewCamera views. The main viewport is left unchanged. |
| `CCTV1` - `CCTV4` | Shows a single CCTV feed at the full monitor size. The main viewport uses the live ViewCamera by default, while the monitor prefers the outer camera. Pressing the same CCTV button again swaps the main viewport and monitor roles. |

Monitor rendering FPS is controlled by `CCTV_MONITOR_MAX_FPS` in `sim/config.py`. The current default is 30 FPS.
