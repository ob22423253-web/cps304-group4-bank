"""Draws all system-design diagrams (matplotlib; Graphviz is not installed) into docs/diagrams/.
Every canvas is 100 units wide = 9 inches, text is >= 10.5 pt, so the text is still >= 7 pt when the picture is 15 cm wide."""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch, Polygon, Rectangle

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "diagrams")
os.makedirs(OUT, exist_ok=True)
FAMILY = "Carlito" if any("Carlito" in f.name for f in font_manager.fontManager.ttflist) else "DejaVu Sans"
plt.rcParams["font.family"] = FAMILY
C = dict(client="#cfe2f7", coord="#fde0b8", primary="#cdebc6", standby="#cfeae7", db="#e6d4ec", sec="#f8cfce",
         neutral="#ececec", edge="#2b2b2b", red="#b3301f", green="#1e7b34", blue="#1f5fa8", note="#fff3b0")
FS = 11.5      # default text size inside boxes
FL = 11        # arrow labels


def canvas(h, title=None):
    fig, ax = plt.subplots(figsize=(9, h * 0.09))
    ax.set_xlim(0, 100); ax.set_ylim(0, h); ax.axis("off")
    fig.subplots_adjust(left=0.005, right=0.995, top=0.995, bottom=0.005)
    if title:
        ax.text(50, h - 2.2, title, ha="center", va="center", fontsize=14, fontweight="bold", color="#1f3a5f")
    return fig, ax


def box(ax, cx, cy, w, h, text, fc, fs=FS, bold=False, shape="round", ec=None, ls="-", color="black"):
    ec = ec or C["edge"]
    if shape == "diamond":
        ax.add_patch(Polygon([(cx, cy + h / 2), (cx + w / 2, cy), (cx, cy - h / 2), (cx - w / 2, cy)], fc=fc, ec=ec, lw=1.6, zorder=3))
    elif shape == "rect":
        ax.add_patch(Rectangle((cx - w / 2, cy - h / 2), w, h, fc=fc, ec=ec, lw=1.6, ls=ls, zorder=3))
    else:
        ax.add_patch(FancyBboxPatch((cx - w / 2, cy - h / 2), w, h, boxstyle="round,pad=0.2,rounding_size=1.2", fc=fc, ec=ec, lw=1.6, ls=ls, zorder=3))
    ax.text(cx, cy, text, ha="center", va="center", fontsize=fs, fontweight="bold" if bold else "normal", linespacing=1.15, zorder=4, color=color)


def arrow(ax, p, q, text="", color=None, ls="-", fs=FL, dx=0, dy=0, lw=1.8, head=True):
    color = color or C["edge"]
    ax.annotate("", xy=q, xytext=p, zorder=2, arrowprops=dict(arrowstyle="-|>" if head else "-", color=color, lw=lw, ls=ls, shrinkA=0, shrinkB=0, mutation_scale=14))
    if text:
        ax.text((p[0] + q[0]) / 2 + dx, (p[1] + q[1]) / 2 + dy, text, ha="center", va="center", fontsize=fs, color=color, zorder=5,
                bbox=dict(fc="white", ec="none", alpha=0.92, pad=1.0))


def poly(ax, pts, color=None, text="", tpos=None, fs=FL, ls="-"):
    color = color or C["edge"]
    for a, b in zip(pts[:-2], pts[1:-1]):
        ax.plot([a[0], b[0]], [a[1], b[1]], color=color, lw=1.8, ls=ls, zorder=2)
    arrow(ax, pts[-2], pts[-1], color=color, ls=ls)
    if text:
        ax.text(tpos[0], tpos[1], text, ha="center", va="center", fontsize=fs, color=color, zorder=5, bbox=dict(fc="white", ec="none", alpha=0.92, pad=1.0))


def line(ax, p, q, color="#888888", ls=(0, (4, 3)), lw=1.2):
    ax.plot([p[0], q[0]], [p[1], q[1]], color=color, ls=ls, lw=lw, zorder=1)


def save(fig, name):
    fig.savefig(os.path.join(OUT, name), dpi=200)
    plt.close(fig)


# ------------------------------------------------------------------ (a) architecture
def architecture():
    fig, ax = canvas(66, "System architecture")
    box(ax, 13, 40, 25, 11, "CLI client\ncustomer / teller\n/ admin", C["client"], bold=True)
    box(ax, 13, 18, 25, 9, "Demo and test\ndriver", C["client"])
    ax.add_patch(FancyBboxPatch((38, 5), 27, 54, boxstyle="round,pad=0.3,rounding_size=1.5", fc="#fff6ea", ec=C["edge"], lw=1.8, zorder=1))
    ax.text(51.5, 56, "COORDINATOR", ha="center", fontsize=12.5, fontweight="bold")
    box(ax, 51.5, 47, 23, 9, "Secure gateway\nlogin, roles, audit", C["sec"], fs=11)
    box(ax, 51.5, 35.5, 23, 9, "2PC engine\nprepare, vote, commit", C["coord"], bold=True, fs=11)
    box(ax, 51.5, 24.5, 23, 8, "Failover manager", C["coord"], fs=11)
    box(ax, 51.5, 13, 23, 9, "Decision log\ncoordinator.db", C["db"], fs=11, shape="rect")
    for y, n in ((50, "A"), (30, "B"), (10, "C")):
        ax.add_patch(FancyBboxPatch((72, y - 8.5), 27.5, 18, boxstyle="round,pad=0.2,rounding_size=1.2", fc="#f6fbf4", ec=C["edge"], lw=1.4, zorder=1))
        ax.text(85.7, y + 7.2, "Branch %s" % n, ha="center", fontsize=12, fontweight="bold")
        box(ax, 79, y - 1.2, 11.5, 11, "%s1\nprimary\nlocks, WAL" % n, C["primary"], fs=10.5, bold=True)
        box(ax, 93, y - 1.2, 11, 11, "%s2\nstandby\nreplica" % n, C["standby"], fs=10.5, bold=True)
        arrow(ax, (84.8, y - 1.2), (87.4, y - 1.2), "", lw=1.6)
        arrow(ax, (63, {"A": 47, "B": 35.5, "C": 24.5}[n]), (72.8, y - 1.2), "", color=C["blue"])
    arrow(ax, (26, 42), (38, 42), "", color=C["red"]); arrow(ax, (38, 38.5), (26, 38.5), "", color=C["red"])
    ax.text(32, 45.2, "AES-GCM", fontsize=10.5, color=C["red"], ha="center")
    arrow(ax, (26, 18), (38, 30), "", color=C["red"])
    arrow(ax, (72.8, 14), (63, 14), "", color=C["green"], ls="--")
    ax.text(1, 9.5, "blue: PREPARE / COMMIT / ABORT", fontsize=10.5, color=C["blue"])
    ax.text(1, 6, "green dashed: DECISION query", fontsize=10.5, color=C["green"])
    ax.text(1, 2.5, "A1 -> A2 arrows: WAL shipping", fontsize=10.5, color="#444")
    save(fig, "a_architecture.png")


# ------------------------------------------------------------------ (b) 2PC flowchart
def flow_2pc():
    fig, ax = canvas(91)
    ax.text(24, 88, "COORDINATOR", ha="center", fontsize=13, fontweight="bold", color=C["blue"])
    ax.text(72, 88, "PARTICIPANT (branch primary)", ha="center", fontsize=13, fontweight="bold", color=C["green"])
    line(ax, (50, 1), (50, 86))
    box(ax, 24, 81, 40, 6, "Client request", C["client"])
    box(ax, 24, 72, 40, 7, "Check role, new txid", C["coord"])
    box(ax, 24, 62, 40, 8, "PHASE 1\nsend PREPARE", C["coord"], bold=True)
    box(ax, 72, 62, 32, 8, "Lock accounts", C["primary"])
    box(ax, 72, 50, 34, 11, "Funds and\nlocks OK?", C["neutral"], shape="diamond")
    box(ax, 72, 38, 32, 8, "Force PREPARE to\nWAL (fsync)", C["primary"])
    box(ax, 94, 38, 11, 8, "Vote\nNO", C["sec"], fs=11)
    box(ax, 72, 28, 32, 7, "Send vote", C["primary"], bold=True)
    box(ax, 24, 28, 36, 11, "All votes\nYES?", C["neutral"], shape="diamond")
    box(ax, 33, 16.5, 26, 8, "Log COMMIT\ndecision", C["coord"], bold=True)
    box(ax, 9, 16.5, 17, 8, "Log\nABORT", C["sec"])
    box(ax, 24, 5.5, 40, 8, "PHASE 2\nsend decision", C["coord"], bold=True)
    box(ax, 72, 5.5, 32, 8, "Apply or roll back\nrelease locks", C["primary"])
    arrow(ax, (24, 78), (24, 75.5)); arrow(ax, (24, 68.5), (24, 66))
    arrow(ax, (44, 62), (55.5, 62), "PREPARE", color=C["blue"], dy=2.6)
    arrow(ax, (72, 58), (72, 55.5)); arrow(ax, (72, 44.5), (72, 42), "yes", color=C["green"], dx=3.5)
    poly(ax, [(89, 50), (94, 50), (94, 42)], color=C["red"], text="no", tpos=(91.5, 52.5))
    arrow(ax, (72, 34), (72, 31.5)); poly(ax, [(94, 34), (94, 28), (88.2, 28)])
    arrow(ax, (55.5, 28), (42, 28), "vote", color=C["blue"], dy=2.6)
    arrow(ax, (28, 23), (33, 20.5), "yes", color=C["green"], dx=3.5, dy=1); arrow(ax, (20, 25), (9, 20.5), "no", color=C["red"], dx=-3, dy=1.5)
    arrow(ax, (33, 12.5), (27, 9.5)); arrow(ax, (9, 12.5), (18, 9.5))
    arrow(ax, (44, 5.5), (55.5, 5.5), "decision", color=C["blue"], dy=2.6)
    save(fig, "b_2pc_flowchart.png")


# ------------------------------------------------------------------ (c) 2PC sequence with crash
def seq_2pc():
    names = [("Client", 9, C["client"]), ("Coordinator", 30, C["coord"]), ("A1", 51, C["primary"]), ("B1", 72, C["primary"]), ("B2 standby", 91, C["standby"])]
    x = {n: px for n, px, _ in names}
    fig, ax = canvas(92)
    for n, px, col in names:
        box(ax, px, 87.5, 16, 6, n, col, bold=True)
        line(ax, (px, 84.5), (px, 1))
    y = [79.0]

    def msg(a, b, text, color=None, ls="-"):
        arrow(ax, (x[a], y[0]), (x[b], y[0]), text, color=color, ls=ls, dy=2.2)
        y[0] -= 5.4

    def note(a, text, col=C["note"], w=26):
        box(ax, x[a], y[0], w, 4.4, text, col, fs=10.5, shape="rect")
        y[0] -= 5.4
    msg("Client", "Coordinator", "1 TRANSFER")
    msg("Coordinator", "A1", "2 PREPARE")
    msg("A1", "Coordinator", "3 vote YES", C["green"])
    msg("Coordinator", "B1", "4 PREPARE")
    msg("B1", "B2 standby", "5 replicate", C["blue"], "--")
    msg("B1", "Coordinator", "6 vote YES", C["green"])
    note("Coordinator", "7 log COMMIT", w=24)
    msg("Coordinator", "A1", "8 COMMIT")
    arrow(ax, (x["Coordinator"], y[0]), (x["B1"] - 2.5, y[0]), "9 COMMIT", dy=2.2)
    ax.text(x["B1"], y[0], "X", color=C["red"], fontsize=24, fontweight="bold", ha="center", va="center", zorder=6)
    ax.text(x["B1"] + 3, y[0] - 2.4, "crash", color=C["red"], fontsize=11, ha="left")
    y[0] -= 6.0
    note("Coordinator", "10 B1 down: fail over", C["sec"], 30)
    msg("Coordinator", "B2 standby", "11 PROMOTE", C["red"])
    msg("B2 standby", "Coordinator", "12 promoted, re-locked", C["green"])
    msg("Coordinator", "B2 standby", "13 COMMIT")
    msg("B2 standby", "Coordinator", "14 ack, credit applied", C["green"])
    msg("Coordinator", "Client", "15 COMMITTED", C["green"])
    save(fig, "c_2pc_sequence_crash.png")


# ------------------------------------------------------------------ (d) deadlock
def deadlock():
    fig, ax = canvas(62)
    box(ax, 20, 48, 30, 10, "T1\nA-1001 -> A-1002", C["client"], bold=True)
    box(ax, 80, 48, 30, 10, "T2\nA-1002 -> A-1001", C["coord"], bold=True)
    box(ax, 20, 12, 26, 8, "account A-1001", C["db"], shape="rect")
    box(ax, 80, 12, 26, 8, "account A-1002", C["db"], shape="rect")
    arrow(ax, (20, 43), (20, 16.5), "holds", color=C["green"], dx=5)
    arrow(ax, (80, 43), (80, 16.5), "holds", color=C["green"], dx=-5)
    arrow(ax, (35.5, 51.5), (64.5, 51.5), "T1 waits for A-1002", color=C["red"], dy=3)
    arrow(ax, (64.5, 44.5), (35.5, 44.5), "T2 waits for A-1001", color=C["red"], dy=-3)
    ax.text(50, 28, "CYCLE\nT1 -> T2 -> T1\n= DEADLOCK", ha="center", va="center", fontsize=14, color=C["red"], fontweight="bold")
    ax.text(50, 2, "T -> U : T waits for a lock owned by U", ha="center", fontsize=11, color="#444")
    save(fig, "d1_deadlock_wait_for_graph.png")

    fig, ax = canvas(92)
    box(ax, 28, 86, 40, 7, "Lock request for X", C["client"], bold=True)
    box(ax, 28, 74, 34, 11, "X free or\nmine?", C["neutral"], shape="diamond")
    box(ax, 76, 74, 34, 8, "Grant lock", C["primary"], bold=True)
    box(ax, 28, 61, 40, 8, "Add edge:\nme waits for owner(X)", C["sec"])
    box(ax, 28, 49, 36, 11, "Cycle back\nto me?", C["neutral"], shape="diamond")
    box(ax, 76, 49, 38, 10, "DEADLOCK\nabort youngest in cycle", C["sec"], bold=True, fs=11)
    box(ax, 28, 36, 34, 11, "Waited longer\nthan timeout?", C["neutral"], shape="diamond")
    box(ax, 76, 36, 34, 8, "LockTimeout\nvote NO", C["sec"])
    box(ax, 76, 23, 38, 9, "Coordinator retries the\naborted transfer", C["coord"])
    box(ax, 28, 22, 34, 8, "Wait 50 ms", C["neutral"])
    box(ax, 80, 86, 36, 9, "PREVENTION: lock the\naccounts in sorted order", C["primary"], fs=11, bold=True)
    arrow(ax, (28, 82.5), (28, 79.5)); arrow(ax, (45, 74), (59, 74), "yes", color=C["green"], dy=2.6)
    arrow(ax, (28, 68.5), (28, 65)); arrow(ax, (28, 57), (28, 54.5)); arrow(ax, (46, 49), (57, 49), "yes", color=C["red"], dy=2.6)
    arrow(ax, (28, 43.5), (28, 41.5), "no", dx=-3); arrow(ax, (45, 36), (59, 36), "yes", color=C["red"], dy=2.6)
    arrow(ax, (76, 44), (76, 40)); arrow(ax, (76, 32), (76, 27.5))
    arrow(ax, (28, 30.5), (28, 26), "no", dx=-3)
    poly(ax, [(11, 22), (3, 22), (3, 74), (11, 74)])
    ax.add_patch(Rectangle((52, 1.5), 47, 13, fc="#fffaf0", ec="#999999", lw=1.2, ls="--", zorder=1))
    ax.text(75.5, 12.3, "wait-for graph: a cycle = deadlock", ha="center", va="center", fontsize=10.5, color=C["red"], fontweight="bold")
    box(ax, 60, 5.8, 9, 5, "T1", C["client"], fs=11, bold=True); box(ax, 91, 5.8, 9, 5, "T2", C["coord"], fs=11, bold=True)
    arrow(ax, (64.8, 7.2), (86.2, 7.2), "", color=C["red"]); arrow(ax, (86.2, 4.4), (64.8, 4.4), "", color=C["red"])
    ax.text(75.5, 9.0, "waits for", ha="center", fontsize=10, color=C["red"], zorder=5)
    save(fig, "d2_deadlock_detection_flowchart.png")


# ------------------------------------------------------------------ (e) encryption flow
def crypto_flow():
    fig, ax = canvas(98)
    cx, sx = 17, 83
    box(ax, cx, 93, 24, 6, "Client", C["client"], bold=True); box(ax, sx, 93, 24, 6, "Coordinator", C["coord"], bold=True)
    line(ax, (cx, 90), (cx, 38)); line(ax, (sx, 90), (sx, 38))
    y = [84.0]

    def m(l2r, text, col=None):
        arrow(ax, (cx, y[0]) if l2r else (sx, y[0]), (sx, y[0]) if l2r else (cx, y[0]), text, color=col, dy=2.5)
        y[0] -= 7.0

    def n(side, text, col=C["note"], w=40):
        box(ax, {"L": cx + 9, "R": sx - 9, "M": 50}[side], y[0], w, 5.2, text, col, fs=11, shape="rect")
        y[0] -= 7.4
    m(True, "1 hello + X25519 public key")
    m(False, "2 public key + Ed25519 signature")
    n("L", "check pinned server key", C["sec"], 34)
    n("M", "both: HKDF -> K_c2s and K_s2c", C["note"], 44)
    m(True, "3 AES-GCM [seq 1]: LOGIN")
    m(False, "4 AES-GCM [seq 1]: role, accounts")
    m(True, "5 AES-GCM [seq n]: TRANSFER")
    n("R", "tag ok? seq = last+1? role?", C["sec"], 40)
    ax.text(50, 24.5, "Wire frame", ha="center", fontsize=12.5, fontweight="bold")
    xs = 3
    for w, t, col in ((14, "length\n4 B", C["neutral"]), (18, "seq. no.\n8 B (clear)", C["coord"]), (46, "ciphertext\nAES-256-GCM", C["sec"]), (18, "tag\n16 B", C["db"])):
        box(ax, xs + w / 2, 15.5, w - 0.8, 8.5, t, col, fs=11, shape="rect")
        xs += w
    ax.text(50, 6, "nonce = 0x00000000 + sequence number; one key per direction", ha="center", fontsize=10.5, color="#333")
    save(fig, "e_encryption_authentication_flow.png")


# ------------------------------------------------------------------ (f) failover / replication
def failover():
    fig, ax = canvas(82)
    ax.text(25, 78, "REPLICATION", ha="center", fontsize=13, fontweight="bold", color=C["green"])
    ax.text(75, 78, "FAILOVER", ha="center", fontsize=13, fontweight="bold", color=C["red"])
    line(ax, (50, 1), (50, 79))
    def column(cx, items, w):
        prev = None
        for yy, t, col, kind in items:
            h = 9.5 if kind == "d" else 8
            box(ax, cx, yy, w, h, t, col, shape="diamond" if kind == "d" else "round", bold=kind == "b")
            if prev is not None:
                arrow(ax, (cx, prev[0] - prev[1] / 2), (cx, yy + h / 2))
            prev = (yy, h)
    column(25, [(69, "Primary appends\nWAL record", C["primary"], "b"), (58, "Ship records after\n'peer_acked'", C["primary"], "n"), (47, "id = last + 1 ?", C["neutral"], "d"),
                (36, "Standby applies\nthe record", C["standby"], "b"), (25, "Ack; primary\nreplies", C["primary"], "n")], 36)
    box(ax, 44, 47, 10, 9, "gap:\ncatch\nup", C["sec"], fs=10.5)
    box(ax, 25, 10, 44, 11, "Standby down: primary keeps\nserving, standby catches up\nlater from its last id", C["sec"], fs=11)
    column(72, [(69, "Request to active\nnode", C["coord"], "n"), (58, "Reachable?", C["neutral"], "d"), (47, "Retry once\n(0.2 s)", C["coord"], "n"), (36, "Still down?", C["neutral"], "d"),
                (25, "PROMOTE standby", C["standby"], "b"), (14, "Re-lock in-doubt tx,\nre-send request", C["standby"], "n")], 32)
    box(ax, 93, 58, 11, 8, "done", C["primary"], fs=11)
    box(ax, 93, 36, 11, 9, "no\nfailover:\nabort", C["sec"], fs=10)
    save(fig, "f_failover_replication_flow.png")


# ------------------------------------------------------------------ (g) schema
def table(ax, x, y, w, name, cols, col, rowh=4.6):
    h = rowh * (len(cols) + 1)
    ax.add_patch(Rectangle((x, y - h), w, h, fc="white", ec=C["edge"], lw=1.4, zorder=3))
    ax.add_patch(Rectangle((x, y - rowh), w, rowh, fc=col, ec=C["edge"], lw=1.4, zorder=3))
    ax.text(x + w / 2, y - rowh / 2, name, ha="center", va="center", fontsize=11.5, fontweight="bold", zorder=4)
    for i, c in enumerate(cols):
        ax.text(x + 1.2, y - rowh * (i + 1.5), c, va="center", fontsize=10.5, zorder=4)


def schema():
    fig, ax = canvas(74)
    ax.add_patch(FancyBboxPatch((1, 38.3), 98, 34.7, boxstyle="round,pad=0.2", fc="#fbf5fd", ec=C["edge"], lw=1.3, ls="--", zorder=0))
    ax.text(50, 70.5, "coordinator.db", ha="center", fontsize=13, fontweight="bold")
    table(ax, 3, 67, 22, "users", ["PK username", "salt", "pw_hash", "iterations", "role"], C["sec"], 3.9)
    table(ax, 27, 67, 22, "accounts", ["PK acct_id", "owner", "branch"], C["db"], 3.9)
    table(ax, 51, 67, 22, "audit", ["PK id", "ts", "username, role", "action", "detail", "outcome"], C["sec"], 3.9)
    table(ax, 75, 67, 22, "decisions", ["PK txid", "decision", "pending (list)", "ts"], C["coord"], 3.9)
    ax.add_patch(FancyBboxPatch((1, 1), 98, 36, boxstyle="round,pad=0.2", fc="#f4fbf2", ec=C["edge"], lw=1.3, ls="--", zorder=0))
    ax.text(50, 34.3, "one database per node (A1 ... C2)", ha="center", fontsize=13, fontweight="bold")
    table(ax, 3, 31, 26, "accounts", ["PK acct_id", "owner", "balance >= 0", "(bututs, integer)"], C["primary"], 3.9)
    table(ax, 31, 31, 37, "wal (write-ahead log)", ["PK id", "txid", "kind PREPARE|COMMIT|ABORT", "payload (operations)", "ts"], C["standby"], 3.9)
    table(ax, 70, 31, 27, "history", ["PK id", "txid", "acct_id", "delta", "balance_after", "memo"], C["db"], 3.9)
    ax.text(3, 7.5, "COMMIT + balance updates +\nhistory = one SQLite tx", fontsize=10.5, color="#333", va="center")
    ax.text(3, 3.6, "txid links decisions, wal\nand history", fontsize=10.5, color="#333", va="center")
    save(fig, "g_database_schema.png")


if __name__ == "__main__":
    for f in (architecture, flow_2pc, seq_2pc, deadlock, crypto_flow, failover, schema):
        f()
        print("drawn", f.__name__)
