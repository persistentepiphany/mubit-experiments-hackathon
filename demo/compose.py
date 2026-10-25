"""Assemble the filmed scenes into the final video.

1. Check the narration. video-demo writes where each line lands in a clip
   (<scene>.lines.json). No line may start before the previous one ends, and
   no line may fall inside a transition, where two clips' audio is mixed.
2. Frame the website scenes in the style of Recordly
   (github.com/webadderallorg/recordly): the capture sits on one of Recordly's
   wallpapers, blurred, with padding, rounded corners and a shadow. Explainer
   scenes are already full frame.
3. Join the clips with crossfades and level the audio.

    python3 demo/compose.py <demo-out/light> <wallpaper.jpg> <out.mp4>
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

W, H = 1920, 1080
TOUR = ["viz-intro", "viz-mubit", "task", "run1", "lesson", "viz-memory", "run2", "reuse", "viz-outro"]
FADE = 0.7          # seconds of crossfade between clips
GAP = 0.08          # the least silence allowed between two lines
LEAD = 0.35         # silence kept between a transition and the nearest line
RADIUS, SHADOW_BLUR, SHADOW_OFFSET, SHADOW_ALPHA = 22, 34, 18, 120


def probe(path: Path) -> tuple[int, int, float]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True).stdout.split()
    return int(out[0]), int(out[1]), float(out[2])


def check_narration(clips: list[Path]) -> list[str]:
    """Lines that start before the previous line in the same clip has ended."""
    problems = []
    for clip in clips:
        lines = sorted(json.loads(clip.with_suffix(".lines.json").read_text()), key=lambda l: l["at"])
        for before, after in zip(lines, lines[1:]):
            end = before["at"] + before["seconds"]
            if end + GAP > after["at"]:
                problems.append(f"{clip.stem}: \"{before['text'][:40]}\" runs {end - after['at']:.2f}s into the next line")
    return problems


def padding(clip: Path) -> tuple[float, float]:
    """Seconds of held frame and silence to add before and after a clip.

    The recorder keeps frames only when the screen changes, so a clip that
    ends on a still screen stops right after its last word. Padding both ends
    puts every transition over silence.
    """
    lines = sorted(json.loads(clip.with_suffix(".lines.json").read_text()), key=lambda l: l["at"])
    seconds = probe(clip)[2]
    if not lines:
        return 0.0, 0.0
    head = max(0.0, FADE + LEAD - lines[0]["at"])
    tail = max(0.0, lines[-1]["at"] + lines[-1]["seconds"] + FADE + LEAD - seconds)
    return head, tail


def cover(image: Image.Image, w: int, h: int) -> Image.Image:
    scale = max(w / image.width, h / image.height)
    image = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    left, top = (image.width - w) // 2, (image.height - h) // 2
    return image.crop((left, top, left + w, top + h))


def prepare(clip: Path, wallpaper: Path, out: Path, tmp: Path) -> None:
    """Pads a clip, and frames it on the wallpaper unless it is already full frame."""
    vw, vh, seconds = probe(clip)
    head, tail = padding(clip)
    total = f"{seconds + head + tail:.3f}"
    pad = f"tpad=start_mode=clone:start_duration={head:.3f}:stop_mode=clone:stop_duration={tail:.3f}"
    audio = f"[0:a]adelay={round(head * 1000)}:all=1,apad[a]"
    if (vw, vh) == (W, H):
        inputs, video = [], f"[0:v]{pad},format=yuv420p[o]"
    else:
        x, y = (W - vw) // 2, (H - vh) // 2
        background = cover(Image.open(wallpaper).convert("RGB"), W, H).filter(ImageFilter.GaussianBlur(18))
        shadow = Image.new("L", (W, H), 0)
        ImageDraw.Draw(shadow).rounded_rectangle((x, y + SHADOW_OFFSET, x + vw, y + vh + SHADOW_OFFSET), RADIUS, fill=SHADOW_ALPHA)
        background.paste(Image.new("RGB", (W, H), (20, 16, 12)), (0, 0), shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR)))
        mask = Image.new("L", (vw, vh), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, vw - 1, vh - 1), RADIUS, fill=255)
        background.save(tmp / "bg.png")
        mask.save(tmp / "mask.png")
        # The stills loop forever, so they and the output are cut to the clip's length.
        inputs = ["-loop", "1", "-framerate", "60", "-t", total, "-i", str(tmp / "bg.png"),
                  "-loop", "1", "-framerate", "60", "-t", total, "-i", str(tmp / "mask.png")]
        video = (f"[0:v]{pad},format=yuva420p[v];[2:v]format=gray[m];[v][m]alphamerge[r];"
                 f"[1:v][r]overlay={x}:{y}:shortest=1,format=yuv420p[o]")
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(clip), *inputs,
        "-filter_complex", f"{video};{audio}",
        "-map", "[o]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
        "-r", "60", "-c:a", "aac", "-b:a", "256k", "-t", total, str(out),
    ], check=True)


def stitch(clips: list[Path], out: Path) -> None:
    durations = [probe(c)[2] for c in clips]
    inputs = [arg for c in clips for arg in ("-i", str(c))]
    # Every clip on the same frame rate and timebase, which xfade requires.
    parts = [f"[{i}:v]fps=60,settb=AVTB,setsar=1[n{i}]" for i in range(len(clips))]
    video, audio, offset = "[n0]", "[0:a]", 0.0
    for i in range(1, len(clips)):
        offset += durations[i - 1] - FADE
        parts.append(f"{video}[n{i}]xfade=transition=fade:duration={FADE}:offset={offset:.3f}[v{i}]")
        parts.append(f"{audio}[{i}:a]acrossfade=d={FADE}:c1=tri:c2=tri[a{i}]")
        video, audio = f"[v{i}]", f"[a{i}]"
    parts.append(f"{video}format=yuv420p[vout]")
    parts.append(f"{audio}loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[aout]")
    graph = ";".join(parts)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-stats", *inputs, "-filter_complex", graph,
        "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out),
    ], check=True)


def main(corpus: Path, wallpaper: Path, out: Path) -> None:
    clips = [corpus / f"{name}.mp4" for name in TOUR]
    problems = check_narration(clips)
    if problems:
        sys.exit("narration overlaps:\n  " + "\n  ".join(problems))
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        ready = []
        for clip in clips:
            prepared = tmp / f"{clip.stem}.prepared.mp4"
            prepare(clip, wallpaper, prepared, tmp)
            ready.append(prepared)
        stitch(ready, out)
    print(f"compose: {out} ({probe(out)[2]:.1f}s)")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
