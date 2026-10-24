"""Put the stitched tour in a Recordly-style frame.

Recordly (github.com/webadderallorg/recordly) is a desktop recorder whose
editor places a capture on a wallpaper with padding, rounded corners and a
drop shadow. It needs a desktop session, so this reproduces that frame with
ffmpeg instead: the wallpaper (one of Recordly's own, blurred as its editor
does) and the shadow are rendered once as a still, the rounded corners are an
alpha mask, and ffmpeg overlays every frame of the tour onto them.

    python3 demo/frame.py <tour.mp4> <wallpaper.jpg> <out.mp4>
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

W, H = 1920, 1080
RADIUS = 22
SHADOW_BLUR = 34
SHADOW_OFFSET = 18
SHADOW_ALPHA = 120


def probe(path: Path) -> tuple[int, int, str]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True).stdout.split()
    return int(out[0]), int(out[1]), out[2]


def cover(image: Image.Image, w: int, h: int) -> Image.Image:
    scale = max(w / image.width, h / image.height)
    image = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    left, top = (image.width - w) // 2, (image.height - h) // 2
    return image.crop((left, top, left + w, top + h))


def main(tour: Path, wallpaper: Path, out: Path) -> None:
    vw, vh, seconds = probe(tour)
    x, y = (W - vw) // 2, (H - vh) // 2

    background = cover(Image.open(wallpaper).convert("RGB"), W, H).filter(ImageFilter.GaussianBlur(18))
    shadow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shadow).rounded_rectangle(
        (x, y + SHADOW_OFFSET, x + vw, y + vh + SHADOW_OFFSET), RADIUS, fill=SHADOW_ALPHA)
    shadow = shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))
    background.paste(Image.new("RGB", (W, H), (20, 16, 12)), (0, 0), shadow)

    mask = Image.new("L", (vw, vh), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, vw - 1, vh - 1), RADIUS, fill=255)

    with tempfile.TemporaryDirectory() as tmp:
        bg_path, mask_path = Path(tmp) / "bg.png", Path(tmp) / "mask.png"
        background.save(bg_path)
        mask.save(mask_path)
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-stats",
            # The stills loop forever, so every input and the output are cut to the tour's length.
            "-i", str(tour),
            "-loop", "1", "-framerate", "60", "-t", seconds, "-i", str(bg_path),
            "-loop", "1", "-framerate", "60", "-t", seconds, "-i", str(mask_path),
            "-filter_complex",
            f"[2:v]format=gray[m];[0:v]format=yuva420p[v];[v][m]alphamerge[r];"
            f"[1:v][r]overlay={x}:{y}:shortest=1,format=yuv420p[out]",
            "-map", "[out]", "-map", "0:a?", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-r", "60", "-c:a", "aac", "-b:a", "192k", "-t", seconds, "-movflags", "+faststart", str(out),
        ], check=True)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
