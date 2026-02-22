import asyncio
from pathlib import Path

from repo_summarizer import summarize_changed_files, build_diff_only_summary


class _DummySummarizer:
    def __init__(self):
        self.calls = 0

    async def summarize_file(self, file_units):
        self.calls += 1
        return f"summary:{Path(file_units.path).name}"


class _DummyOrchestrator:
    def __init__(self):
        self.summarizer = _DummySummarizer()


def test_summarize_changed_files_only_for_parseable_sources(tmp_path: Path):
    py = tmp_path / "a.py"
    txt = tmp_path / "notes.txt"
    py.write_text("def a():\n    return 1\n")
    txt.write_text("not code")

    orch = _DummyOrchestrator()
    summaries = asyncio.run(summarize_changed_files(orch, [str(py), str(txt)]))

    assert summaries == {str(py): "summary:a.py"}
    assert orch.summarizer.calls == 1


def test_build_diff_only_summary_includes_counts():
    text = build_diff_only_summary(
        "old summary here",
        added=2,
        modified=3,
        deleted=1,
    )
    assert "+2 added" in text
    assert "3 modified" in text
    assert "-1 deleted" in text
