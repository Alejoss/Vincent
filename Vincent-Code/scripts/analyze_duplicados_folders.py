"""Analiza duplicados por carpeta para planificar limpieza."""
import csv
import os
import sys
from collections import defaultdict


def analyze(path: str) -> None:
    groups: dict[str, list[dict]] = defaultdict(list)
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            groups[row["Clave"]].append(row)

    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
    recoverable = sum((len(v) - 1) * int(v[0]["Length"]) for v in dup_groups.values())
    total_files = sum(len(v) for v in dup_groups.values())

    def top_folders(depth: int) -> dict[str, float]:
        folder_bytes: dict[str, float] = defaultdict(float)
        for v in dup_groups.values():
            rec = (len(v) - 1) * int(v[0]["Length"])
            per = rec / len(v)
            for row in v:
                parts = row["FullName"].split("\\")
                if len(parts) >= depth:
                    key = "\\".join(parts[:depth])
                    folder_bytes[key] += per
        return folder_bytes

    ext_bytes: dict[str, int] = defaultdict(int)
    ext_files: dict[str, int] = defaultdict(int)
    for v in dup_groups.values():
        rec = (len(v) - 1) * int(v[0]["Length"])
        name = v[0]["Name"]
        ext = os.path.splitext(name)[1].lower() or "(sin ext)"
        ext_bytes[ext] += rec
        ext_files[ext] += len(v)

    node_files = sum(
        len(v)
        for v in dup_groups.values()
        if any(
            "node_modules" in r["FullName"].lower() or ".pnpm" in r["FullName"].lower()
            for r in v
        )
    )

    print(f"Archivo: {path}")
    print(f"Total GB recuperables: {recoverable / 1024**3:.2f}")
    print(f"Grupos: {len(dup_groups):,} | Archivos: {total_files:,}")
    print(f"Archivos en node_modules/.pnpm: {node_files:,} ({node_files / total_files * 100:.0f}%)")
    print()
    print("=== Top extensiones (GB) ===")
    for ext, b in sorted(ext_bytes.items(), key=lambda x: -x[1])[:12]:
        print(f"{b / 1024**3:7.2f} GB  {ext:12} ({ext_files[ext]:,} archivos)")
    print()
    print("=== Top carpetas raiz (GB atribuidos) ===")
    for k, v in sorted(top_folders(2).items(), key=lambda x: -x[1])[:15]:
        print(f"{v / 1024**3:8.2f} GB  {k}")
    print()
    print("=== Top subcarpetas (GB) ===")
    for k, v in sorted(top_folders(3).items(), key=lambda x: -x[1])[:20]:
        print(f"{v / 1024**3:8.2f} GB  {k}")
    print()
    print("=== Top 10 grupos por espacio ===")
    top = sorted(
        (
            (len(v) - 1) * int(v[0]["Length"]),
            v[0]["Name"],
            len(v),
            [r["FullName"] for r in v],
        )
        for v in dup_groups.values()
    )
    for rec, name, cnt, paths in reversed(top[-10:]):
        print(f"{rec / 1024**3:.2f} GB | {cnt} copias | {name}")
        for p in paths[:4]:
            print(f"  - {p}")
        if len(paths) > 4:
            print(f"  ... +{len(paths) - 4} mas")


if __name__ == "__main__":
    analyze(sys.argv[1] if len(sys.argv) > 1 else r"E:\duplicados-disco-E.csv")
