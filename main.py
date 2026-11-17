# main.py
import argparse
import sys

from src import instance_link


def parse_args():
    parser = argparse.ArgumentParser(description="ADT Flutter Tools")
    parser.add_argument("--project", help="složka projektu, který se má otevřít (nabídne přidání, pokud v nástroji není)")
    parser.add_argument(
        "--from-editor", action="store_true",
        help="spuštěno z VS Code: když už nástroj běží, předá mu projekt místo otevření druhého okna",
    )
    # parse_known_args: macOS may append its own arguments to a bundled app
    return parser.parse_known_args()[0]


if __name__ == "__main__":
    """Hlavní vstupní bod aplikace."""
    args = parse_args()
    if args.from_editor and instance_link.forward({"project": args.project}):
        print("--- ADT Flutter Tools už běží, projekt předán otevřenému oknu ---")
        sys.exit(0)

    # Imported only now: forwarding to a running app must not wait for Tkinter.
    from src.ui.app import App

    print(f"--- 1. START: Spouštím main.py (Python verze: {sys.version.split()[0]}) ---")

    app = App(initial_project_path=args.project)
    print("--- 2. Vytvořena instance App() ---")

    app.mainloop()

    print("--- 3. Aplikace ukončena (po mainloop) ---")
