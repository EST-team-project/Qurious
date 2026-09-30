"""Read-only AST/static inventory; lecture repositories are never modified."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen


def endpoints(folder):
    result = []
    for path in folder.rglob("*.py"):
        if any(x in path.parts for x in ("venv", ".venv", "__pycache__")):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        prefixes = {"app": "", "router": ""}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                if getattr(node.value.func, "id", "") == "APIRouter":
                    for keyword in node.value.keywords:
                        if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant):
                            prefixes[node.targets[0].id] = keyword.value.value
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.args:
                    verb = dec.func.attr.upper()
                    if verb in {"GET", "POST", "PUT", "PATCH", "DELETE"} and isinstance(dec.args[0], ast.Constant):
                        url = prefixes.get(getattr(dec.func.value, "id", ""), "") + dec.args[0].value
                        if url.startswith(("/api/", "/auth", "/chat", "/ingest", "/market", "/backtest")):
                            result.append({"method": verb, "path": url, "source": str(path.relative_to(folder))})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--investment", type=Path, required=True)
    parser.add_argument("--domain", type=Path, required=True)
    parser.add_argument("--base", default="http://localhost")
    args = parser.parse_args()
    with urlopen(args.base + "/openapi.json", timeout=30) as response:
        live = json.load(response)["paths"]
    routes = endpoints(args.investment / "app/backend") + endpoints(args.domain / "app/api/routes")
    for route in routes:
        route["present"] = route["method"].lower() in live.get(route["path"], {})
    assets = []
    for source in sorted((args.investment / "app/frontend").rglob("*")):
        if source.is_file():
            relative = source.relative_to(args.investment / "app/frontend")
            target = Path("frontend/analysis") / relative
            assets.append({"path": relative.as_posix(), "present": target.is_file(),
                "unchanged": target.is_file() and hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(target.read_bytes()).digest()})
    print(json.dumps({"api_count": len(routes), "missing_api": [r for r in routes if not r["present"]],
        "asset_count": len(assets), "missing_assets": [a for a in assets if not a["present"]],
        "routes": routes, "assets": assets}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
