#!/bin/bash
# =====================================================
# Restore top-level "cache" CLI commands for Yo
# =====================================================

echo "🔧 Restoring cache commands to Yo CLI..."

cat > yo/cli.py <<'EOF'
"""
yo.cli — unified CLI with cache + ns support
"""
import argparse
from yo.brain import YoBrain

def main():
    parser = argparse.ArgumentParser(description="Yo — Your Local Second Brain")
    parser.add_argument("command", choices=["add","ask","summarize","ns","cache"])
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
        if args.arg == "list":
            brain._list_cache()
        elif args.arg == "clear":
            brain._clear_cache()
        else:
            print("Usage:\n  yo cache [list|clear]")

if __name__ == "__main__":
    main()
EOF

echo "✅ Cache commands restored."
echo "Try:"
echo "  python3 -m yo.cli cache list"
echo "  python3 -m yo.cli cache clear"
