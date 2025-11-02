"""
yo.cli — Command-line interface for Yo Brain.
Commands:
    yo add <folder>
    yo ask "<question>"
    yo summarize
"""

import argparse
from yo.brain import YoBrain

def main():
    parser = argparse.ArgumentParser(description="Yo — Your Local Second Brain")
    parser.add_argument("command", choices=["add", "ask", "summarize"])
    parser.add_argument("arg", nargs="?", default=None)
    args = parser.parse_args()

    brain = YoBrain()

    if args.command == "add":
        brain.ingest(args.arg)
    elif args.command == "ask":
        print("💡 Coming soon: interactive Q&A.")
    elif args.command == "summarize":
        print("🧠 Summarizing memory contents... (stub)")

if __name__ == "__main__":
    main()

