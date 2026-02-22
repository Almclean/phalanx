from pathlib import Path

from manifest import (
    FileRecord,
    ManifestStore,
    RunManifest,
    build_run_manifest,
    compute_repo_changes,
)


def test_build_manifest_and_diff_roundtrip(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    a = repo / "a.py"
    b = repo / "b.py"
    a.write_text("def a():\n    return 1\n")
    b.write_text("def b():\n    return 2\n")

    m1 = build_run_manifest(
        repo_path=repo,
        repo_url=None,
        run_id="run1",
        duration_secs=1.0,
        api_cost_usd=0.1,
        final_summary="summary-1",
        file_summaries={
            str(a): "A summary",
            str(b): "B summary",
        },
    )

    # mutate repo state for second run: delete a, modify b, add c
    a.unlink()
    b.write_text("def b():\n    return 22\n")
    c = repo / "c.py"
    c.write_text("def c():\n    return 3\n")

    m2 = build_run_manifest(
        repo_path=repo,
        repo_url=None,
        run_id="run2",
        duration_secs=1.2,
        api_cost_usd=0.2,
        final_summary="summary-2",
        file_summaries={
            str(b): "B summary new",
            str(c): "C summary",
        },
    )

    store = ManifestStore(tmp_path / "manifests")
    p1 = store.save(m1)
    p2 = store.save(m2)

    l1 = store.load(p1)
    l2 = store.load(p2)
    assert l1 is not None
    assert l2 is not None
    assert l1.run_id == "run1"
    assert l2.run_id == "run2"

    diff = store.diff(l1, l2)
    assert diff.added == [str(c)]
    assert diff.deleted == [str(a)]
    assert len(diff.modified) == 1
    assert diff.modified[0].path == str(b)


def _mk_manifest(run_id: str, ts: str, content_hash: str) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        repo_path="/tmp/repo",
        repo_url=None,
        timestamp=ts,
        duration_secs=1.0,
        total_files=1,
        total_units=1,
        api_cost_usd=0.0,
        final_summary=f"s-{run_id}",
        files={
            "src/core.py": FileRecord(
                content_hash=content_hash,
                summary_hash=f"h-{run_id}",
                summary=f"sum-{run_id}",
                language="python",
                unit_count=1,
                last_seen=ts,
            )
        },
    )


def test_churn_hotspots_detect_three_of_last_five():
    # Desc order: newest -> oldest
    manifests = [
        _mk_manifest("r5", "2026-02-22T15:00:00Z", "h5"),
        _mk_manifest("r4", "2026-02-22T14:00:00Z", "h4"),
        _mk_manifest("r3", "2026-02-22T13:00:00Z", "h3"),
        _mk_manifest("r2", "2026-02-22T12:00:00Z", "h2"),
        _mk_manifest("r1", "2026-02-22T11:00:00Z", "h1"),
    ]
    hotspots = ManifestStore.compute_churn_hotspots(manifests, min_hits=3, window=5)
    assert hotspots == ["src/core.py"]


def test_compute_repo_changes_added_modified_deleted(tmp_path: Path):
    repo = tmp_path / "repo_changes"
    repo.mkdir()
    a = repo / "a.py"
    b = repo / "b.py"
    a.write_text("def a():\n    return 1\n")
    b.write_text("def b():\n    return 2\n")

    old_manifest = build_run_manifest(
        repo_path=repo,
        repo_url=None,
        run_id="old",
        duration_secs=0.1,
        api_cost_usd=0.0,
        final_summary="old",
        file_summaries={str(a.resolve()): "A", str(b.resolve()): "B"},
    )

    # mutate filesystem: modify b, delete a, add c
    a.unlink()
    b.write_text("def b():\n    return 22\n")
    c = repo / "c.py"
    c.write_text("def c():\n    return 3\n")

    changes = compute_repo_changes(repo_path=repo, previous_manifest=old_manifest)
    assert changes.added == [str(c.resolve())]
    assert changes.deleted == [str(a.resolve())]
    assert changes.modified == [str(b.resolve())]
    assert changes.unchanged == []


def test_manifest_prune_keeps_latest_n(tmp_path: Path):
    repo = tmp_path / "repo_prune"
    repo.mkdir()
    f = repo / "x.py"
    f.write_text("def x():\n    return 1\n")

    store = ManifestStore(tmp_path / "manifests")
    m1 = build_run_manifest(
        repo_path=repo,
        repo_url=None,
        run_id="run1",
        duration_secs=0.1,
        api_cost_usd=0.0,
        final_summary="s1",
        file_summaries={str(f.resolve()): "sum1"},
    )
    m1.timestamp = "2026-02-22T10:00:00Z"
    m2 = build_run_manifest(
        repo_path=repo,
        repo_url=None,
        run_id="run2",
        duration_secs=0.1,
        api_cost_usd=0.0,
        final_summary="s2",
        file_summaries={str(f.resolve()): "sum2"},
    )
    m2.timestamp = "2026-02-22T11:00:00Z"
    m3 = build_run_manifest(
        repo_path=repo,
        repo_url=None,
        run_id="run3",
        duration_secs=0.1,
        api_cost_usd=0.0,
        final_summary="s3",
        file_summaries={str(f.resolve()): "sum3"},
    )
    m3.timestamp = "2026-02-22T12:00:00Z"

    store.save(m1)
    store.save(m2)
    store.save(m3)

    removed = store.prune(repo, keep=2)
    assert len(removed) == 1

    remaining = store.find_all(repo, limit=10)
    assert len(remaining) == 2
    assert [m.run_id for m in remaining] == ["run3", "run2"]
