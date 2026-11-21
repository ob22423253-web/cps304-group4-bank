"""Builds docs/CPS304_Group4_SourceCode_Appendix.docx and .pdf: the FULL source of src/, demo/run_demo.py and tests/,
one heading per file, monospace, line numbers, page numbers."""
import glob
import os
import re
import subprocess

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
NAVY = RGBColor(0x1F, 0x3A, 0x5F)
MONO = "Courier New"
FILES = (sorted(glob.glob(os.path.join(ROOT, "src", "*.py"))) + [os.path.join(ROOT, "demo", "run_demo.py")]
         + sorted(glob.glob(os.path.join(ROOT, "tests", "*.py"))))


def font(style, name, size=None, bold=None, color=None):
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


def fld(run, instr):
    for t, txt in (("begin", None), (None, instr), ("end", None)):
        if t:
            e = OxmlElement("w:fldChar"); e.set(qn("w:fldCharType"), t)
        else:
            e = OxmlElement("w:instrText"); e.set(qn("xml:space"), "preserve"); e.text = txt
        run._r.append(e)


def border(p, side="bottom", color="1F3A5F", sz=6):
    pPr = p._p.get_or_add_pPr()
    pb = OxmlElement("w:pBdr")
    e = OxmlElement("w:" + side)
    e.set(qn("w:val"), "single"); e.set(qn("w:sz"), str(sz)); e.set(qn("w:space"), "1"); e.set(qn("w:color"), color)
    pb.append(e); pPr.append(pb)


def build():
    doc = Document()
    s = doc.sections[0]
    s.page_width, s.page_height = Cm(21), Cm(29.7)
    s.left_margin = s.right_margin = Cm(1.5)
    s.top_margin, s.bottom_margin = Cm(1.6), Cm(1.5)
    s.header_distance, s.footer_distance = Cm(0.7), Cm(0.6)
    font(doc.styles["Normal"], "Calibri", 10)
    font(doc.styles["Heading 1"], "Calibri", 12, True, NAVY)
    h1 = doc.styles["Heading 1"].paragraph_format
    h1.space_before, h1.space_after, h1.keep_with_next = Pt(8), Pt(2), True
    hp = s.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = hp.add_run("CPS 304 Operating System II  |  Group 4  |  Source code appendix"); r.font.size = Pt(8); r.font.color.rgb = RGBColor(0x59, 0x59, 0x59)
    border(hp, "bottom", "A6A6A6", 4)
    fp = s.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = fp.add_run("Page "); r.font.size = Pt(8.5)
    r2 = fp.add_run(); r2.font.size = Pt(8.5); fld(r2, "PAGE")

    p = doc.add_paragraph()
    r = p.add_run("CPS 304 Operating System II - Group 4"); r.bold = True; r.font.size = Pt(14); r.font.color.rgb = NAVY
    p.paragraph_format.space_after = Pt(0)
    p = doc.add_paragraph()
    r = p.add_run("Fault-Tolerant Distributed Banking System for the UTG Microfinance Unit - complete source code"); r.font.size = Pt(11)
    border(p, "bottom", "1F3A5F", 8)
    p.paragraph_format.space_after = Pt(4)
    total = 0
    idx = []
    for f in FILES:
        n = len(open(f).read().split("\n")) - (1 if open(f).read().endswith("\n") else 0)
        total += n
        idx.append("%s (%d lines)" % (os.path.relpath(f, ROOT).replace(os.sep, "/"), n))
    p = doc.add_paragraph()
    r = p.add_run("Files: " + "; ".join(idx) + ".  Total %d lines." % total); r.font.size = Pt(8.5)
    p.paragraph_format.space_after = Pt(2)

    for f in FILES:
        rel = os.path.relpath(f, ROOT).replace(os.sep, "/")
        doc.add_heading(rel, 1)
        text = open(f).read().rstrip("\n").split("\n")
        width = len(str(len(text)))
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0); p.paragraph_format.line_spacing = 1.0
        for i, line in enumerate(text, 1):
            r = p.add_run("%*d  %s" % (width, i, line.replace("\t", "    ")))
            r.font.name, r.font.size = MONO, Pt(6.6)
            rf = r._r.get_or_add_rPr().find(qn("w:rFonts"))
            rf.set(qn("w:eastAsia"), MONO); rf.set(qn("w:cs"), MONO)
            if i < len(text):
                r.add_break()
    out = os.path.join(DOCS, "CPS304_Group4_SourceCode_Appendix.docx")
    doc.save(out)
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", DOCS, out], check=True, capture_output=True, timeout=600)
    pdf = out[:-5] + ".pdf"
    n = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", pdf], capture_output=True, text=True).stdout).group(1))
    print("APPENDIX PAGES:", n, "lines:", total)


if __name__ == "__main__":
    build()
