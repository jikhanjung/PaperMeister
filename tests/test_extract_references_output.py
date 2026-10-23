"""scripts/extract_references.py prints titles the Windows code page cannot encode.

With stdout redirected (a log file, a pipe) Python on a Korean Windows writes
cp949, which has no en dash. A run on 2026-10-23 died printing
"[13/27] 9908 Pliocene–Pleistocene…" — that paper was saved, the 14 still in
flight were parsed by the LLM and dropped, and the resolve pass never ran.
"""
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'extract_references.py'

_LOAD_AND_PRINT = f"""
import importlib.util
spec = importlib.util.spec_from_file_location('extract_references', {str(SCRIPT)!r})
spec.loader.exec_module(importlib.util.module_from_spec(spec))
print('[13/27] 9908 Pliocene\\u2013Pleistocene ok | 139 refs')
"""


def _run(code):
    env = dict(os.environ, PYTHONIOENCODING='cp949')
    return subprocess.run([sys.executable, '-c', code], capture_output=True, env=env,
                          cwd=SCRIPT.parent.parent, timeout=60)


def test_cp949_stdout_cannot_print_an_en_dash():
    """The premise: without the script's fix, this print raises."""
    assert _run("print('Pliocene\\u2013Pleistocene')").returncode != 0


def test_script_prints_a_title_cp949_lacks():
    proc = _run(_LOAD_AND_PRINT)
    assert proc.returncode == 0, proc.stderr.decode('utf-8', 'replace')
    assert 'Pliocene–Pleistocene' in proc.stdout.decode('utf-8')
