"""Freeze both systems for one benchmark run and record provenance.

Both repos have uncommitted work and at least one is being edited while the
benchmark runs, so each run executes from a copy taken at start time.

    python evaluation/benchmark_ab/snapshot.py <run_id> <snapshot_root>

Writes  <snapshot_root>/A  (health-system-chatbot: src, docs, pyproject, .env)
        <snapshot_root>/B  (text-to-sql-chatbot: src, knowledge, .env)
        evaluation/benchmark_ab/runs/<run_id>/provenance/{A,B}.patch, provenance.json
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
A_ROOT = HERE.parent.parent
B_ROOT = A_ROOT.parent / "text-to-sql-chatbot"

A_PARTS = ["src", "docs", "pyproject.toml", ".env"]
B_PARTS = ["src", "knowledge", ".env"]
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")

# B only sends reasoning_effort to model names starting with these prefixes, so
# with gpt-6-luna every call silently ran at the provider default. The snapshot
# sends it for gpt-6 too and lets the benchmark pin one effort for every call
# (BENCH_REASONING_EFFORT), the same effort A uses (CHATBOT_LLM_REASONING_EFFORT).
B_EFFORT_OLD = 'model.startswith(("gpt-5", "o3", "o4"))'
B_EFFORT_NEW = 'model.startswith(("gpt-5", "gpt-6", "o3", "o4"))'
B_ASSIGN_OLD = 'kwargs["reasoning_effort"] = reasoning_effort'
B_ASSIGN_NEW = 'kwargs["reasoning_effort"] = __import__("os").environ.get("BENCH_REASONING_EFFORT") or reasoning_effort'


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False).stdout


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name != ".env"):
        h.update(str(path.relative_to(root)).encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def copy_parts(src: Path, dst: Path, parts: list[str]) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for part in parts:
        s = src / part
        if s.is_dir():
            shutil.copytree(s, dst / part, ignore=IGNORE)
        elif s.exists():
            shutil.copy2(s, dst / part)


def main() -> int:
    run_id, snap_root = sys.argv[1], Path(sys.argv[2])
    run_dir = HERE / "runs" / run_id / "provenance"
    run_dir.mkdir(parents=True, exist_ok=True)

    copy_parts(A_ROOT, snap_root / "A", A_PARTS)
    copy_parts(B_ROOT, snap_root / "B", B_PARTS)

    llm = snap_root / "B" / "src" / "llm.py"
    text = llm.read_text(encoding="utf-8")
    n_patched = text.count(B_EFFORT_OLD)
    if n_patched == 0 or text.count(B_ASSIGN_OLD) != n_patched:
        raise SystemExit("B llm.py changed: reasoning_effort patch sites not found")
    llm.write_text(text.replace(B_EFFORT_OLD, B_EFFORT_NEW).replace(B_ASSIGN_OLD, B_ASSIGN_NEW), encoding="utf-8")

    (run_dir / "A.patch").write_text(git(A_ROOT, "diff", "HEAD", "--", "src", "docs", "pyproject.toml"), encoding="utf-8")
    (run_dir / "B.patch").write_text(git(B_ROOT, "diff", "HEAD", "--", "src", "knowledge"), encoding="utf-8")
    shutil.copy2(B_ROOT / "knowledge" / "sihrd9.yaml", run_dir / "B_knowledge_sihrd9.yaml")

    prov = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "A": {"repo": str(A_ROOT), "head": git(A_ROOT, "rev-parse", "HEAD").strip(),
              "snapshot_sha256": tree_hash(snap_root / "A")},
        "B": {"repo": str(B_ROOT), "head": git(B_ROOT, "rev-parse", "HEAD").strip(),
              "snapshot_sha256": tree_hash(snap_root / "B"),
              "reasoning_effort_patch_sites": n_patched},
    }
    (run_dir / "provenance.json").write_text(json.dumps(prov, indent=2), encoding="utf-8")
    print(json.dumps(prov, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
