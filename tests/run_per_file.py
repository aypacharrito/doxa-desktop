"""Run every tests/test_*.py in its own process (Tk tests can't share one interpreter) and sum the results.

    %LOCALAPPDATA%\\Programs\\Jarvis\\runtime\\Scripts\\python.exe tests\\run_per_file.py [-j 6]
"""
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
jobs = int(sys.argv[sys.argv.index("-j") + 1]) if "-j" in sys.argv else 6


def run(path):
    done = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(HERE), "-p", path.name],
                          cwd=HERE.parent, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=900)
    out = done.stdout + done.stderr
    ran = re.search(r"Ran (\d+) test", out)
    status = "OK" if re.search(r"^OK", out, re.M) else "FAIL"
    return path.name, int(ran.group(1)) if ran else 0, status, out


files = sorted(HERE.glob("test_*.py"))
with ThreadPoolExecutor(jobs) as pool:
    results = list(pool.map(run, files))
total = sum(r[1] for r in results)
failed = [r for r in results if r[2] != "OK"]
for name, count, status, out in failed:
    print(f"--- {name}: {status} ({count} tests)")
    print("\n".join(line for line in out.splitlines() if re.match(r"(FAIL|ERROR|AssertionError|\w+Error)", line))[:3000])
print(f"{total} tests in {len(files)} files, {len(failed)} file(s) failed")
sys.exit(1 if failed else 0)
