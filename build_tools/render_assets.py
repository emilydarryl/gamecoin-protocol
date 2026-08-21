from __future__ import annotations

from pathlib import Path

import cairosvg
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SOURCE = ASSETS / "gamecoin_protocol_mark.svg"
MARK_PNG = ASSETS / "gamecoin_protocol_mark.png"
FULL_PNG = ASSETS / "gamecoin_protocol_full.png"
ICON = ASSETS / "gamecoin_protocol_mark.ico"


def main() -> None:
    # The vector mark is the authoritative branding build input.  Raster files
    # are generated during builds so every binary input is derived from source.
    cairosvg.svg2png(url=str(SOURCE), write_to=str(MARK_PNG), output_width=1024, output_height=1024)
    cairosvg.svg2png(url=str(SOURCE), write_to=str(FULL_PNG), output_width=1024, output_height=1024)
    with Image.open(MARK_PNG) as image:
        image.save(ICON, format="ICO", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    for path in (MARK_PNG, FULL_PNG, ICON):
        print(f"generated {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
