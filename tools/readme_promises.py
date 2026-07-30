#!/usr/bin/env python3
"""Fail the build if README promises something the package does not deliver.

Both bugs this guards were actually shipped once: "pillow optional" while the
radar decoder imported it at module level, and "pip install runemap" while the
package was not on PyPI. A sentence in the README is an interface; CI has to
hold it to the same standard as code, or documentation rots silently -- and a
broken promise is indistinguishable from a broken feature to whoever hit it."""
import importlib, pathlib, re, subprocess, sys

R = pathlib.Path("README.md").read_text(encoding="utf-8")
fails, checks = [], 0

# 1. every `from runemap import X` shown in the README must actually resolve
for m in re.finditer(r"^\s*from\s+(runemap[\w\.]*)\s+import\s+([\w, ]+)", R, re.M):
    mod, names = m.group(1), [x.strip() for x in m.group(2).split(",") if x.strip()]
    checks += 1
    try:
        o = importlib.import_module(mod)
        for n in names:
            if not hasattr(o, n):
                fails.append("%s has no attribute %s" % (mod, n))
    except Exception as e:
        fails.append("cannot import %s (%r)" % (mod, e))

# 2. every example the README tells a stranger to run must exist and produce output
for m in re.finditer(r"^\s*python3?\s+(examples/[\w/.\-]+\.py)", R, re.M):
    p = m.group(1); checks += 1
    if not pathlib.Path(p).exists():
        fails.append("README points at missing file %s" % p); continue
    r = subprocess.run([sys.executable, p], capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not r.stdout.strip():
        fails.append("example %s rc=%d stderr=%s" % (p, r.returncode, r.stderr[-200:]))

# 3. never advertise a PyPI install while admitting it is not on PyPI
checks += 1
if re.search(r"pip install\s+runemap(\s|$|`)", R) and "not on PyPI" in R:
    fails.append("README both offers 'pip install runemap' and admits it is not on PyPI")

# 4. a dependency the README calls optional must not be a hard import
deps = re.findall(r'^dependencies\s*=\s*\[([^\]]*)\]',
                  pathlib.Path("pyproject.toml").read_text(encoding="utf-8"), re.M | re.S)
names = re.findall(r'"([A-Za-z0-9_.\-]+)', deps[0]) if deps else []
src = "\n".join(p.read_text(encoding="utf-8") for p in pathlib.Path("runemap").rglob("*.py"))
for dep in names:
    checks += 1
    if re.search(r"%s[^\n]{0,40}optional" % re.escape(dep), R, re.I) and \
       re.search(r"^\s*(?:import|from)\s+%s\b" % re.escape(dep), src, re.M):
        fails.append("README calls %s optional but runemap/ imports it at module level" % dep)

print("\n".join("FAIL " + f for f in fails) if fails
      else "README promises OK (%d checks)" % checks)
sys.exit(1 if fails else 0)
