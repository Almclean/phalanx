"""
diff_report.py — JSON diff + optional prose digest generation.
"""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any, Optional

from manifest import ManifestDiff, RunManifest
from prompts import diff_digest_prompt


def manifest_diff_to_dict(
    diff: ManifestDiff,
    *,
    old_run_id: str | None,
    new_run_id: str,
) -> dict[str, Any]:
    return {
        "old_run_id": old_run_id,
        "new_run_id": new_run_id,
        "added": diff.added,
        "deleted": diff.deleted,
        "modified": [asdict(m) for m in diff.modified],
        "unchanged": diff.unchanged,
        "churn_hotspots": diff.churn_hotspots,
        "counts": {
            "added": len(diff.added),
            "deleted": len(diff.deleted),
            "modified": len(diff.modified),
            "unchanged": diff.unchanged,
        },
    }


def write_diff_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


async def generate_diff_digest(
    *,
    summarizer: Any,
    diff: ManifestDiff,
    old_manifest: Optional[RunManifest],
    new_manifest: RunManifest,
) -> str:
    prompt = diff_digest_prompt(
        old_run_id=old_manifest.run_id if old_manifest else None,
        new_run_id=new_manifest.run_id,
        old_summary=old_manifest.final_summary if old_manifest else None,
        new_summary=new_manifest.final_summary,
        diff=diff,
    )

    # Reuse the summarizer's Sonnet caller for consistent tracking and retry behavior.
    return await summarizer.summarize_diff_digest(prompt)
