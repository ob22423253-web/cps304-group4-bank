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
    """Report figures from the real browser screenshots (screenshots/ui_*.png): only empty page area at the bottom is trimmed."""
    sd = os.path.join(ROOT, "screenshots")
    if not os.path.exists(os.path.join(sd, "ui_05_admin_status_after_primary_killed.png")):
        return
    import numpy as np

    def trim(im, pad=24):
        a = np.array(im.convert("RGB")).astype(int)
        rows = np.where(np.abs(a - np.array([242, 245, 249])).sum(axis=2).max(axis=1) > 12)[0]
        return im.crop((0, 0, im.width, min(im.height, rows.max() + pad)))
    ld = lambda n: Image.open(os.path.join(sd, n)).convert("RGB")
    ld("ui_02_customer_transfer_committed.png").crop((0, 0, 2200, 1350)).save(os.path.join(ROOT, "docs", "figs", "ui1.png"))
    trim(ld("ui_04_role_denied_customer_deposit.png")).save(os.path.join(ROOT, "docs", "figs", "ui2.png"))
    trim(ld("ui_05_admin_status_after_primary_killed.png")).save(os.path.join(ROOT, "docs", "figs", "ui3.png"))


REPORT_COLS = 88   # 16 cm wide image at 88 columns -> about 8.2 pt text on the printed page (>= 7.5 pt)


def curated(name, subs):
    """Picks, in the given order, the first not yet used line of demo/output/<name>.txt containing each substring.
    A tuple (sub, repl) replaces the picked line by a shorter text of ours; a plain string keeps the real line."""
    lines = [l.rstrip() for l in open(os.path.join(ROOT, "demo", "output", name + ".txt")).read().split("\n")]
    used, out = set(), []
    for item in subs:
        sub, repl = item if isinstance(item, tuple) else (item, None)
        if sub == "":
            out.append("")
            continue
        for i, l in enumerate(lines):
            if i not in used and sub in l:
                used.add(i)
                t = repl if repl else l.strip()
                if repl is None and not t.startswith((">>>", "[PASS]", "[FAIL]", "SCENARIO")):
                    t = "  " + t
                if len(t) > REPORT_COLS - 1:
                    t = t[:REPORT_COLS - 4] + "..."
                out.append(t)
                break
        else:
            raise SystemExit("curated(): %r not found in %s" % (sub, name))
    return out


def report_terminals():
    """Short terminal figures for the report: only the lines that prove the point, big text, 16 cm wide."""
    R = lambda lines, f, title: render(lines, os.path.join(ROOT, "docs", "figs", f + ".png"), title, cols=REPORT_COLS, size=15)
    R(curated("01_normal_transfer", [(">>> Teller transfers", ">>> Scenario 1: transfer D 250.00 A-1001 -> B-2001"), "reply:", "branch A voted YES", "branch B voted YES",
                                     "DECISION COMMIT", "A1: [(1", "B1: [(1", "primaries:", "standbys :", "[PASS] transaction committed", "[PASS] debit and credit", "[PASS] total money", "[PASS] hot standbys"])
      + [""] + curated("02_insufficient_funds", [(">>> Teller tries", ">>> Scenario 2: D 99,999.00 from A-1001 (balance D 10,000.00)"), ("reply:", "  reply: ABORTED, insufficient funds in A-1001"), "voted NO", "DECISION ABORT",
                                                  "A1 WAL:", "[PASS] transaction aborted", "[PASS] every balance", "[PASS] no locks", "[PASS] Branch B never"]),
      "c_0102", "demo/output: scenarios 1 and 2 (excerpts)")
    R(curated("03_participant_crash_recovery", [(">>> 3a)", ">>> 3a) Branch B primary crashes after forcing PREPARE"), ("B1 WAL on disk:", "  B1 WAL on disk: [(1, 'T000001', 'PREPARE')] -> in doubt"), ("RECOVERY: tx T000001", "  log| [B1:primary] RECOVERY: tx T000001 is IN DOUBT, lock B-2001 re-taken"), "B1 WAL after recovery", ("[PASS] in-doubt", "[PASS] in-doubt transaction resolved as ABORT"), "[PASS] balances unchanged",
                                                (">>> 3b)", ">>> 3b) Branch B primary crashes when COMMIT arrives"), "total money visible", "[PASS] recovered B1", "[PASS] total money unchanged"])
      + [""] + curated("04_primary_failover", [(">>> Transfer D 300.00", ">>> Scenario 4: B1 killed (kill -9) between PREPARE and COMMIT"), "FAILOVER branch B: B1", ("FAILOVER branch B complete", "  log| [COORD] FAILOVER branch B complete: B2 is now primary"), "[B2:primary] COMMIT", "active node per branch",
                                                  "system total (active", ("B1 (rejoined)", "  B1 (rejoined) balances == B2: True"), "[PASS] transfer committed", "[PASS] debit and credit", "[PASS] restarted old"]),
      "c_0304", "demo/output: scenarios 3 and 4 (excerpts)")
    R(curated("05_deadlock_detected", [(">>> 5a)", ">>> 5a) detection OFF, timeout 1.0 s: real deadlock"), "LOCK TIMEOUT: T000001", ("[PASS] neither", "[PASS] neither transfer could proceed before the timeout: real deadlock"), (">>> 5b)", ">>> 5b) detection ON, victim retried"), ("DEADLOCK detected", "  log| [A1:primary] DEADLOCK detected: wait-for cycle T000004 <-> T000003"), "aborted as deadlock victim",
                                       "retry 1 after", "deadlocks detected by A1", "[PASS] wait-for-graph cycle", "[PASS] victim aborted", "[PASS] total money unchanged"])
      + [""] + curated("06_deadlock_prevented", [(">>> Run the same", ">>> Scenario 6: same transfers with ordered locking"), "locking ['A-1001', 'A-1002'] (sorted", "deadlocks detected: 0", "[PASS] all four", "[PASS] no deadlock", "[PASS] total money"]),
      "c_0506", "demo/output: scenarios 5 and 6 (excerpts)")
    R(curated("09_encryption_tamper_replay", ["plaintext of frame 2", ("on the wire, frame 2", "  on the wire, frame 2 : 00000000000000023a387789c89d4d99871b12e1a8872063..."), ("captured 10 frames", "  captured 10 frames, 814 bytes, 7 secret words searched -> found: nothing"), ("[PASS] no plaintext", "[PASS] no plaintext word appears in the captured traffic"), "[PASS] identical",
                                              (">>> Tampering", ">>> Tampering: proxy flips ONE bit of the TRANSFER frame"), ("SECURITY TAMPER", "  log| [COORD] SECURITY TAMPER from user=alice: GCM tag mismatch, connection dropped"), "[PASS] modified",
                                              (">>> Replay", ">>> Replay: proxy delivers a captured valid TRANSFER frame twice"), ("SECURITY REPLAY", "  log| [COORD] SECURITY REPLAY from user=alice: sequence 2, expected 3, dropped"), ("A-1001 balance change", "  A-1001 balance change: -D 50.00 (one transfer, not two)"), ("[PASS] replayed frame", "[PASS] replayed frame rejected: transfer executed exactly once"), "[PASS] total money"]),
      "09_encryption_tamper_replay", "demo/output/09_encryption_tamper_replay.txt (excerpt)")


def main():
    for p in sorted(glob.glob(os.path.join(ROOT, "demo", "output", "[0-9]*.txt"))):
        name = os.path.basename(p)[:-4]
        lines = open(p).read().rstrip("\n").split("\n")
        render(lines, os.path.join(ROOT, "screenshots", name + ".png"), "student@utg-bank: python demo/run_demo.py  (%s)" % name)
        render(excerpt(lines, {"08": 15, "09": 9, "07": 13, "10": 12}.get(name[:2], 26)), os.path.join(ROOT, "docs", "figs", name + ".png"), "demo/output/%s.txt (excerpt)" % name, cols=104, size=15)
    def ex(name, cap):
        return excerpt(open(os.path.join(ROOT, "demo", "output", name + ".txt")).read().rstrip("\n").split("\n"), cap)
    render(ex("11_cli_session", 16), os.path.join(ROOT, "docs", "figs", "11_cli_short.png"), "demo/output/11_cli_session.txt (excerpt)", cols=104, size=15)
    report_terminals()
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
