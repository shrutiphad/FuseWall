"""Explicit cloud migration/check/export/restore. Reads secrets only from environment."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fusewall.cloud import store_from_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["migrate", "check", "export", "restore", "recover"])
    parser.add_argument("--file", type=Path)
    args = parser.parse_args()
    store = store_from_environment()
    if args.command == "migrate":
        store.migrate()
        store.assert_ready()
        result = {"migrated": True, "schema": store.schema, "version": 1}
    elif args.command == "check":
        store.assert_ready()
        result = store.integrity()
        if not result["ok"]:
            print(json.dumps(result))
            return 1
    elif args.command == "recover":
        result = store.recover()
    elif args.command == "export":
        if args.file is None:
            parser.error("export requires --file pointing to a new private backup file")
        with args.file.open("x", encoding="utf8") as handle:
            json.dump(store.export_snapshot(), handle)
        args.file.chmod(0o600)
        result = {"exported": True, "file": str(args.file)}
    else:
        if args.file is None:
            parser.error("restore requires --file and a newly migrated empty destination schema")
        result = store.restore_snapshot(json.loads(args.file.read_text(encoding="utf8")))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
