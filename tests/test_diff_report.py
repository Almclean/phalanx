from manifest import ManifestDiff, ModifiedFile, RunManifest
from diff_report import manifest_diff_to_dict, generate_diff_digest


class _FakeSummarizer:
    def __init__(self):
        self.prompts: list[str] = []

    async def summarize_diff_digest(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "digest text"


def _manifest(run_id: str, summary: str) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        repo_path="/tmp/repo",
        repo_url=None,
        timestamp="2026-02-22T10:00:00Z",
        duration_secs=1.0,
        total_files=1,
        total_units=1,
        api_cost_usd=0.1,
        final_summary=summary,
        files={},
    )


def test_manifest_diff_to_dict_counts():
    diff = ManifestDiff(
        added=["a.py"],
        deleted=["b.py"],
        modified=[
            ModifiedFile(
                path="c.py",
                language="python",
                old_summary="old",
                new_summary="new",
                unit_count_delta=1,
            )
        ],
        unchanged=4,
        churn_hotspots=["c.py"],
    )
    payload = manifest_diff_to_dict(diff, old_run_id="r1", new_run_id="r2")
    assert payload["counts"] == {"added": 1, "deleted": 1, "modified": 1, "unchanged": 4}
    assert payload["old_run_id"] == "r1"
    assert payload["new_run_id"] == "r2"


async def _run_digest():
    fake = _FakeSummarizer()
    diff = ManifestDiff(added=[], deleted=[], modified=[], unchanged=0, churn_hotspots=[])
    text = await generate_diff_digest(
        summarizer=fake,
        diff=diff,
        old_manifest=_manifest("r1", "old summary"),
        new_manifest=_manifest("r2", "new summary"),
    )
    return text, fake.prompts


def test_generate_diff_digest_uses_summarizer():
    import asyncio

    text, prompts = asyncio.run(_run_digest())
    assert text == "digest text"
    assert len(prompts) == 1
    assert "Previous run: r1" in prompts[0]
    assert "Current run: r2" in prompts[0]
