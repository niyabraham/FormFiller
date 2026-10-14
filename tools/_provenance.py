"""One recipe for 'which pipeline source produced this evaluation', shared by the SPA and widget evaluators.

recipe `formfill-src-v2`: sha256 over
    1. the raw text of `git diff HEAD -- formfill` (tracked files, relative to the evaluated commit; no trimming), then
    2. for every untracked, non-ignored file under formfill/ in sorted path order: "<path>:<sha256 of its bytes>\n".
Returns None for a clean tree. The same source snapshot therefore always hashes to the same value, whichever evaluator
computed it. Earlier results (Phase 3C, Phase 3D round 1) used two slightly different, undocumented variants of this
(`formfill-src-v1a` SPA: trimmed diff + "\n"; `v1b` widget: trimmed diff); they differed only in a trailing newline.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

RECIPE = "formfill-src-v2"


def _git(root: Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True, check=False).stdout


def pipeline_source_sha256(root: Path) -> str | None:
    diff = _git(root, "diff", "HEAD", "--", "formfill")
    untracked = sorted(p for p in _git(root, "ls-files", "--others", "--exclude-standard", "--", "formfill").split("\n") if p)
    blob = diff + "".join(f"{p}:{hashlib.sha256((root / p).read_bytes()).hexdigest()}\n" for p in untracked)
    return hashlib.sha256(blob.encode()).hexdigest() if blob else None
