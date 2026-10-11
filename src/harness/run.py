"""CLI 入口。

用法（项目根目录下）：
  python -m src.harness.run --arm C --run 0 --smoke     # 烟雾测试：2 章
  python -m src.harness.run --arm A --run 1             # 正式：12 章
"""
import argparse
import json
import os

from .arms import run_arm
from .ledger import Ledger
from .metrics import canary_hits

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXP_DIR = os.path.join(ROOT, "experiments", "exp001")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["A", "B", "C"])
    ap.add_argument("--run", type=int, required=True)
    ap.add_argument("--smoke", action="store_true", help="只写 2 章验证管线")
    args = ap.parse_args()

    with open(os.path.join(EXP_DIR, "spec.json"), encoding="utf-8") as f:
        spec = json.load(f)
    with open(os.path.join(EXP_DIR, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)

    tag = "smoke-" if args.smoke else ""
    outdir = os.path.join(EXP_DIR, "runs", f"{tag}{args.arm}{args.run}")
    chapters = run_arm(args.arm, args.run, spec, cfg, outdir, chapters_override=2 if args.smoke else None)

    hits = canary_hits(chapters, Ledger(spec))
    with open(os.path.join(outdir, "canary.json"), "w", encoding="utf-8") as f:
        json.dump({"hard_leaks": hits, "count": len(hits)}, f, ensure_ascii=False, indent=2)
    print(f"[arm {args.arm} run {args.run}] done. canary hard leaks: {len(hits)}")
    for h in hits:
        print(f"  LEAK: {h['foreshadow']} canary '{h['canary']}' in ch{h['chapter']} (reveal due ch{h['reveal_chapter']})")


if __name__ == "__main__":
    main()
