"""Analiza una carpeta en F: vs contenido de D: (nombre+tamaño)."""
import os
import sys
import time

D_ROOT = "D:\\"
SKIP = {"node_modules", ".pnpm", "__MACOSX", "System Volume Information", "$RECYCLE.BIN"}


def should_skip(path: str) -> bool:
    lower = path.lower()
    return any(p.lower() in lower for p in SKIP)


def build_d_index() -> set[str]:
    index: set[str] = set()
    count = 0
    for dirpath, dirnames, filenames in os.walk(D_ROOT):
        dirnames[:] = [d for d in dirnames if not should_skip(os.path.join(dirpath, d))]
        for name in filenames:
            full = os.path.join(dirpath, name)
            if should_skip(full):
                continue
            try:
                index.add(f"{name.lower()}|{os.path.getsize(full)}")
                count += 1
            except OSError:
                pass
    print(f"D index: {count:,} archivos, {len(index):,} claves")
    return index


def analyze_folder(folder: str, d_index: set[str]) -> None:
    total = unique = dup = 0
    files = 0
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not should_skip(os.path.join(dirpath, d))]
        for name in filenames:
            full = os.path.join(dirpath, name)
            if should_skip(full):
                continue
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            files += 1
            total += size
            if f"{name.lower()}|{size}" in d_index:
                dup += size
            else:
                unique += size

    print(f"\nCarpeta: {folder}")
    print(f"  Archivos: {files:,}")
    print(f"  Total:    {total/1024**3:.2f} GB")
    print(f"  Unico vs D: {unique/1024**3:.2f} GB ({unique/total*100 if total else 0:.0f}%)")
    print(f"  Ya en D:  {dup/1024**3:.2f} GB")


if __name__ == "__main__":
    folder = sys.argv[1]
    print("Indexando D:...")
    idx = build_d_index()
    analyze_folder(folder, idx)
