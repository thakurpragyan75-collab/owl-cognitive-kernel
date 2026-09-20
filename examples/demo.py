from pathlib import Path
from owl_kernel.runtime import Runtime

ROOT = Path(__file__).resolve().parents[1]
repo = ROOT / "examples" / "shop_repo"
work = ROOT / ".kernel-work"
work.mkdir(exist_ok=True)

GOAL = (
    "Inspect this repository, find the cause of the failing behavior, repair it, "
    "run the relevant tests, perform security verification, and produce a final report. "
    "Only keep the candidate if tests pass."
)

if __name__ == "__main__":
    r = Runtime(work, repo)
    result = r.execute(GOAL)
    print("ok", result["ok"])
    print("provider", result["provider"])
    print("diff", result["diff"][:1500])
    print("events", len(result["replay"]))
    print("changed", result.get("changed"))
