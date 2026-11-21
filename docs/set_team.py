"""Writes the real names into docs/team.json and README.md, then rebuilds the report.
    python docs/set_team.py "Name 1" "Name 2" "Name 3" "Name 4" "Lecturer name" "Faculty or school"
"""
import json, os, re, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if len(sys.argv) != 7:
    sys.exit(__doc__)
n1, n2, n3, n4, lect, fac = sys.argv[1:]
p = os.path.join(ROOT, "docs", "team.json")
t = json.load(open(p))
old = [m[0] for m in t["members"]] + [t["lecturer"], t["faculty"]]
for m, n in zip(t["members"], (n1, n2, n3, n4)):
    m[0] = n
t["lecturer"], t["faculty"] = lect, fac
json.dump(t, open(p, "w"), indent=2)
r = os.path.join(ROOT, "README.md")
s = open(r).read()
for o, n in zip(old, (n1, n2, n3, n4, lect, fac)):
    s = s.replace(o, n)
open(r, "w").write(s)
subprocess.run([sys.executable, os.path.join(ROOT, "docs", "build_report.py")], check=True)
