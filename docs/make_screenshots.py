"""Renders demo/output/*.txt (and the pytest summary) as dark-terminal PNGs with Pillow.
screenshots/NN_name.png = full output; docs/figs/NN_name.png = shortened excerpt used in the report."""
import glob
import os
import re
import textwrap
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
BG, FG = (30, 30, 30), (212, 212, 212)


def colour(line):
    s = line.strip()
    if "[PASS]" in s: return (106, 217, 117)
    if "[FAIL]" in s or "FAILED" in s: return (255, 107, 107)
    if s.startswith(">>>"): return (255, 214, 102)
    if s.startswith("log|") or "log|" in s[:12]: return (130, 170, 255)
    if s.startswith("SCENARIO") or s.startswith("DEMO SUMMARY") or "passed" in s and "==" in s: return (255, 255, 255)
    if "PASSED" in s: return (106, 217, 117)
    return FG


def wrap(lines, cols):
    out = []
    for l in lines:
        l = l.replace("\t", "    ")
        if len(l) <= cols:
            out.append(l)
            continue
        ind = len(l) - len(l.lstrip()) + 4
        w = textwrap.wrap(l, cols, subsequent_indent=" " * ind, break_long_words=True, drop_whitespace=False)
        out.extend(w)
    return out


def render(lines, path, title, cols=110, size=15):
    f, fb = ImageFont.truetype(FONT, size), ImageFont.truetype(BOLD, size)
    lh, cw = int(size * 1.35), f.getlength("M")
    lines = wrap(lines, cols)
    W, H = int(cw * (cols + 4)), lh * (len(lines) + 2) + 44
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 30], fill=(58, 58, 58))
    for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        d.ellipse([12 + i * 22, 9, 24 + i * 22, 21], fill=c)
    d.text((W // 2 - len(title) * cw / 2, 7), title, font=f, fill=(200, 200, 200))
    y = 42
    for l in lines:
        d.text((cw * 2, y), l, font=fb if l.strip().startswith((">>>", "SCENARIO")) else f, fill=colour(l))
        y += lh
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im.save(path)
    return len(lines)


def excerpt(lines, cap):
    lines = [l for l in lines if l.strip() and not set(l.strip()) <= {"="}]
    def score(l):
        s = l.strip()
        if "[PASS]" in s or "[FAIL]" in s or s.startswith((">>>", "SCENARIO", "DEMO")): return 0
        return 2 if "log|" in s else 1
    keep = list(range(len(lines)))
    for sc in (2, 1):
        for i in reversed(range(len(lines))):
            if len(keep) <= cap: break
            if i in keep and score(lines[i]) == sc: keep.remove(i)
    return [lines[i] for i in keep]


def compose_ui():
    """Crops and combines the real browser screenshots (screenshots/ui_*.png) into the report figures docs/figs/ui1.png, ui2.png."""
    sd = os.path.join(ROOT, "screenshots")
    if not os.path.exists(os.path.join(sd, "ui_05_admin_status_after_primary_killed.png")):
        return
    ld = lambda n: Image.open(os.path.join(sd, n)).convert("RGB")
    a = ld("ui_01_login_wrong_password.png").crop((480, 90, 1440, 640))
    b = ld("ui_04_role_denied_customer_deposit.png").crop((90, 120, 1300, 640))
    h = 520
    a, b = [x.resize((int(x.width * h / x.height), h)) for x in (a, b)]
    im = Image.new("RGB", (a.width + b.width + 24, h), (255, 255, 255))
    im.paste(a, (0, 0)); im.paste(b, (a.width + 24, 0))
    im.save(os.path.join(ROOT, "docs", "figs", "ui1.png"))
    c = ld("ui_02_customer_transfer_committed.png").crop((90, 110, 1830, 640))
    d = ld("ui_05_admin_status_after_primary_killed.png").crop((90, 110, 1830, 640))
    im = Image.new("RGB", (c.width, c.height * 2 + 16), (255, 255, 255))
    im.paste(c, (0, 0)); im.paste(d, (0, c.height + 16))
    im.save(os.path.join(ROOT, "docs", "figs", "ui2.png"))


def main():
    for p in sorted(glob.glob(os.path.join(ROOT, "demo", "output", "[0-9]*.txt"))):
        name = os.path.basename(p)[:-4]
        lines = open(p).read().rstrip("\n").split("\n")
        render(lines, os.path.join(ROOT, "screenshots", name + ".png"), "student@utg-bank: python demo/run_demo.py  (%s)" % name)
        render(excerpt(lines, {"08": 15, "09": 13, "07": 13, "10": 12}.get(name[:2], 26)), os.path.join(ROOT, "docs", "figs", name + ".png"), "demo/output/%s.txt (excerpt)" % name, cols=104, size=15)
    def ex(name, cap):
        return excerpt(open(os.path.join(ROOT, "demo", "output", name + ".txt")).read().rstrip("\n").split("\n"), cap)
    for out, parts, title in (("c_0102", (("01_normal_transfer", 11), ("02_insufficient_funds", 7)), "scenarios 1 and 2 (excerpts)"),
                              ("c_0506", (("05_deadlock_detected", 13), ("06_deadlock_prevented", 7)), "scenarios 5 and 6 (excerpts)"),
                              ("c_0304", (("03_participant_crash_recovery", 12), ("04_primary_failover", 12)), "scenarios 3 and 4 (excerpts)")):
        lines = []
        for n, cap in parts:
            lines += ex(n, cap) + [""]
        render(lines[:-1], os.path.join(ROOT, "docs", "figs", out + ".png"), "demo/output: " + title, cols=104, size=15)
    render(ex("11_cli_session", 16), os.path.join(ROOT, "docs", "figs", "11_cli_short.png"), "demo/output/11_cli_session.txt (excerpt)", cols=104, size=15)
    compose_ui()
    pt = os.path.join(ROOT, "demo", "output", "pytest_summary.txt")
    if os.path.exists(pt):
        lines = open(pt).read().rstrip("\n").split("\n")
        lines = [re.sub(r"^tests/", "", l) for l in lines]
        render(lines, os.path.join(ROOT, "screenshots", "12_pytest_summary.png"), "student@utg-bank: python -m pytest tests -v", cols=110, size=14)
        keep = [l for l in lines if "PASSED" in l or "passed" in l or "FAILED" in l]
        render([lines[0]] + keep[:36] + keep[-1:], os.path.join(ROOT, "docs", "figs", "12_pytest_summary.png"), "pytest -v (all tests)", cols=100, size=13)
    print("screenshots written")


if __name__ == "__main__":
    main()
