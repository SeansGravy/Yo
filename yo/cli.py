"""
yo.cli — Adds cache list/clear commands
"""
import argparse
from yo.brain import YoBrain

def main():
    parser = argparse.ArgumentParser(description="Yo — Your Local Second Brain")
    parser.add_argument("command", choices=["add", "ask", "summarize", "cache"])
    parser.add_argument("arg", nargs="?", default=None, help="Path, question, or cache action")
    parser.add_argument("--ns", default="default", help="Namespace (collection name)")
    parser.add_argument("--web", action="store_true", help="Use live web context")
    args = parser.parse_args()

    brain = YoBrain()

    if args.command == "add":
        brain.ingest(args.arg, namespace=args.ns)
    elif args.command == "ask":
        brain.ask(args.arg, namespace=args.ns, web=args.web)
    elif args.command == "summarize":
        brain.summarize(namespace=args.ns)
    elif args.command == "cache":
        if args.arg == "list":
            brain._list_cache()
        elif args.arg == "clear":
            brain._clear_cache()
        else:
            print("Usage: yo cache [list|clear]")

if __name__ == "__main__":
    main()
