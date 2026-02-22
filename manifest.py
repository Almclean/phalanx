"""
manifest.py — Run manifest storage and diff helpers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Optional

from parser import parse_file


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(data: str) -> str:
    return _sha256_bytes(data.encode("utf-8", errors="replace"))


def _repo_slug(repo_path: str | Path) -> str:
    p = Path(str(repo_path))
    parts = [part for part in p.parts if part not in ("/", "")]
    tail = parts[-2:] if len(parts) >= 2 else parts
    return "_".join(tail) or "repo"


@dataclass
class FileRecord:
    content_hash: str
    summary_hash: str
    summary: str
    language: str
    unit_count: int
    last_seen: str


@dataclass
class RunManifest:
    run_id: str
    repo_path: str
    repo_url: str | None
    timestamp: str
    duration_secs: float
    total_files: int
    total_units: int
    api_cost_usd: float
    final_summary: str
    files: dict[str, FileRecord]


@dataclass
class ModifiedFile:
    path: str
    language: str
    old_summary: str
    new_summary: str
    unit_count_delta: int


@dataclass
class ManifestDiff:
    added: list[str]
    deleted: list[str]
    modified: list[ModifiedFile]
    unchanged: int
    churn_hotspots: list[str]


class ManifestStore:
    def __init__(self, manifest_dir: Optional[Path] = None):
        if manifest_dir is None:
            manifest_dir = Path.home() / ".repo_summarizer_cache" / "manifests"
        self.manifest_dir = manifest_dir
        self.manifest_dir.mkdir(parents=True, exist_ok=True)

    def _manifest_path(self, repo_path: str | Path, run_id: str) -> Path:
        return self.manifest_dir / f"{_repo_slug(repo_path)}_{run_id[:8]}.json"

    def save(self, manifest: RunManifest) -> Path:
        path = self._manifest_path(manifest.repo_path, manifest.run_id)
        payload = asdict(manifest)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return path

    def load(self, path: Path) -> Optional[RunManifest]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        try:
            files = {
                p: FileRecord(**record)
                for p, record in raw.get("files", {}).items()
            }
            return RunManifest(
                run_id=raw["run_id"],
                repo_path=raw["repo_path"],
                repo_url=raw.get("repo_url"),
                timestamp=raw["timestamp"],
                duration_secs=float(raw.get("duration_secs", 0.0)),
                total_files=int(raw.get("total_files", 0)),
                total_units=int(raw.get("total_units", 0)),
                api_cost_usd=float(raw.get("api_cost_usd", 0.0)),
                final_summary=str(raw.get("final_summary", "")),
                files=files,
            )
        except (KeyError, TypeError, ValueError):
            return None

    def find_all(self, repo_path: str | Path, limit: int = 10) -> list[RunManifest]:
        target = str(Path(repo_path).resolve())
        manifests: list[RunManifest] = []
        for p in self.manifest_dir.glob("*.json"):
            m = self.load(p)
            if m is None:
                continue
            if str(Path(m.repo_path).resolve()) != target:
                continue
            manifests.append(m)

        manifests.sort(key=lambda m: m.timestamp, reverse=True)
        return manifests[:limit]

    def find_latest(self, repo_path: str | Path, run_id_prefix: str | None = None) -> Optional[RunManifest]:
        all_for_repo = self.find_all(repo_path, limit=200)
        if run_id_prefix:
            all_for_repo = [m for m in all_for_repo if m.run_id.startswith(run_id_prefix)]
        return all_for_repo[0] if all_for_repo else None

    @staticmethod
    def diff(old: RunManifest, new: RunManifest) -> ManifestDiff:
        old_paths = set(old.files.keys())
        new_paths = set(new.files.keys())

        added = sorted(new_paths - old_paths)
        deleted = sorted(old_paths - new_paths)

        modified: list[ModifiedFile] = []
        unchanged = 0
        for path in sorted(old_paths & new_paths):
            old_rec = old.files[path]
            new_rec = new.files[path]
            if old_rec.content_hash == new_rec.content_hash:
                unchanged += 1
                continue
            modified.append(
                ModifiedFile(
                    path=path,
                    language=new_rec.language,
                    old_summary=old_rec.summary,
                    new_summary=new_rec.summary,
                    unit_count_delta=new_rec.unit_count - old_rec.unit_count,
                )
            )

        return ManifestDiff(
            added=added,
            deleted=deleted,
            modified=modified,
            unchanged=unchanged,
            churn_hotspots=[],
        )

    @staticmethod
    def compute_churn_hotspots(
        manifests_desc: list[RunManifest],
        *,
        min_hits: int = 3,
        window: int = 5,
    ) -> list[str]:
        if len(manifests_desc) < 2:
            return []

        window_manifests = manifests_desc[:window]
        counts: dict[str, int] = {}
        for i in range(len(window_manifests) - 1):
            newer = window_manifests[i]
            older = window_manifests[i + 1]
            d = ManifestStore.diff(older, newer)
            for m in d.modified:
                counts[m.path] = counts.get(m.path, 0) + 1

        return sorted([path for path, count in counts.items() if count >= min_hits])


def new_run_id(repo_path: str | Path) -> str:
    seed = f"{Path(repo_path).resolve()}|{_now_iso()}"
    return _sha256_text(seed)[:16]


def build_run_manifest(
    *,
    repo_path: Path,
    repo_url: str | None,
    run_id: str,
    duration_secs: float,
    api_cost_usd: float,
    final_summary: str,
    file_summaries: dict[str, str],
) -> RunManifest:
    now = _now_iso()
    files: dict[str, FileRecord] = {}
    total_units = 0

    for path_str, summary in sorted(file_summaries.items()):
        path = Path(path_str)
        if not path.exists():
            continue
        try:
            content_hash = _sha256_bytes(path.read_bytes())
        except OSError:
            continue

        parsed = parse_file(path)
        if parsed is None:
            language = path.suffix.lower().lstrip(".") or "unknown"
            unit_count = 0
        else:
            language = parsed.language
            unit_count = len(parsed.units)

        total_units += unit_count
        files[path_str] = FileRecord(
            content_hash=content_hash,
            summary_hash=_sha256_text(summary),
            summary=summary,
            language=language,
            unit_count=unit_count,
            last_seen=now,
        )

    return RunManifest(
        run_id=run_id,
        repo_path=str(repo_path.resolve()),
        repo_url=repo_url,
        timestamp=now,
        duration_secs=duration_secs,
        total_files=len(files),
        total_units=total_units,
        api_cost_usd=api_cost_usd,
        final_summary=final_summary,
        files=files,
    )
