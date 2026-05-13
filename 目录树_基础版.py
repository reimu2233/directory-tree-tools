import os
import sys
import time
from pathlib import Path
from typing import List, Tuple

OUTPUT_FILENAME = "目录树.txt"
EXCLUDE_PATTERNS = {"目录树.txt", "目录树希望.txt", "目录树生成结果", "Directory_Tree_Final"}

if os.name == "nt":
    os.system("")
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"

def should_exclude(name: str, script_name: str) -> bool:
    if name == script_name:
        return True
    return any(p in name for p in EXCLUDE_PATTERNS)

def scan_directory(dir_path: Path, script_name: str) -> Tuple[List[str], List[str]]:
    tree_lines: List[str] = []
    warnings: List[str] = []

    def _recurse(current: Path, prefix: str):
        try:
            entries = list(os.scandir(current))
        except PermissionError:
            warnings.append(f"[权限不足] {current}")
            return
        except OSError as e:
            warnings.append(f"[{e.strerror}] {current}")
            return

        dirs = sorted(
            [e for e in entries if e.is_dir(follow_symlinks=False)],
            key=lambda e: e.name.lower()
        )
        files = sorted(
            [e for e in entries if not e.is_dir(follow_symlinks=False)],
            key=lambda e: e.name.lower()
        )
        items = [e for e in dirs + files if not should_exclude(e.name, script_name)]

        for i, entry in enumerate(items):
            is_last = (i == len(items) - 1)
            connector = "└── " if is_last else "├── "
            tree_lines.append(f"{prefix}{connector}{entry.name}")

            if entry.is_dir(follow_symlinks=False):
                extension = "    " if is_last else "│   "
                _recurse(Path(entry.path), prefix + extension)

    _recurse(dir_path, "")
    return tree_lines, warnings

def main():
    if len(sys.argv) > 1:
        root = Path(sys.argv[1]).resolve()
    else:
        root = Path(sys.argv[0]).resolve().parent

    script_name = Path(sys.argv[0]).name
    output_path = root / OUTPUT_FILENAME

    t0 = time.perf_counter()
    try:
        tree_lines, warnings = scan_directory(root, script_name)
        header = f"{root.name}（{root}）"
        result = [header]
        result.extend(tree_lines if tree_lines else ["未扫描到任何文件。"])
        output_path.write_text("\n".join(result), encoding="utf-8-sig")
        elapsed = time.perf_counter() - t0
        print(f"{GREEN}成功 {elapsed:.2f}s  {len(tree_lines)} 条  →  {output_path}{RESET}")
        if warnings:
            print(f"{RED}{len(warnings)} 个目录被跳过{RESET}")
    except Exception as e:
        print(f"{RED}失败: {e}{RESET}")

    input()

if __name__ == "__main__":
    main()
