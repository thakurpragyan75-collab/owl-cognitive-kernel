from pathlib import Path
from owl_kernel.runtime import Runtime

ROOT = Path(__file__).resolve().parents[1]
repo = ROOT / "examples" / "fixture_repo"
work = ROOT / ".kernel-work"
work.mkdir(exist_ok=True)

GOAL = (
    "Find the bug in the local math helper, determine the root cause, "
    "create a fix, run the relevant tests, and only apply the fix if the tests pass."
)

if __name__ == "__main__":
    r = Runtime(work, repo)
    result = r.execute(GOAL)
    print("ok", result["ok"])
    print("provider", result["provider"])
    print("diff", result["diff"])
    print("events", len(result["replay"]))
