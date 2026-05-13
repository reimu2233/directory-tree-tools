import os
import sys
import time
import shutil
import subprocess
import json
from pathlib import Path
from datetime import datetime
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

import hashlib

OUTPUT_FILENAME = "目录树_详细.txt"
MAX_WORKERS = 32
EXCLUDE_PATTERNS = {
    "目录树.txt", "目录树希望.txt", "目录树_详细.txt",
    "Directory_Tree_Final", "目录树生成结果",
}


def get_cache_path(root: Path) -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
    cache_dir = Path(base) / "目录树缓存"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    key = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"{key}.json"

VIDEO_EXTS = frozenset({
    ".mp4", ".mkv", ".mov", ".avi", ".flv", ".wmv", ".ts", ".m4v",
    ".rmvb", ".webm", ".m2ts", ".mts", ".vob", ".mpg", ".mpeg",
})
AUDIO_EXTS = frozenset({
    ".mp3", ".wav", ".aac", ".flac", ".m4a", ".wma", ".ogg",
    ".ape", ".alac", ".opus", ".amr", ".mka",
})
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS

if os.name == "nt":
    os.system("")
GREEN = "\033[92m"
RED = "\033[91m"
DIM = "\033[90m"
RESET = "\033[0m"
IS_TTY = sys.stdout.isatty()


class DurationEngine:
    def __init__(self):
        self.method = "none"
        self._ffprobe_path: Optional[str] = None
        self._tinytag_cls = None
        fp = shutil.which("ffprobe")
        if fp:
            self._ffprobe_path = fp
            self.method = "ffprobe"
            return
        try:
            from tinytag import TinyTag
            self._tinytag_cls = TinyTag
            self.method = "tinytag"
        except ImportError:
            pass

    def get_duration(self, filepath: str) -> float:
        try:
            if self.method == "ffprobe":
                cmd = [self._ffprobe_path, "-v", "quiet",
                       "-show_entries", "format=duration",
                       "-of", "csv=p=0", filepath]
                r = subprocess.run(
                    cmd, capture_output=True, timeout=30,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                out = r.stdout.strip()
                return float(out) if out else 0.0
            elif self.method == "tinytag":
                try:
                    tag = self._tinytag_cls.get(filepath, tags=False, image=False)
                except TypeError:
                    tag = self._tinytag_cls.get(filepath)
                d = getattr(tag, "duration", None)
                return float(d) if d else 0.0
        except Exception:
            pass
        return 0.0


class TreeNode:
    __slots__ = ("text", "filepath", "ext", "is_media", "is_video", "duration",
                 "_stat_size", "_stat_mtime")

    def __init__(self, text, filepath="", ext="", is_media=False, is_video=False):
        self.text = text
        self.filepath = filepath
        self.ext = ext
        self.is_media = is_media
        self.is_video = is_video
        self.duration = 0.0


def scan_directory(root: Path, script_name: str):
    nodes: List[TreeNode] = []
    ext_counter: Counter = Counter()
    total_files = 0
    warnings: List[str] = []

    def excluded(name: str) -> bool:
        if name == script_name:
            return True
        return any(p in name for p in EXCLUDE_PATTERNS)

    def recurse(current: Path, prefix: str):
        nonlocal total_files
        try:
            entries = list(os.scandir(current))
        except PermissionError:
            warnings.append(f"[权限不足] {current}")
            return
        except OSError as e:
            warnings.append(f"[{e.strerror}] {current}")
            return

        dirs = sorted([e for e in entries if e.is_dir(follow_symlinks=False)],
                      key=lambda e: e.name.lower())
        files = sorted([e for e in entries if not e.is_dir(follow_symlinks=False)],
                       key=lambda e: e.name.lower())
        items = [e for e in dirs + files if not excluded(e.name)]

        for i, entry in enumerate(items):
            is_last = (i == len(items) - 1)
            line = f"{prefix}{'└── ' if is_last else '├── '}{entry.name}"

            if entry.is_dir(follow_symlinks=False):
                nodes.append(TreeNode(line))
                recurse(Path(entry.path), prefix + ("    " if is_last else "│   "))
            else:
                total_files += 1
                ext = Path(entry.name).suffix.lower()
                ext_counter[ext.lstrip(".").upper() or "NO-EXT"] += 1
                is_media = ext in MEDIA_EXTS
                nodes.append(TreeNode(line, entry.path, ext, is_media, ext in VIDEO_EXTS))

    recurse(root, "")
    return nodes, ext_counter, total_files, warnings


def fmt_hms(s: float) -> str:
    s = int(s)
    return f"{s // 3600}小时 {(s % 3600) // 60}分 {s % 60}秒"


def fmt_bracket(s: float) -> str:
    s = int(s)
    return f" [{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}]"


def detect_durations(media_nodes, engine, cache: dict, cache_hits: list):
    if not media_nodes or engine.method == "none":
        return

    todo = []
    stat_map = {}  # filepath -> (size, mtime)
    for n in media_nodes:
        try:
            st = os.stat(n.filepath)
            size, mtime = st.st_size, int(st.st_mtime)
            entry = cache.get(n.filepath)
            if entry and entry.get("size") == size and entry.get("mtime") == mtime:
                n.duration = entry.get("duration", 0.0)
                cache_hits.append(n)
                continue
            stat_map[n.filepath] = (size, mtime)
        except OSError:
            pass
        todo.append(n)

    if not todo:
        return

    total = len(todo)
    done = 0
    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            def probe(n):
                n.duration = engine.get_duration(n.filepath)
                return n
            futures = {pool.submit(probe, n): n for n in todo}
            for f in as_completed(futures):
                done += 1
                n = f.result()
                if n.filepath in stat_map:
                    size, mtime = stat_map[n.filepath]
                    cache[n.filepath] = {"size": size, "mtime": mtime, "duration": n.duration}
                if IS_TTY:
                    print(f"\r{DIM}媒体时长 {done}/{total}（缓存命中 {len(cache_hits)}）{RESET}",
                          end="", flush=True)
        if IS_TTY:
            print(f"\r{' ' * 60}\r", end="", flush=True)
    except KeyboardInterrupt:
        if IS_TTY:
            print()
        raise


def main():
    if len(sys.argv) > 1:
        root = Path(sys.argv[1]).resolve()
    else:
        root = Path(sys.argv[0]).resolve().parent

    script_name = Path(sys.argv[0]).name
    output_path = root / OUTPUT_FILENAME
    cache_path = get_cache_path(root)
    t0 = time.perf_counter()

    cache = {}
    try:
        if cache_path.exists():
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            if not isinstance(cache, dict):
                cache = {}
    except Exception:
        cache = {}
    cache_hits = []

    try:
        nodes, ext_counter, total_files, warnings = scan_directory(root, script_name)
        engine = DurationEngine()
        media_nodes = [n for n in nodes if n.is_media]
        detect_durations(media_nodes, engine, cache, cache_hits)

        # 清理缓存中已不存在的文件
        valid_paths = {n.filepath for n in media_nodes}
        cache = {k: v for k, v in cache.items() if k in valid_paths}
        try:
            cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

        video_sec = sum(n.duration for n in nodes if n.is_video and n.duration > 0)
        audio_sec = sum(n.duration for n in nodes if n.is_media and not n.is_video and n.duration > 0)

        header = [
            "=" * 64,
            f" 生成时间: {datetime.now():%Y-%m-%d %H:%M:%S}   时长引擎: {engine.method}",
            f" 文件总数: {total_files}   视频总时长: {fmt_hms(video_sec)}   音频总时长: {fmt_hms(audio_sec)}",
            "-" * 64,
            " [文件类型]",
        ]
        for ext, count in ext_counter.most_common():
            header.append(f"   .{ext:<6} : {count}")
        if warnings:
            header.append("-" * 64)
            header.append(f" [跳过 {len(warnings)} 个目录]")
            for w in warnings[:50]:
                header.append(f"   {w}")
            if len(warnings) > 50:
                header.append(f"   ... 另有 {len(warnings) - 50} 条")
        header += ["=" * 64, ""]

        tree_lines = [f"{root.name}（{root}）"]
        for n in nodes:
            tree_lines.append(n.text + fmt_bracket(n.duration) if n.is_media and n.duration > 0 else n.text)

        output_path.write_text("\n".join(header + tree_lines), encoding="utf-8-sig")

        elapsed = time.perf_counter() - t0
        cache_info = f"  缓存命中 {len(cache_hits)}/{len(media_nodes)}" if media_nodes else ""
        msg = f"成功 {elapsed:.2f}s  {total_files} 文件  引擎:{engine.method}{cache_info}  →  {output_path}"
        print(f"{GREEN}{msg}{RESET}")
        if warnings:
            print(f"{RED}{len(warnings)} 个目录被跳过{RESET}")

    except Exception as e:
        print(f"{RED}失败: {type(e).__name__}: {e}{RESET}")

    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    main()
