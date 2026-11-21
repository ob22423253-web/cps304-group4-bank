"""Builds docs/CPS304_Group4_Report.docx (python-docx) and converts it to PDF with LibreOffice.
Two passes: the first pass finds the page of every heading, the second writes them into the table of contents.
Names, lecturer and faculty come from docs/team.json. Code excerpts are copied from the real source files."""
import collections
import json
import os
import re
import subprocess

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
DIAG, FIGS, OUTD = os.path.join(DOCS, "diagrams"), os.path.join(DOCS, "figs"), os.path.join(ROOT, "demo", "output")
FONT, MONO = "Calibri", "Courier New"
NAVY, NAVYHEX = RGBColor(0x1F, 0x3A, 0x5F), "1F3A5F"
BODY_PT = 10.5
TEAM = json.load(open(os.path.join(DOCS, "team.json")))


def rd(name):
    return open(os.path.join(OUTD, name)).read()


def grab(name, rx, default="?"):
    m = re.search(rx, rd(name))
    return m.group(1) if m else default


# ------------------------------------------------------------------ real numbers from the real runs
PT = rd("pytest_summary.txt")
PT_LINE = re.findall(r"=+ (.*(?:passed|failed).*) =+", PT)[-1]
PT_PASSED = int(re.search(r"(\d+) passed", PT_LINE).group(1))
PT_FAILED = int(re.search(r"(\d+) failed", PT_LINE).group(1)) if "failed" in PT_LINE else 0
PT_TIME = re.search(r"in ([\d.]+s(?: \(.*?\))?)", PT_LINE).group(1)
PER_FILE = collections.OrderedDict()
for f, r in re.findall(r"tests/(test_\w+\.py)::\S+ (PASSED|FAILED)", PT):
    PER_FILE.setdefault(f, [0, 0])[0 if r == "PASSED" else 1] += 1
D_CHECKS, D_PASS, D_FAIL = (int(x) for x in re.search(r"DEMO SUMMARY: (\d+) checks, (\d+) passed, (\d+) failed", rd("run_all.txt")).groups())
S7_T, S7_C, S7_A = re.search(r"finished in ([\d.]+) s -> committed: (\d+), aborted: (\d+)", rd("07_concurrent_transfers.txt")).groups()
S5B = grab("05_deadlock_detected.txt", r"resolved in ([\d.]+) s")

FIGORDER = ["arch", "s0102", "schema", "flow", "seq", "d2", "s0506", "ui2", "crypto", "s09", "s0304", "fail", "ui1", "ui3"]
FIGNO = {k: i + 1 for i, k in enumerate(FIGORDER)}
TABORDER = ["req", "coffman"]
TABNO = {k: i + 1 for i, k in enumerate(TABORDER)}
LISTORDER = ["decision", "prepare", "ordering", "cycle", "gcm", "password", "rbac", "failover"]
LISTNO = {k: i + 1 for i, k in enumerate(LISTORDER)}
F = lambda k: "Figure %d" % FIGNO[k]
T = lambda k: "Table %d" % TABNO[k]
L = lambda k: "Listing %d" % LISTNO[k]

FIGFILE = {
    "arch": "diagrams/a_architecture.png", "schema": "diagrams/g_database_schema.png", "flow": "diagrams/b_2pc_flowchart.png",
    "seq": "diagrams/c_2pc_sequence_crash.png", "d2": "diagrams/d2_deadlock_detection_flowchart.png",
    "crypto": "diagrams/e_encryption_authentication_flow.png", "fail": "diagrams/f_failover_replication_flow.png",
    "s0102": "figs/c_0102.png", "s0506": "figs/c_0506.png", "s0304": "figs/c_0304.png", "ui1": "figs/ui1.png", "ui2": "figs/ui2.png", "ui3": "figs/ui3.png", "s09": "figs/09_encryption_tamper_replay.png", "s10": "figs/10_stale_vs_strong_read.png"}
FIGWIDTH = {"arch": 16.2, "schema": 11.0, "flow": 9.5, "seq": 14.5, "d2": 8.5, "crypto": 14.5, "fail": 9.5, "s0102": 16.0, "s0506": 16.0,
            "s0304": 16.0, "ui1": 14.6, "ui2": 14.6, "ui3": 14.6, "s09": 16.0, "s10": 11.5}
CAPTION = {
    "arch": "System architecture: one coordinator and three branches, each with a primary and a hot standby",
    "s0102": "Scenario 1 (normal transfer, 2PC commit) and scenario 2 (insufficient funds, abort): real output, shortened",
    "schema": "Database schema of the coordinator database and of every branch database",
    "flow": "Two-phase commit flowchart", "seq": "2PC message sequence with a crash of the Branch B primary and failover",
    "s10": "Scenario 10: strong read from the primary and stale read from the lagging standby",
    "d2": "Deadlock detection (wait-for graph, victim, timeout) and prevention (ordered locking)",
    "s0506": "Scenarios 5 and 6: real deadlock detected and resolved, and the same transfers with ordered locking",
    "crypto": "Login handshake, session keys and AES-256-GCM frame format",
    "ui2": "Web UI (real browser): \'Role denied\' when a customer tries a teller deposit; the panel on the right shows the plain action and the real encrypted frames",
    "ui1": "Web UI (real browser), customer view: transfer committed, with the plain action and the real AES-256-GCM frames on the right",
    "s09": "Scenario 9: captured ciphertext, tampered and replayed messages rejected",
    "fail": "Replication (WAL shipping) and failover flow",
    "s0304": "Scenarios 3 and 4: participant crash and WAL recovery, primary killed and failover",
    "ui3": "Web UI (real browser), admin view after the Branch B primary was killed: B1 DOWN, B2 promoted, failover in the audit log"}

doc = None
HEADINGS = []


# ------------------------------------------------------------------ low-level helpers
def set_font(style, name, size=None, bold=None, color=None):
    style.font.name = name
    if size: style.font.size = Pt(size)
    if bold is not None: style.font.bold = bold
    if color is not None: style.font.color.rgb = color
    rpr = style.element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts"); rpr.append(rf)
    for a in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rf.set(qn(a), name)
    for a in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        if rf.get(qn(a)) is not None:
            del rf.attrib[qn(a)]


def shade(cell, color):
    tcPr = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear"); sh.set(qn("w:color"), "auto"); sh.set(qn("w:fill"), color)
    tcPr.append(sh)


def borders(table, color="BFBFBF", sz=4, inside=True):
    tblPr = table._tbl.tblPr
    b = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right") + (("insideH", "insideV") if inside else ()):
        e = OxmlElement("w:" + edge)
        e.set(qn("w:val"), "single"); e.set(qn("w:sz"), str(sz)); e.set(qn("w:space"), "0"); e.set(qn("w:color"), color)
        b.append(e)
    tblPr.append(b)


def cell_margins(table, top=40, bottom=40, left=80, right=80):
    tblPr = table._tbl.tblPr
    m = OxmlElement("w:tblCellMar")
    for k, v in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        e = OxmlElement("w:" + k); e.set(qn("w:w"), str(v)); e.set(qn("w:type"), "dxa"); m.append(e)
    tblPr.append(m)


def para_border(p, side="bottom", color=NAVYHEX, sz=8):
    pPr = p._p.get_or_add_pPr()
    pb = OxmlElement("w:pBdr")
    e = OxmlElement("w:" + side)
    e.set(qn("w:val"), "single"); e.set(qn("w:sz"), str(sz)); e.set(qn("w:space"), "1"); e.set(qn("w:color"), color)
    pb.append(e); pPr.append(pb)


def add_runs(p, text, size=None, color=None, mono=False):
    for i, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if not part:
            continue
        r = p.add_run(part)
        r.bold = i % 2 == 1
        if size: r.font.size = Pt(size)
        if color: r.font.color.rgb = color
        if mono: r.font.name = MONO


def fld(run, instr):
    for t, txt in (("begin", None), (None, instr), ("end", None)):
        if t:
            e = OxmlElement("w:fldChar"); e.set(qn("w:fldCharType"), t)
        else:
            e = OxmlElement("w:instrText"); e.set(qn("xml:space"), "preserve"); e.text = txt
        run._r.append(e)


def setup():
    s = doc.sections[0]
    s.page_width, s.page_height = Cm(21), Cm(29.7)
    s.left_margin = s.right_margin = Cm(2.0)
    s.top_margin, s.bottom_margin = Cm(2.1), Cm(1.8)
    s.header_distance, s.footer_distance = Cm(1.0), Cm(0.9)
    st = doc.styles["Normal"]
    set_font(st, FONT, BODY_PT)
    st.paragraph_format.space_after = Pt(4)
    st.paragraph_format.line_spacing = 1.15
    for n, sz, before, after in (("Heading 1", 14.5, 9, 3), ("Heading 2", 11.5, 5, 2)):
        h = doc.styles[n]
        set_font(h, FONT, sz, True, NAVY)
        h.paragraph_format.space_before, h.paragraph_format.space_after = Pt(before), Pt(after)
        h.paragraph_format.keep_with_next = True
    # header / footer on every page except the cover
    s.different_first_page_header_footer = True
    hp = s.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = hp.add_run("Fault-Tolerant Distributed Banking System  |  CPS 304 Operating System II  |  Group 4")
    r.font.size, r.font.color.rgb = Pt(8.5), RGBColor(0x59, 0x59, 0x59)
    para_border(hp, "bottom", "A6A6A6", 4)
    fp = s.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = fp.add_run("Page ")
    r.font.size = Pt(9)
    r2 = fp.add_run(); r2.font.size = Pt(9)
    fld(r2, "PAGE")


def P(text, align=WD_ALIGN_PARAGRAPH.JUSTIFY, size=None, after=None, keep=False):
    p = doc.add_paragraph()
    p.alignment = align
    add_runs(p, text, size)
    if after is not None: p.paragraph_format.space_after = Pt(after)
    if keep: p.paragraph_format.keep_with_next = True
    return p


def B(items):
    for t in items:
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_after = Pt(1.5)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        add_runs(p, t)


def H(text, level=1):
    HEADINGS.append((level, text))
    h = doc.add_heading(text, level)
    if level == 1:
        para_border(h, "bottom", "9DB2CC", 6)


def TABLE(key, caption, header, rows, widths, size=9):
    c = doc.add_paragraph()
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    c.paragraph_format.keep_with_next = True
    c.paragraph_format.space_after = Pt(2)
    c.paragraph_format.space_before = Pt(4)
    r = c.add_run("%s: %s" % (T(key), caption)); r.bold = True; r.font.size = Pt(9.5); r.font.color.rgb = NAVY
    t = doc.add_table(rows=1, cols=len(header))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    borders(t); cell_margins(t)
    for i, h in enumerate(header):
        cell = t.rows[0].cells[i]
        cell.text = ""
        add_runs(cell.paragraphs[0], "**%s**" % h, size, RGBColor(255, 255, 255))
        shade(cell, NAVYHEX)
    for n, row in enumerate(rows):
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            add_runs(cells[i].paragraphs[0], v, size)
            if n % 2: shade(cells[i], "F3F6FA")
    for row in t.rows:
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        for i, w in enumerate(widths):
            row.cells[i].width = Cm(w)
        for cell in row.cells:
            for p in cell.paragraphs:
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.line_spacing = 1.05
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    sp = doc.add_paragraph(); sp.paragraph_format.space_after = Pt(0)
    sp.paragraph_format.line_spacing = 0.6


def FIG(key):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.keep_with_next = True
    p.paragraph_format.space_after = Pt(1); p.paragraph_format.space_before = Pt(3); p.paragraph_format.line_spacing = 1.0
    p.add_run().add_picture(os.path.join(DOCS, FIGFILE[key]), width=Cm(FIGWIDTH[key]))
    c = doc.add_paragraph()
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = c.add_run("%s: %s" % (F(key), CAPTION[key])); r.italic = True; r.font.size = Pt(9); r.font.color.rgb = RGBColor(0x40, 0x40, 0x40)
    c.paragraph_format.space_after = Pt(6)


def CODE(key, relpath, start, n, what):
    """Copies n consecutive lines of the real source file, starting at the first line that contains `start`."""
    path = os.path.join(ROOT, relpath)
    lines = open(path).read().split("\n")
    i = next(k for k, l in enumerate(lines) if start in l)
    chunk = lines[i:i + n]
    ind = min(len(l) - len(l.lstrip()) for l in chunk if l.strip())
    chunk = [l[ind:] for l in chunk]
    assert 5 <= len(chunk) <= 12, (key, len(chunk))
    c = doc.add_paragraph()
    c.alignment = WD_ALIGN_PARAGRAPH.LEFT
    c.paragraph_format.space_before = Pt(4); c.paragraph_format.space_after = Pt(2); c.paragraph_format.keep_with_next = True
    r = c.add_run("%s: %s (lines %d-%d), %s" % (L(key), relpath, i + 1, i + len(chunk), what))
    r.italic = True; r.font.size = Pt(9); r.font.color.rgb = NAVY
    t = doc.add_table(rows=1, cols=1)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    borders(t, "999999", 4, False); cell_margins(t, 50, 50, 110, 80)
    cell = t.rows[0].cells[0]
    cell.width = Cm(16.2)
    cs = OxmlElement("w:cantSplit"); t.rows[0]._tr.get_or_add_trPr().append(cs)
    shade(cell, "ECECEC")
    cell.text = ""
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0); p.paragraph_format.line_spacing = 1.0
    p.paragraph_format.keep_together = True
    p.paragraph_format.keep_with_next = True
    for j, l in enumerate(chunk):
        r = p.add_run(l)
        r.font.name, r.font.size = MONO, Pt(7.2)
        rpr = r._r.get_or_add_rPr(); rf = rpr.find(qn("w:rFonts"))
        rf.set(qn("w:eastAsia"), MONO); rf.set(qn("w:cs"), MONO)
        if j < len(chunk) - 1: r.add_break()
    sp = doc.add_paragraph(); sp.paragraph_format.space_after = Pt(2); sp.paragraph_format.line_spacing = 0.5


# ------------------------------------------------------------------ cover and contents
def band(color, text_lines, height_cm, align=WD_ALIGN_PARAGRAPH.CENTER):
    t = doc.add_table(rows=1, cols=1)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = t.rows[0].cells[0]
    cell.width = Cm(16.2)
    shade(cell, color)
    cell.text = ""
    first = True
    for txt, size, bold, col in text_lines:
        p = cell.paragraphs[0] if first else cell.add_paragraph()
        first = False
        p.alignment = align
        p.paragraph_format.space_before, p.paragraph_format.space_after = Pt(3), Pt(3)
        r = p.add_run(txt); r.font.size, r.bold = Pt(size), bold
        r.font.color.rgb = RGBColor(*col)
    trPr = t.rows[0]._tr.get_or_add_trPr()
    h = OxmlElement("w:trHeight"); h.set(qn("w:val"), str(int(height_cm * 567))); h.set(qn("w:hRule"), "atLeast"); trPr.append(h)
    tcPr = cell._tc.get_or_add_tcPr()
    va = OxmlElement("w:vAlign"); va.set(qn("w:val"), "center"); tcPr.append(va)


def centered(text, size, bold=False, after=6, color=None, before=0):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before, p.paragraph_format.space_after = Pt(before), Pt(after)
    r = p.add_run(text); r.font.size, r.bold = Pt(size), bold
    if color: r.font.color.rgb = color
    return p


def cover():
    band(NAVYHEX, [("UNIVERSITY OF THE GAMBIA", 26, True, (255, 255, 255)), (TEAM["faculty"], 12, False, (214, 226, 242))], 4.2)
    band("C9A227", [("", 3, False, (0, 0, 0))], 0.35)
    centered("CPS 304 - OPERATING SYSTEM II", 17, True, 2, NAVY, before=30)
    centered("Practical Coursework (30 marks)  |  1st Semester 2026", 11.5, False, 40, RGBColor(0x40, 0x40, 0x40))
    centered("Fault-Tolerant Distributed", 28, True, 0, NAVY)
    centered("Banking System", 28, True, 4, NAVY)
    centered("for the UTG Microfinance Unit", 18, False, 6, RGBColor(0x2E, 0x54, 0x8A))
    centered("A secure, consistent and fault-tolerant distributed transaction system", 11.5, False, 34, RGBColor(0x59, 0x59, 0x59))
    centered("GROUP 4", 15, True, 6, NAVY)
    t = doc.add_table(rows=1, cols=3)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    borders(t, "BFBFBF", 4); cell_margins(t, 60, 60, 100, 100)
    for i, h in enumerate(("Full name", "Matric number", "Role")):
        c = t.rows[0].cells[i]; c.text = ""
        add_runs(c.paragraphs[0], "**%s**" % h, 11, RGBColor(255, 255, 255)); shade(c, NAVYHEX)
    for k, (n, m, r) in enumerate(TEAM["members"]):
        cells = t.add_row().cells
        for i, v in enumerate((n, m, r)):
            cells[i].text = ""
            add_runs(cells[i].paragraphs[0], ("**%s**" % v) if (i == 2 and "Leader" in v) else v, 11)
            if k % 2: shade(cells[i], "F3F6FA")
    for row in t.rows:
        for i, w in enumerate((7, 4, 4)):
            row.cells[i].width = Cm(w)
        for c in row.cells:
            c.paragraphs[0].paragraph_format.space_after = Pt(0)
            c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.LEFT
    centered("Lecturer: %s" % TEAM["lecturer"], 12.5, False, 4, before=20)
    centered("Source code: %s" % TEAM["repo"], 11, False, 4, RGBColor(0x2E, 0x54, 0x8A))
    centered("", 6, after=10)
    band(NAVYHEX, [("Submission date: 24 November 2026", 13, True, (255, 255, 255))], 1.3)


TOC_ENTRIES = [
    (1, "1 Introduction and objectives"), (1, "2 Requirements-to-implementation table"), (1, "3 System architecture"),
    (2, "3.1 Components and tools"),
    (1, "4 Server simulation and replication"), (1, "5 Transaction consistency"),
    (2, "5.1 Two-phase commit and the write-ahead log"), (2, "5.2 ACID properties"), (2, "5.3 Consistency models: strong and eventual"),
    (1, "6 Deadlock handling"), (2, "6.1 The Coffman conditions"), (2, "6.2 Detection and prevention"), (2, "6.3 Results"),
    (1, "7 Security"), (2, "7.1 Authentication and access control"), (2, "7.2 Encryption, replay protection and audit"),
    (1, "8 Fault tolerance and recovery"), (1, "9 Testing and results"), (1, "10 Limitations and future work"),
    (1, "11 Conclusion"), (1, "References"),
]


def toc(pages):
    p = doc.add_paragraph()
    r = p.add_run("Table of contents"); r.bold = True; r.font.size = Pt(18); r.font.color.rgb = NAVY
    para_border(p, "bottom", NAVYHEX, 10)
    p.paragraph_format.space_after = Pt(10)
    for lvl, text in TOC_ENTRIES:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.8 * (lvl - 1))
        p.paragraph_format.space_after = Pt(3 if lvl == 1 else 1)
        p.paragraph_format.space_before = Pt(5 if lvl == 1 else 0)
        p.paragraph_format.line_spacing = 1.1
        p.paragraph_format.tab_stops.add_tab_stop(Cm(16.2), alignment=2, leader=1)
        r = p.add_run("%s\t%s" % (text, pages.get(text, "")))
        r.bold = lvl == 1
        r.font.size = Pt(11.5 if lvl == 1 else 10.5)
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    add_runs(p, "**Figures, tables and listings:** %d figures, %d tables and %d code listings, numbered in the order of appearance. "
                "The full source code is in the separate document CPS304_Group4_SourceCode_Appendix.pdf and in the submission zip." % (len(FIGORDER), len(TABORDER), len(LISTORDER)), 10)


# ------------------------------------------------------------------ body
def body():
    H("1 Introduction and objectives")
    P("The Microfinance Unit of the University of The Gambia (UTG) keeps customer savings in several branch offices. If one branch computer stops in the middle of a transfer, or two clerks move money at the same moment, "
      "the books must still balance. This project builds a working model of such a system: a **fault-tolerant distributed banking system** with three bank servers, each with a hot-standby copy, coordinated by a transaction coordinator. "
      "Everything runs on one computer, but every server is a separate operating-system process with its own TCP port and its own SQLite database.")
    P("The coursework objective is to develop a secure distributed transaction system. We split it into four tasks and show for each one the implementation and the proof from a real run:")
    P("**Task 1, simulate multiple bank servers** (Sections 3, 4); **Task 2, transaction consistency** with two-phase commit (2PC), a write-ahead log and strong versus eventual consistency (Section 5); "
      "**Task 3, handle deadlock scenarios** with a real deadlock, detection, victim retry and prevention by ordered locking (Section 6); **Task 4, apply encryption for transactions** with AES-256-GCM, key exchange at login, replay protection, roles and an audit log (Section 7).")
    P("All numbers and screenshots come from the automated demo (demo/run_demo.py, %d checks) and the pytest suite (%d tests). "
      "Short code excerpts are shown where they prove a requirement; the **full source code is in the separate appendix document (CPS304_Group4_SourceCode_Appendix.pdf), in the submission zip and on GitHub: %s**." % (D_CHECKS, PT_PASSED, TEAM["repo"]))

    H("2 Requirements-to-implementation table")
    P("%s lists every coursework item, the file that implements it and the evidence that proves it." % T("req"), after=2, keep=True)
    TABLE("req", "Coursework requirements, implementation and evidence",
          ["Requirement", "Implemented in", "Evidence"],
          [["1. Simulate multiple bank servers", "src/branch.py, cluster.py, seed.py", "Figure %d; scenarios 1, 7; test_cluster.py" % FIGNO["arch"]],
           ["2. Transaction consistency", "src/coordinator.py, wal.py, branch.py", "Figures %d, %d; scenarios 1, 2, 7, 10; test_consistency.py" % (FIGNO["flow"], FIGNO["seq"])],
           ["3. Handle deadlock scenarios", "src/locks.py, branch.py", "%s to %s; scenarios 5, 6; test_locks.py, test_deadlock.py" % (F("d2"), F("s0506"))],
           ["4. Apply encryption for transactions", "src/crypto.py, coordinator.py, netproxy.py", "%s to %s; scenarios 8, 9; test_security.py" % (F("crypto"), F("s09"))],
           ["Fault tolerance", "src/branch.py, coordinator.py", "Figures %d, %d; scenarios 3, 4; test_fault_tolerance.py" % (FIGNO["s0304"], FIGNO["fail"])],
           ["CLI client and web UI", "src/client.py, webui.py, web/index.html", "Figures %d, %d, %d; scenario 11; test_cli.py, test_webui.py" % (FIGNO["ui2"], FIGNO["ui1"], FIGNO["ui3"])]],
          [4.8, 5.0, 6.4])

    H("3 System architecture")
    P("%s shows the architecture. A client talks only to the coordinator, which authenticates the user, checks the role and runs the transaction on the branches. "
      "Each branch has a primary node (A1, B1, C1) and a hot standby (A2, B2, C2) that receives every change of its primary." % F("arch"))
    H("3.1 Components and tools", 2)
    P("The **coordinator** (src/coordinator.py) is the secure gateway (handshake, login, roles, audit), the 2PC engine, the owner of the durable decision log and the failover manager. "
      "A **branch primary** owns the accounts of its branch, runs the lock manager and the write-ahead log and acts as 2PC participant; a **standby** replays its log, serves optional eventually consistent reads and can be promoted. "
      "The **client** (src/client.py) is a menu-driven program. Accounts are partitioned by branch (B-2001 belongs to Branch B): 12 accounts of D 10,000.00, so the system holds D 120,000.00. Money is an integer number of bututs (1/100 dalasi), so rounding cannot create or destroy money.")
    P("**Web UI.** src/webui.py is a small local gateway (http.server, one offline HTML page) on 127.0.0.1:8080. It keeps one real encrypted client session per browser login, so the browser never talks to a bank server; the page shows the plain action next to the real hex of the AES-GCM frames (Figures %d, %d, %d)." % (FIGNO["ui2"], FIGNO["ui1"], FIGNO["ui3"]))
    P("**Tools.** Python 3.12 (socket, threading, sqlite3), the cryptography package, SQLite, pytest, Pillow, matplotlib (Graphviz was not installed), Playwright with Chrome for the UI screenshots, python-docx and LibreOffice. Runs on Linux, WSL and Windows.")

    FIG("arch")
    H("4 Server simulation and replication")
    P("The launcher (src/cluster.py) creates the databases, picks free ports and starts seven separate processes. The tests check that there are seven process ids, that every node has its own database file and that the account partitions do not overlap. "
      "Scenario 1 (demo/output/01_normal_transfer.txt, %s) shows one transfer: coordinator votes and decision, the write-ahead logs (PREPARE, COMMIT) and equal balances on primaries and standbys." % F("s0102"))
    P("**Replication.** Every change is first written to the write-ahead log (WAL, Section 5.1). The primary then sends all records that the standby has not acknowledged. The standby accepts a record only if its id is the last id plus one; otherwise the primary re-sends the missing records. "
      "Replication is synchronous by default, so a standby always holds every prepared and committed transaction; if the standby is down the primary keeps serving and the standby catches up later (scenario 4). "
      "%s shows the schema; the accounts table has a CHECK (balance >= 0) as a last defence." % F("schema"))

    FIG("s0102")
    H("5 Transaction consistency")
    H("5.1 Two-phase commit and the write-ahead log", 2)
    P("Every deposit, withdrawal and transfer is a distributed transaction run by the coordinator with two-phase commit (%s). A cross-branch transfer has two participants; a deposit has one." % F("flow"))
    B(["**Phase 1:** the coordinator sends PREPARE to each participant in turn. The participant locks the accounts, checks that no balance becomes negative, **forces a PREPARE record to its WAL** (SQLite synchronous=FULL), replicates it and votes YES; otherwise it unlocks and votes NO (%s)." % L("prepare"),
       "**Decision:** if all votes are YES the coordinator writes COMMIT to its durable decision log, otherwise ABORT. This is the commit point and it happens before any phase-2 message (%s)." % L("decision"),
       "**Phase 2:** COMMIT applies the balances, history rows and COMMIT record in one SQLite transaction and releases the locks. All phase-2 messages are idempotent, so they can be repeated.",
       "**Recovery:** an undeliverable decision stays pending and is re-sent every 0.5 s. A restarted participant finds PREPARE records without outcome (in doubt), re-takes their locks and asks the coordinator (unknown transaction: presumed abort)."])
    CODE("decision", "src/coordinator.py", 'decision = "ABORT" if reason else "COMMIT"', 6, "Coordinator.attempt: the decision is logged before phase 2")
    P("%s is the commit point: the decision is forced to the log first and only then delivered to the participants." % L("decision"), after=2)
    CODE("prepare", "src/branch.py", "for a, d in net.items():", 8, "Branch.op_prepare: validate, then write the PREPARE record and replicate")
    P("%s shows the participant side: it checks every balance, forces the PREPARE record to its WAL and replicates it before it can vote YES. %s is the message sequence of a transfer in which the Branch B primary is killed after voting YES (scenario 4, Section 8)." % (L("prepare"), F("seq")))
    FIG("schema")
    FIG("flow")
    H("5.2 ACID properties", 2)
    P("**Atomicity:** all branches apply the transfer or none does (2PC; COMMIT record and balances in one SQLite transaction). **Consistency:** CHECK(balance >= 0), validation at PREPARE and the total-money invariant. "
      "**Isolation:** exclusive account locks from PREPARE to COMMIT/ABORT (strict two-phase locking). **Durability:** PREPARE, COMMIT and the decision are forced to disk before any reply, and a standby holds a copy.")
    P("In scenario 2 (demo/output/02_insufficient_funds.txt) a transfer of D 99,999.00 from an account with D 10,000.00 is rejected: Branch A votes NO, the coordinator logs ABORT, no balance changes, no lock is left, and Branch B is never contacted (%s)." % F("s0102"))
    FIG("seq")
    H("5.3 Consistency models: strong and eventual", 2)
    P("**Strong consistency** means that once an operation is confirmed, every later read sees it. **Eventual consistency** only promises that replicas converge if no new updates arrive; meanwhile a read may return an old value. "
      "In our system all writes and the default balance read go through the primary and 2PC (strong). A client may ask for an eventual read, which the standby answers.")
    P("Scenario 10 (demo/output/10_stale_vs_strong_read.txt) is a real example. Replication of Branch A is delayed by 2.0 s and a teller deposits D 500.00 to A-1003 (opening balance D 10,000.00). The strong read from A1 returns D 10,500.00 at log position 2; the eventual read from A2 returns the old D 10,000.00 at position 0, so it is stale. "
      "After the delay the standby also shows D 10,500.00. The standby read is cheap but can be out of date, so strong reads are needed for any balance that decides a payment.")

    H("6 Deadlock handling")
    H("6.1 The Coffman conditions", 2)
    P("A deadlock needs four conditions together (Coffman et al., 1971). In our bank the resources are account locks. T1 moves money from A-1001 to A-1002 and locks A-1001 first; T2 moves money from A-1002 to A-1001 and locks A-1002 first. "
      "T1 then waits for T2 and T2 waits for T1, a cycle in the wait-for graph (inset of %s). %s shows which method breaks which condition." % (F("d2"), T("coffman")))
    TABLE("coffman", "The four Coffman conditions and how our methods break them", ["Condition", "In our bank", "Broken by"],
          [["Mutual exclusion", "An account lock is exclusive", "Not broken: needed for correctness"],
           ["Hold and wait", "T1 keeps A-1001 while it waits for A-1002; 2PC keeps locks until commit", "Not broken: needed for isolation"],
           ["No preemption", "A lock is released only by its owner", "**Detection + victim abort** and **lock timeout** force a transaction to give up its locks"],
           ["Circular wait", "T1 waits for T2 and T2 waits for T1", "**Ordered locking**: sorted lock order makes a cycle impossible"]],
          [3.2, 6.4, 6.6])
    H("6.2 Detection and prevention", 2)
    P("**Detection.** The lock manager records which account each waiting transaction waits for; following waiter, owner, owner's own wait gives the wait-for graph (%s). When a request closes a cycle (%s) the **youngest** transaction of the cycle becomes the victim, votes NO, releases its locks and the coordinator retries it after a random back-off. "
      "A **lock timeout** (1.0 to 1.5 s) is the safety net and the only tool for cycles that span two branches." % (F("d2"), L("cycle")))
    CODE("cycle", "src/locks.py", "path, cur = [start], start", 12, "LockManager._cycle_from: follows the wait-for chain and returns the cycle")
    P("%s walks the chain waiter, owner, owner's wait; if it returns to the starting transaction, that is a deadlock." % L("cycle"), after=2)
    P("**Prevention.** With ordered locking on, the coordinator contacts branches in sorted order and each branch sorts the accounts of a transaction (%s), so every transaction asks for locks in the same global order and a circular wait is impossible." % L("ordering"))
    CODE("ordering", "src/branch.py", "accts = []", 10, "Branch.op_prepare: sorted lock acquisition when ordering is on")
    H("6.3 Results", 2)
    P("In the demo every lock step is slowed by 0.4 s so that the interleaving is repeatable (%s). **5a:** with detection off and a 1.0 s timeout neither transfer can proceed until the timeout fires, which proves a genuine deadlock. "
      "**5b:** with detection on, Branch A finds the cycle, one victim is aborted and retried, and both transfers commit (the second needed 2 attempts), resolved in %s s without the timeout. "
      "**5c:** with accounts on two branches the cycle is invisible to a single branch and is broken by the timeout; both transfers then commit. **6:** with ordered locking the same opposite transfers, inside Branch A and across A and B, commit at the first attempt with 0 deadlocks and 0 timeouts. The total money stayed D 120,000.00 in every case." % (F("s0506"), S5B))
    FIG("d2")
    FIG("s0506")

    H("7 Security")
    H("7.1 Authentication and access control", 2)
    P("Passwords are never stored. For each user the coordinator keeps a random 16-byte salt and the PBKDF2-HMAC-SHA256 hash (%s); the comparison is constant-time, a wrong password and an unknown user give the same message, and three failures close the connection. "
      "The demo uses 30,000 iterations to keep the tests fast; the value is one constant and should be raised in production." % L("password"))
    CODE("password", "src/crypto.py", "def hash_password", 9, "hash_password and verify_password (PBKDF2-HMAC-SHA256 with per-user salt)")
    P("Three roles exist. A **customer** may read the balance and history of, and transfer from, his or her own accounts only; a **teller** may read all accounts, transfer between any accounts and deposit or withdraw cash; the **admin** may open the admin view and change the configuration but may not move money. Every request passes the check in %s, and every decision, allowed or denied, is audited." % L("rbac"), after=2)
    CODE("rbac", "src/coordinator.py", "if op not in PERMS[role]:", 10, "Coordinator.dispatch: role check and account ownership check")
    P("Scenario 8 (demo/output/08_auth_and_access_control.txt) shows the stored salted hashes, a wrong password, an unknown user, a request before login and six forbidden actions that were all denied (for example a customer reading another customer's balance, a teller opening the admin view, the admin moving money); the permitted actions succeeded in the same run. In the web UI (%s) the same denial appears as a \'Role denied\' message." % F("ui2"))
    FIG("ui2")
    H("7.2 Encryption, replay protection and audit", 2)
    P("Each connection starts with the handshake of %s: both sides exchange fresh X25519 public keys, derive two 256-bit keys with HKDF-SHA256 (one per direction) and from then on every message is one **AES-256-GCM** frame. "
      "The server signs the transcript with an Ed25519 key that the client has pinned, so a fake server is rejected; cluster nodes authenticate each other with an HMAC proof. The password travels only inside the encrypted channel." % F("crypto"))
    CODE("gcm", "src/crypto.py", '(seq,) = struct.unpack(">Q", frame[:8])', 9, "SecureConn.recv: GCM decryption (tamper check) and sequence-number replay check")
    P("In %s the nonce is the frame's sequence number. A changed bit fails the GCM tag check (tamper); an old frame has a valid tag but an old sequence number and is refused (replay). In scenario 9 (%s) a man-in-the-middle proxy records all traffic: none of the words alice, the password, TRANSFER, A-1001, BALANCE or amount appears in the captured frames, "
      "and the same request sent twice gives different ciphertext. One flipped bit in a transfer makes the server drop the connection and no money moves; a valid transfer frame delivered twice is executed exactly once." % (L("gcm"), F("s09")))
    FIG("crypto")
    FIG("s09")
    P("**Audit log.** The coordinator writes one audit row for every login, every operation (also denied ones) and every security event (tamper, replay, failover); scenarios 8 and 9 print them.")

    H("8 Fault tolerance and recovery")
    P("We assume crash-stop failures, lost connections, slow nodes and an attacker who can change messages. Failures are injected by killing a process (SIGKILL) and by failpoints that call os._exit at an exact moment of 2PC (like a power cut: nothing is cleaned up). Scenarios 3 and 4 below cover a participant crash, a crash of the primary and the failover; a hung node is treated as a NO vote after the 4 s RPC timeout (test_fault_tolerance.py)." )
    P("%s is the failover logic. After a failed request the coordinator waits 0.2 s, retries once and then promotes the standby (%s); the standby switches its role, re-takes the locks of its in-doubt transactions from the replicated WAL and the request is repeated on the new primary." % (F("fail"), L("failover")))
    CODE("failover", "src/coordinator.py", "def do_failover", 11, "Coordinator.do_failover: promote the standby and update the active node")
    P("**3a** (%s): the crashed Branch B primary had written PREPARE only; after the restart its log shows PREPARE then ABORT, its locks are free and both balances are unchanged. **3b:** the debit is applied but the credit is missing, so the visible total is D 119,900.00 for a moment; the money is not lost, it is the committed transfer waiting for the recovering node, and the total is D 120,000.00 again after the restart. "
      "**4:** the coordinator waits 1.5 s after logging COMMIT and the Branch B primary is killed in that window; the standby already holds the PREPARE record, so the transfer completes as COMMITTED, debit and credit are applied exactly once and the total is unchanged. The old primary later rejoins as a standby and becomes identical to B2." % F("s0304"))
    FIG("s0304")
    FIG("fail")

    H("9 Testing and results")
    P("The demo runs eleven scenarios on fresh clusters and checks its own results: **%d checks, %d passed, %d failed**. The pytest suite has **%d tests, %d passed, %d failed** (%s)." % (D_CHECKS, D_PASS, D_FAIL, PT_PASSED + PT_FAILED, PT_PASSED, PT_FAILED, PT_TIME), after=2)
    P("**Money invariant.** Scenario 7 sends %d random transfers (60 normal ones of D 1.00 to D 200.00 between random accounts of all branches and 5 deliberately oversized ones) from 8 parallel sessions (demo/output/07_concurrent_transfers.txt). "
      "%s committed and %s aborted for insufficient funds (exactly the 5 oversized ones) in %s s; the total money was D 120,000.00 before and after, on primaries and standbys, no balance became negative and no lock remained. "
      "Scenario 11 drives the menu-driven client with scripted keystrokes (wrong password, balance, transfer of D 75.50, eventual read, history, denied actions); all screenshots are in the folder screenshots/. The web UI was tested in a real browser: %s shows a committed transfer next to the real encrypted frames, and %s the admin view after the Branch B primary was killed (B1 DOWN, B2 promoted, failover in the audit log)." % (int(S7_C) + int(S7_A), S7_C, S7_A, S7_T, F("ui1"), F("ui3")))
    FIG("ui1")
    FIG("ui3")

    H("10 Limitations and future work")
    B(["**Coordinator is a single point of failure:** its log is durable, but while it is down in-doubt participants stay blocked (2PC blocking). A replicated coordinator (Paxos/Raft) or three-phase commit would remove this.",
       "**No fencing:** we never fail over on a timeout; a real system needs fencing tokens or a consensus-based leader. Asynchronous replication (lag mode) could lose data; cross-branch deadlocks are broken by timeouts, not by a global wait-for graph.",
       "**Single machine and security scope:** network partitions were only simulated; 30,000 PBKDF2 iterations in the demo; server key pinned from a file, not a certificate; no rate limiting; audit log not hash-chained; the fault-injection commands would be removed in production."])

    H("11 Conclusion")
    P("We built a distributed banking system with three bank servers and their hot standbys, coordinated by a transaction coordinator, and proved each coursework task by running it. "
      "Two-phase commit with a write-ahead log kept all %d concurrent transfers consistent and the total money constant. Deadlocks were produced for real, detected with a wait-for graph, resolved by a victim abort and prevented by ordered locking. "
      "Every message is protected with AES-256-GCM and replay protection, and users by salted PBKDF2 hashes, roles and an audit log. "
      "A killed primary was replaced by its standby in the middle of a transaction and a crashed participant recovered from its log, without losing or creating money. "
      "The complete source code is in the separate appendix (CPS304_Group4_SourceCode_Appendix.pdf) and in the submission zip." % (int(S7_C) + int(S7_A)))

    H("References", 1)
    refs = ["Tanenbaum, A. S. and Van Steen, M. (2017) Distributed Systems: Principles and Paradigms, 3rd edn. Pearson.",
            "Coulouris, G., Dollimore, J., Kindberg, T. and Blair, G. (2012) Distributed Systems: Concepts and Design, 5th edn. Addison-Wesley.",
            "Silberschatz, A., Galvin, P. B. and Gagne, G. (2018) Operating System Concepts, 10th edn. Wiley.",
            "Coffman, E. G., Elphick, M. J. and Shoshani, A. (1971) 'System deadlocks', ACM Computing Surveys, 3(2), pp. 67-78.",
            "Dworkin, M. (2007) Recommendation for Block Cipher Modes of Operation: Galois/Counter Mode (GCM) and GMAC. NIST Special Publication 800-38D.",
            "Moriarty, K., Kaliski, B. and Rusch, A. (2017) PKCS #5: Password-Based Cryptography Specification Version 2.1. RFC 8018. IETF.",
            "Langley, A., Hamburg, M. and Turner, S. (2016) Elliptic Curves for Security (X25519). RFC 7748; Josefsson, S. and Liusvaara, I. (2017) EdDSA (Ed25519). RFC 8032; Krawczyk, H. and Eronen, P. (2010) HKDF. RFC 5869. IETF."]
    for r in refs:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.8); p.paragraph_format.first_line_indent = Cm(-0.8)
        p.paragraph_format.space_after = Pt(2); p.paragraph_format.line_spacing = 1.05
        add_runs(p, r, 9)


def page_break():
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def build(pages, out):
    global doc
    doc = Document()
    HEADINGS.clear()
    setup()
    cover(); page_break()
    toc(pages); page_break()
    body()
    doc.save(out)


def to_pdf(docx):
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", DOCS, docx], check=True, capture_output=True, timeout=300)
    pdf = docx[:-5] + ".pdf"
    n = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", pdf], capture_output=True, text=True).stdout).group(1))
    return pdf, n


def find_pages(pdf, n):
    pages = {}
    for i in range(3, n + 1):
        txt = subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), "-layout", pdf, "-"], capture_output=True, text=True).stdout
        for line in txt.split("\n"):
            l = line.strip()
            for lvl, h in TOC_ENTRIES:
                if h not in pages and l == h:
                    pages[h] = str(i)
    return pages


if __name__ == "__main__":
    out = os.path.join(DOCS, "CPS304_Group4_Report.docx")
    build({}, out)
    pdf, n = to_pdf(out)
    pages = find_pages(pdf, n)
    build(pages, out)
    pdf, n2 = to_pdf(out)
    pages2 = find_pages(pdf, n2)
    if pages2 != pages:
        build(pages2, out)
        pdf, n2 = to_pdf(out)
        pages2 = find_pages(pdf, n2)
    missing = [h for _, h in TOC_ENTRIES if h not in pages2]
    print("PAGES:", n2, "missing toc entries:", missing)
