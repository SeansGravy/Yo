"""
yo.cli — now supports `yo ask "question"`
"""
import argparse
from yo.brain import YoBrain

def main():
    parser = argparse.ArgumentParser(description="Yo — Your Local Second Brain")
    parser.add_argument("command", choices=["add", "ask", "summarize"])
    parser.add_argument("arg", nargs="?", default=None, help="Path or question")
    parser.add_argument("--ns", default="default", help="Namespace (collection name)")
    args = parser.parse_args()

    brain = YoBrain()

    if args.command == "add":
        brain.ingest(args.arg, namespace=args.ns)
    elif args.command == "ask":
        brain.ask(args.arg, namespace=args.ns)
    elif args.command == "summarize":
        print("🧠 Summarization placeholder — coming soon!")

if __name__ == "__main__":
    main()
