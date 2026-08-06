"""Built-in color looks (DaVinci-flavored one-word grades) + user LUT support.

Each look is a list of ffmpeg filter strings applied in order, before the
per-clip manual color controls (exposure/contrast/saturation/temperature).
"""

LOOKS = {
    "teal_orange": [
        "curves=blue='0/0.04 0.5/0.48 1/0.96':red='0/0 0.5/0.54 1/1'",
        "eq=saturation=1.12:contrast=1.06",
    ],
    "noir": [
        "hue=s=0",
        "eq=contrast=1.28:brightness=-0.02",
        "vignette=PI/4.4",
    ],
    "vintage": [
        "curves=preset=vintage",
        "eq=saturation=0.85",
        "noise=alls=6:allf=t",
    ],
    "cinema": [
        "eq=contrast=1.1:saturation=0.94:brightness=-0.015",
        "curves=all='0/0.02 0.5/0.5 1/0.97'",
    ],
    "vivid": [
        "eq=saturation=1.35:contrast=1.08",
        "unsharp=5:5:0.6",
    ],
    "cold": [
        "colortemperature=temperature=9500",
        "eq=saturation=0.95",
    ],
    "warm": [
        "colortemperature=temperature=4300",
        "eq=saturation=1.05",
    ],
    "dreamy": [
        "gblur=sigma=1.4",
        "eq=brightness=0.03:saturation=1.08:contrast=0.96",
    ],
    "punch_bw": [
        "hue=s=0",
        "eq=contrast=1.42",
        "unsharp=5:5:0.8",
    ],
    "night": [
        "eq=brightness=-0.06:saturation=0.8",
        "colorbalance=bs=0.12:ms=0.06",
    ],
}


def look_filters(name):
    if name is None:
        return []
    if name not in LOOKS:
        raise ValueError(f"unknown look {name!r}. Options: {', '.join(sorted(LOOKS))}")
    return list(LOOKS[name])


def color_filters(color, root=None):
    """Compile a clip's color dict (see project.DEFAULT_COLOR) to filters."""
    from pathlib import Path

    f = []
    f += look_filters(color.get("look"))
    lut = color.get("lut")
    if lut:
        lut_path = str(Path(root) / lut) if root else lut
        f.append(f"lut3d=file='{lut_path}'")
    eq = []
    if float(color.get("exposure") or 0):
        eq.append(f"brightness={float(color['exposure']):.4f}")
    if float(color.get("contrast") or 1) != 1:
        eq.append(f"contrast={float(color['contrast']):.4f}")
    if float(color.get("saturation") or 1) != 1:
        eq.append(f"saturation={float(color['saturation']):.4f}")
    if eq:
        f.append("eq=" + ":".join(eq))
    temp = float(color.get("temperature") or 0)
    if temp:  # -100 (cold) .. 100 (warm)
        kelvin = 6500 - temp * 25
        f.append(f"colortemperature=temperature={int(kelvin)}")
    if float(color.get("sharpen") or 0):
        amt = min(max(float(color["sharpen"]), 0), 1)
        f.append(f"unsharp=5:5:{0.4 + 1.1 * amt:.2f}")
    if float(color.get("vignette") or 0):
        amt = min(max(float(color["vignette"]), 0), 1)
        f.append(f"vignette=PI/{5.5 - 1.8 * amt:.2f}")
    if float(color.get("grain") or 0):
        amt = min(max(float(color["grain"]), 0), 1)
        f.append(f"noise=alls={int(4 + 16 * amt)}:allf=t")
    return f
