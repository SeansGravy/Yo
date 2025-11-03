"""
yo.cli — Unified CLI entrypoint
Supports: add, ask, summarize, ns, cache, verify, compact
"""
import argparse
import subprocess
import os
import datetime
from yo.brain import YoBrain


def run_test():
    """Execute yo_full_test.sh and print summary."""
    script = os.path.join(os.getcwd(), "yo_full_test.sh")
    if not os.path.exists(script):
        print("⚠️  yo_full_test.sh not found. Please recreate it first.")
        return
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile = f"yo_test_results_{ts}.log"
    print(f"🧠 Running full Yo test suite... (logging to {logfile})")
    subprocess.run(["bash", script])
    print(f"\n✅ Verification complete. Check {logfile} for full details.\n")


def main():
    parser = argparse.ArgumentParser(description="Yo — Your Local Second Brain")
    parser.add_argument(
        "command", choices=["add", "ask", "summarize", "ns", "cache", "verify", "compact"]
    )
    parser.add_argument("arg", nargs="?", default=None)
    parser.add_argument("--ns", default="default")
    parser.add_argument("--web", action="store_true")
    args = parser.parse_args()

    brain = YoBrain()

    if args.command == "add":
        brain.ingest(args.arg, namespace=args.ns)

    elif args.command == "ask":
        brain.ask(args.arg, namespace=args.ns, web=args.web)

    elif args.command == "summarize":
        brain.summarize(namespace=args.ns)

    elif args.command == "ns":
        if args.arg == "list":
            brain.ns_list()
        elif args.arg == "delete":
            brain.ns_delete(args.ns)
        else:
            print("Usage:\n  yo ns list\n  yo ns delete --ns <name>")

    elif args.command == "cache":
    elif args.command == "compact":
        brain.compact()
        if args.arg == "list":
            brain._list_cache()
        elif args.arg == "clear":
            brain._clear_cache()
        else:
            print("Usage:\n  yo cache [list|clear]")

    elif args.command == "verify":
        run_test()

    elif args.command == "compact":
        brain.compact()


if __name__ == "__main__":
    main()
