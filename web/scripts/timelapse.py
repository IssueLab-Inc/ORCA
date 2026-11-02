"""Timestamped screencast frames to an animated WebP time-lapse, with the speed stamped on every sped-up frame.

    timelapse.py <frames-dir> <out.webp> <width> <fps> <start:end:speed>...

Frames are named `f<n>_<seconds>.jpg` (seconds on the recording's clock). Each segment plays [start, end) at `speed`;
a frame that does not change between ticks is held rather than repeated. Run by `capture-proposals.cjs` with the
server's Python (Pillow). Settings from the environment:

- BADGE="x,y" places the speed label (fractions of the frame; y is its bottom edge), or "none" for no label (the
  page around it then says the clip is sped up); BADGE_PX sets its text size.
- CROP="x0,y0,x1,y1" keeps that part of each frame (fractions of it) before scaling to `width`.
- STILL=<path> also writes the last frame as a still WebP (the picture for people who ask for less motion).
- Q is the WebP quality (65).
"""
import bisect
import os
import sys

from PIL import Image, ImageDraw, ImageFont

# A bold sans for the label: Linux (the cloud session), Windows, macOS; Pillow's own font if none is there.
FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/segoeuib.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf"]


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONTS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def main(src: str, out: str, width: int, fps: float, segments: list[tuple[float, float, float]]) -> None:
    files = sorted(f for f in os.listdir(src) if f.endswith(".jpg"))
    stamps = [float(f.rsplit("_", 1)[1][:-4]) for f in files]
    font = load_font(int(os.environ.get("BADGE_PX") or max(13, round(22 * width / 1440))))
    badge = os.environ.get("BADGE", "0.02,0.97")
    bx, by = map(float, badge.split(",")) if badge != "none" else (0.0, 0.0)
    crop = tuple(map(float, os.environ["CROP"].split(","))) if os.environ.get("CROP") else None
    frames: list[Image.Image] = []
    durations: list[float] = []
    cached: tuple[int, Image.Image] | None = None
    last = None
    for start, end, speed in segments:
        t = start
        while t < end:
            i = max(0, bisect.bisect_right(stamps, t) - 1)
            if cached is None or cached[0] != i:
                im = Image.open(os.path.join(src, files[i])).convert("RGB")
                if crop:
                    im = im.crop((round(crop[0] * im.width), round(crop[1] * im.height),
                                  round(crop[2] * im.width), round(crop[3] * im.height)))
                cached = (i, im.resize((width, round(im.height * width / im.width)), Image.LANCZOS))
            if (i, speed) == last:
                durations[-1] += 1000 / fps
            else:
                frame = cached[1].copy()
                if speed != 1 and badge != "none":
                    draw = ImageDraw.Draw(frame)
                    text = f"{speed:g}× speed"
                    x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=font)
                    pad = max(6, round(font.size * 0.3)) if hasattr(font, "size") else 6
                    x, y = round(bx * frame.width), round(by * frame.height) - (y1 - y0) - 2 * pad
                    draw.rounded_rectangle((x, y, x + x1 - x0 + 2 * pad, y + y1 - y0 + 2 * pad), 8, fill=(15, 30, 50))
                    draw.text((x + pad - x0, y + pad - y0), text, font=font, fill=(255, 255, 255))
                frames.append(frame)
                durations.append(1000 / fps)
                last = (i, speed)
            t += speed / fps
    durations[-1] += 2500   # hold the end before it loops
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=[round(d) for d in durations], loop=0,
                   quality=int(os.environ.get("Q", "65")), method=4)
    print(f"{out}: {len(frames)} frames, {sum(durations) / 1000:.1f} s, {os.path.getsize(out) // 1024} KB")
    if os.environ.get("STILL"):
        still = os.environ["STILL"]
        cached[1].save(still, "WEBP", quality=80, method=6)   # the last frame without its speed label
        print(f"{still}: {os.path.getsize(still) // 1024} KB")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], int(a[2]), float(a[3]), [tuple(map(float, s.split(":"))) for s in a[4:]])
