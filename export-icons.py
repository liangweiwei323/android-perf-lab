from __future__ import annotations

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parent
MASTER = ROOT / "assets" / "android-perf-lab-master.png"


def resized(source: Image.Image, size: int) -> Image.Image:
    return source.resize((size, size), Image.Resampling.LANCZOS)


def save_png(source: Image.Image, path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    resized(source, size).save(path, format="PNG", optimize=True)


def main() -> None:
    with Image.open(MASTER) as image:
        source = image.convert("RGBA")
        if source.width != source.height:
            raise ValueError(f"Icon master must be square, got {source.size}")
        if source.getchannel("A").getextrema()[0] != 0:
            raise ValueError("Icon master must have a transparent outer canvas")

        save_png(source, ROOT / "assets" / "android-perf-lab.png", 1024)
        save_png(source, ROOT / "static" / "favicon.png", 64)

        android_sizes = {
            "mipmap-mdpi": 48,
            "mipmap-hdpi": 72,
            "mipmap-xhdpi": 96,
            "mipmap-xxhdpi": 144,
            "mipmap-xxxhdpi": 192,
        }
        android_res = ROOT / "android-overlay" / "app" / "src" / "main" / "res"
        for density, size in android_sizes.items():
            save_png(source, android_res / density / "ic_launcher.png", size)

        ico_path = ROOT / "assets" / "android-perf-lab.ico"
        ico_path.parent.mkdir(parents=True, exist_ok=True)
        resized(source, 256).save(
            ico_path,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )


if __name__ == "__main__":
    main()
