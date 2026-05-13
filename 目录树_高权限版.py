import os
import sys
import ctypes
import time
from pathlib import Path
from datetime import datetime
from typing import List, Tuple

OUTPUT_FILENAME = "目录树.txt"
# 扫描目标在 C 盘时，结果直接落到 E 盘根目录
CROSS_DRIVE_OUTPUT_DIR = Path(r"E:\\")
EXCLUDE_PATTERNS = {"目录树.txt", "目录树希望.txt", "目录树生成结果", "Directory_Tree_Final"}

if os.name == "nt":
    os.system("")
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


# ---------- UAC 自动提权 ----------
def is_admin() -> bool:
    if os.name != "nt":
        return True
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def elevate_if_needed() -> None:
    """若未以管理员运行，则触发 UAC 重启自身；用户取消则以普通权限继续。"""
    if os.name != "nt" or is_admin():
        return
    script = os.path.abspath(sys.argv[0])
    extra = " ".join(f'"{a}"' for a in sys.argv[1:])
    params = f'"{script}"' + ((" " + extra) if extra else "")
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, None, 1
    )
    # ShellExecuteW 成功时返回值 > 32；<= 32 通常代表用户取消或失败
    if ret <= 32:
        print(f"{YELLOW}提权被取消或失败（code={ret}），以当前权限继续运行{RESET}")
        return
    sys.exit(0)


# ---------- 扫描逻辑 ----------
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
            key=lambda e: e.name.lower(),
        )
        files = sorted(
            [e for e in entries if not e.is_dir(follow_symlinks=False)],
            key=lambda e: e.name.lower(),
        )
        items = [e for e in dirs + files if not should_exclude(e.name, script_name)]

        for i, entry in enumerate(items):
            is_last = i == len(items) - 1
            connector = "└── " if is_last else "├── "
            tree_lines.append(f"{prefix}{connector}{entry.name}")
            if entry.is_dir(follow_symlinks=False):
                extension = "    " if is_last else "│   "
                _recurse(Path(entry.path), prefix + extension)

    _recurse(dir_path, "")
    return tree_lines, warnings


# ---------- 输出路径决策 ----------
def resolve_output_path(root: Path) -> Path:
    """扫描目标在 C 盘 → 写到 E 盘根目录；其它情况沿用原地写。E 盘不可用则回退。"""
    drive = root.drive.upper()  # 'C:' / 'D:' / 'E:' 等
    if drive == "C:":
        try:
            CROSS_DRIVE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe = (root.name or "C盘根").replace(" ", "_")
            return CROSS_DRIVE_OUTPUT_DIR / f"目录树_{safe}_{ts}.txt"
        except OSError as e:
            print(f"{YELLOW}E 盘不可用（{e}），回退到扫描目录写入{RESET}")
    return root / OUTPUT_FILENAME


# ---------- 入口 ----------
def main():
    elevate_if_needed()  # 先申请管理员权限

    if len(sys.argv) > 1:
        root = Path(sys.argv[1]).resolve()
    else:
        root = Path(sys.argv[0]).resolve().parent

    script_name = Path(sys.argv[0]).name
    output_path = resolve_output_path(root)

    if is_admin():
        print(f"{GREEN}[管理员]{RESET} 扫描：{root}")
    else:
        print(f"{YELLOW}[普通权限]{RESET} 扫描：{root}")

    t0 = time.perf_counter()
    try:
        tree_lines, warnings = scan_directory(root, script_name)
        header = f"{root.name}（{root}）"
        result = [header]
        result.extend(tree_lines if tree_lines else ["未扫描到任何文件。"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
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
