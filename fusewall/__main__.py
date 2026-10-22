import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Fusewall local gateway — no paid upstreams")
    parser.add_argument("command", choices=["serve", "token", "check", "backup"], nargs="?", default="serve")
    parser.add_argument("--data-dir", default=".fusewall")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", choices=["127.0.0.1", "0.0.0.0"], default="127.0.0.1", help="Use 0.0.0.0 only inside an explicitly loopback-published container")
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn
        from .app import create_app
        print(f"Fusewall: http://127.0.0.1:{args.port} — simulation only")
        print("Unlock token: run 'python -m fusewall token' in another terminal.")
        uvicorn.run(create_app(args.data_dir), host=args.host, port=args.port, workers=1, access_log=False)
    else:
        from .store import Store
        store = Store(args.data_dir)
        if args.command == "token":
            print(store.admin_path.read_text(encoding="utf8").strip())
        elif args.command == "check":
            result = store.integrity()
            print(json.dumps(result, indent=2))
            raise SystemExit(0 if result["ok"] else 1)
        else:
            print(store.backup())


if __name__ == "__main__":
    main()
