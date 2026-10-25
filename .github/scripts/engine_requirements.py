"""Writes the packages Snapper installs for each optional engine (from app/snapper/engine.py) as requirements files, so the
security workflow audits exactly what a user gets. Reads engine.py as text (it needs PySide6 to import, which the audit does not).
usage: engine_requirements.py OUT_DIR   ->  OUT_DIR/<engine>.txt (installed with dependencies) and OUT_DIR/<engine>-nodeps.txt (installed with
--no-deps: resolving them would need packages Snapper deliberately leaves out), for whisperx and separator"""
import ast
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "app" / "snapper" / "engine.py"


def value(node, names):
    """A list of strings written as a literal, a module-level name, or a sum of those."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        return [value(e, names) for e in node.elts]
    if isinstance(node, ast.Name):
        return names[node.id]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return value(node.left, names) + value(node.right, names)
    raise ValueError(f"cannot read {ast.dump(node)[:80]}")


def main(out: Path):
    names, engines = {}, {}
    for node in ast.parse(SOURCE.read_text()).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
            if isinstance(node.value, ast.Call) and getattr(node.value.func, "id", "") == "Engine":
                kw = {k.arg: k.value for k in node.value.keywords}
                engines[value(kw["key"], names)] = (
                    value(kw["gpu_packages"], names) + value(kw["cpu_packages"], names),
                    value(kw["no_deps_packages"], names) if "no_deps_packages" in kw else [])
            else:
                try:
                    names[target] = value(node.value, names)
                except (ValueError, KeyError):
                    pass
    if set(engines) != {"whisperx", "separator"} or not all(p for p, _ in engines.values()):
        sys.exit(f"found engines {sorted(engines)} in {SOURCE}: expected whisperx and separator with packages")
    out.mkdir(parents=True, exist_ok=True)
    for key, (packages, nodeps) in engines.items():
        unique = list(dict.fromkeys(p for p in packages if "onnxruntime-gpu" not in p))   # the CPU wheels stand in for the CUDA builds
        (out / f"{key}.txt").write_text("\n".join(unique) + "\n")
        (out / f"{key}-nodeps.txt").write_text("\n".join(nodeps) + ("\n" if nodeps else ""))
        print(f"{key}: {len(unique)} requirements, {len(nodeps)} without dependencies")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
