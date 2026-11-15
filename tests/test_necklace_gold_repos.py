"""package-risk-audit v2 activity answer set: npm repository -> GitHub newest release, resumable under the ledger."""
import json

from agent_market.necklaces import gold_repos


def setup(tmp_path, names=("lodash", "left-pad", "no-repo", "gone")):
    folder = tmp_path / "gold" / "package-risk-audit"
    folder.mkdir(parents=True)
    lines = [json.dumps({"case_id": f"npm:{n}", "input": {"ecosystem": "npm", "package": n}}) for n in names]
    lines.append(json.dumps({"case_id": "PyPI:numpy", "input": {"ecosystem": "PyPI", "package": "numpy"}}))
    (folder / "holdout-r1.jsonl").write_text("\n".join(lines) + "\n")
    return folder


def fake(limit=99):
    calls = []

    def get(url):
        if len(calls) >= limit:
            raise gold_repos.Budget("system_share")
        calls.append(url)
        if url.endswith("/lodash/latest"):
            return 200, {"version": "4.17.21", "repository": {"type": "git", "url": "git+https://github.com/lodash/lodash.git"}}
        if url.endswith("/left-pad/latest"):
            return 200, {"version": "1.3.0", "repository": "github:stevemao/left-pad"}
        if url.endswith("/no-repo/latest"):
            return 200, {"version": "1.0.0", "repository": "https://gitlab.com/x/y"}
        if url.endswith("/gone/latest"):
            return 404, None
        if "lodash/lodash/releases" in url:
            return 200, [{"tag_name": "4.17.21", "published_at": "2021-02-20T15:42:16Z"}]
        if "left-pad" in url:
            return 404, None
        raise AssertionError(url)
    return get, calls


def test_the_set_is_built_across_runs_under_the_ledger(tmp_path):
    folder = setup(tmp_path)
    get, calls = fake(limit=1)
    out = gold_repos.step(tmp_path, get)
    assert out["stopped"] == "system_share" and out["done"] == 0 and "written" not in out
    progress = json.loads((folder / "repos-progress.json").read_text())
    assert progress["lodash"]["repository_github"] == "lodash/lodash"     # kept for the next run
    get, calls = fake()
    out = gold_repos.step(tmp_path, get)
    assert out["done"] == 1 and out["left"] == 0 and out["written"] == {"cases": 1, "no_releases": 0}
    assert not any("/lodash/latest" in c for c in calls)                  # npm was not asked twice
    assert out["dropped"] == {"left-pad": "GitHub does not know the repository", "no-repo": "npm repository is not on GitHub",
                              "gone": "npm has no such package"}
    case = json.loads((folder / "holdout-v2-activity.jsonl").read_text())
    assert case["truth"]["repository_github"] == "lodash/lodash" and case["truth"]["latest_release_tag"] == "4.17.21"
    assert case["truth"]["valid_until"] and json.loads((folder / "manifest.json").read_text())["files"]["holdout-v2-activity"]


def test_npm_repository_forms():
    assert gold_repos.repo_of({"repository": "https://github.com/a/b.git"}) == "a/b"
    assert gold_repos.repo_of({"repository": {"url": "git+ssh://git@github.com/a/b.git"}}) == "a/b"
    assert gold_repos.repo_of({"repository": "github:stevemao/left-pad"}) == "stevemao/left-pad"
    assert gold_repos.repo_of({"repository": "npm/cli"}) == "npm/cli"
    assert gold_repos.repo_of({"repository": "https://gitlab.com/x/y"}) is None
    assert gold_repos.repo_of({}) is None


def test_a_429_stops_the_round_and_keeps_the_progress(tmp_path):
    import io
    import urllib.error
    calls = []

    def opener(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {}, io.BytesIO(b""))
    import pytest
    with pytest.raises(gold_repos.Budget) as stopped:
        gold_repos.fetch_json("https://api.crossref.org/works?x", reserve=lambda u, s: (True, "ok"),
                              note=lambda *a, **k: calls.append(a), opener=opener)
    assert str(stopped.value) == "provider_429" and calls[0][2] == 429
