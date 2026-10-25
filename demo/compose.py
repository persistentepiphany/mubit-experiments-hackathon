"""Assemble the filmed scenes into the final, captioned video.

1. Check the lines. video-demo writes where each line lands in a clip
   (<scene>.lines.json); no line may start before the previous one ends.
2. Tighten each clip: a silent stretch between lines (scrolling, clicking,
   waiting for the page) longer than MAX_GAP is played faster, at most
   MAX_SPEED times, while every line keeps its own pace.
3. Frame each clip in the style of Recordly (github.com/webadderallorg/recordly):
   the capture sits on one of Recordly's wallpapers, blurred, with rounded
   corners and a shadow, raised to leave a band below it for captions.
4. Join the clips with crossfades and burn in each line as a caption. The
   film has no voice-over, so the synthesised audio, which only timed the
   lines, is dropped.

    python3 demo/compose.py <demo-out/light> <wallpaper.jpg> <out.mp4>
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

W, H = 1920, 1080
TOP = 34            # the window's distance from the top edge; captions sit below it
TOUR = ["viz-mubit", "task", "run1", "lesson", "viz-memory", "run2", "reuse", "viz-outro"]
FADE = 0.7          # seconds of crossfade between clips
GAP = 0.08          # the least time between two lines
LEAD = 0.35         # time kept between a transition and the nearest line
MAX_GAP = 1.2       # a silent stretch longer than this is played faster...
MAX_SPEED = 3.0     # ...but never more than this much faster
LINGER = 0.9        # a caption stays up this long after its line, unless the next one starts
RADIUS, SHADOW_BLUR, SHADOW_OFFSET, SHADOW_ALPHA = 22, 30, 14, 110


def probe(path: Path) -> tuple[int, int, float]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True).stdout.split()
    return int(out[0]), int(out[1]), float(out[2])


def lines_of(clip: Path) -> list[dict]:
    return sorted(json.loads(clip.with_suffix(".lines.json").read_text()), key=lambda l: l["at"])


def check_lines(clips: list[Path]) -> list[str]:
    """Lines that start before the previous line in the same clip has ended."""
    problems = []
    for clip in clips:
        lines = lines_of(clip)
        for before, after in zip(lines, lines[1:]):
            end = before["at"] + before["seconds"]
            if end + GAP > after["at"]:
                problems.append(f"{clip.stem}: \"{before['text'][:40]}\" runs {end - after['at']:.2f}s into the next line")
    return problems


def tighten(clip: Path, out: Path) -> list[dict]:
    """Plays each long silent stretch faster; returns the lines on the new timeline."""
    lines = lines_of(clip)
    seconds = probe(clip)[2]
    cuts, at = [], 0.0
    for line in lines:
        cuts.append((at, line["at"], None))
        cuts.append((line["at"], min(seconds, line["at"] + line["seconds"]), line))
        at = line["at"] + line["seconds"]
    cuts.append((at, seconds, None))
    parts, labels, moved, now = [], [], [], 0.0
    for i, (start, end, line) in enumerate(c for c in cuts if c[1] - c[0] > 0.01):
        length = end - start
        new = length if line or length <= MAX_GAP else max(MAX_GAP, length / MAX_SPEED)
        parts.append(f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=(PTS-STARTPTS)*{new / length:.5f}[v{i}]")
        labels.append(f"[v{i}]")
        if line:
            moved.append({**line, "at": now})
        now += new
    parts.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[v]")
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(clip), "-filter_complex", ";".join(parts),
        "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-r", "60", str(out),
    ], check=True)
    return moved


def cover(image: Image.Image, w: int, h: int) -> Image.Image:
    scale = max(w / image.width, h / image.height)
    image = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    left, top = (image.width - w) // 2, (image.height - h) // 2
    return image.crop((left, top, left + w, top + h))


def frame(clip: Path, lines: list[dict], wallpaper: Path, out: Path, tmp: Path) -> float:
    """Frames a clip on the wallpaper, padding the ends so transitions fall between lines.

    The recorder keeps frames only when the screen changes, so a clip that
    ends on a still screen stops right after its last line. Returns the head
    padding, by which the clip's lines move.
    """
    vw, vh, seconds = probe(clip)
    head = max(0.0, FADE + LEAD - lines[0]["at"]) if lines else 0.0
    tail = max(0.0, lines[-1]["at"] + lines[-1]["seconds"] + FADE + LEAD - seconds) if lines else 0.0
    total = f"{seconds + head + tail:.3f}"
    x, y = (W - vw) // 2, TOP
    background = cover(Image.open(wallpaper).convert("RGB"), W, H).filter(ImageFilter.GaussianBlur(18))
    shadow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shadow).rounded_rectangle((x, y + SHADOW_OFFSET, x + vw, y + vh + SHADOW_OFFSET), RADIUS, fill=SHADOW_ALPHA)
    background.paste(Image.new("RGB", (W, H), (20, 16, 12)), (0, 0), shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR)))
    mask = Image.new("L", (vw, vh), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, vw - 1, vh - 1), RADIUS, fill=255)
    background.save(tmp / "bg.png")
    mask.save(tmp / "mask.png")
    pad = f"tpad=start_mode=clone:start_duration={head:.3f}:stop_mode=clone:stop_duration={tail:.3f}"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(clip),
        # The stills loop forever, so they and the output are cut to the clip's length.
        "-loop", "1", "-framerate", "60", "-t", total, "-i", str(tmp / "bg.png"),
        "-loop", "1", "-framerate", "60", "-t", total, "-i", str(tmp / "mask.png"),
        "-filter_complex",
        f"[0:v]{pad},format=yuva420p[v];[2:v]format=gray[m];[v][m]alphamerge[r];"
        f"[1:v][r]overlay={x}:{y}:shortest=1,format=yuv420p[o]",
        "-map", "[o]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-r", "60", "-t", total, str(out),
    ], check=True)
    return head


def ass_time(t: float) -> str:
    cs = max(0, round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def captions(cues: list[tuple[float, float, str]], path: Path) -> None:
    """Writes the cues as ASS subtitles, centred in the band below the window."""
    band = H - (TOP + 900)
    style = ("Style: Caption,Inter Medium,31,&H00F4EEE4,&H00F4EEE4,&H00191C1F,&H40191C1F,0,0,0,0,100,100,0,0,"
             f"3,12,0,2,280,280,{max(10, band // 2 - 46)},1")
    events = "\n".join(
        f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Caption,,0,0,0,,{text}" for a, b, text in cues)
    path.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 0\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n" + style + "\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n" + events + "\n",
        "utf-8")


def stitch(clips: list[Path], subtitles: Path, out: Path) -> None:
    durations = [probe(c)[2] for c in clips]
    inputs = [arg for c in clips for arg in ("-i", str(c))]
    # Every clip on the same frame rate and timebase, which xfade requires.
    parts = [f"[{i}:v]fps=60,settb=AVTB,setsar=1[n{i}]" for i in range(len(clips))]
    video, offset = "[n0]", 0.0
    for i in range(1, len(clips)):
        offset += durations[i - 1] - FADE
        parts.append(f"{video}[n{i}]xfade=transition=fade:duration={FADE}:offset={offset:.3f}[v{i}]")
        video = f"[v{i}]"
    parts.append(f"{video}subtitles={subtitles},format=yuv420p[vout]")
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-stats", *inputs, "-filter_complex", ";".join(parts),
        "-map", "[vout]", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-movflags", "+faststart", str(out),
    ], check=True)


def main(corpus: Path, wallpaper: Path, out: Path) -> None:
    clips = [corpus / f"{name}.mp4" for name in TOUR]
    problems = check_lines(clips)
    if problems:
        sys.exit("lines overlap:\n  " + "\n  ".join(problems))
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        framed, cues, start = [], [], 0.0
        for clip in clips:
            tight = tmp / f"{clip.stem}.tight.mp4"
            lines = tighten(clip, tight)
            ready = tmp / f"{clip.stem}.framed.mp4"
            head = frame(tight, lines, wallpaper, ready, tmp)
            length = probe(ready)[2]
            for i, line in enumerate(lines):
                begin = start + head + line["at"]
                end = begin + line["seconds"] + LINGER
                if i + 1 < len(lines):
                    end = min(end, start + head + lines[i + 1]["at"] - 0.12)
                cues.append((begin, min(end, start + length - FADE), line["text"]))
            framed.append(ready)
            start += length - FADE
        captions(cues, tmp / "captions.ass")
        stitch(framed, tmp / "captions.ass", out)
    print(f"compose: {out} ({probe(out)[2]:.1f}s, {len(cues)} captions)")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
