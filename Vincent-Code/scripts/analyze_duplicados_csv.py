import csv
import sys
from collections import defaultdict
from pathlib import Path


def analyze(path: str) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            groups[row["Clave"]].append(row)

    num_groups = len(groups)
    num_files = sum(len(v) for v in groups.values())
    recoverable = sum(
        (len(v) - 1) * int(v[0]["Length"])
        for v in groups.values()
        if len(v) > 1
    )

    top = sorted(
        (
            (
                k,
                len(v),
                int(v[0]["Length"]),
                (len(v) - 1) * int(v[0]["Length"]),
                v[0]["Name"],
                v[0]["FullName"],
            )
            for k, v in groups.items()
            if len(v) > 1
        ),
        key=lambda x: x[3],
        reverse=True,
    )[:15]

    ext_bytes: dict[str, int] = defaultdict(int)
    ext_files: dict[str, int] = defaultdict(int)
    for v in groups.values():
        if len(v) <= 1:
            continue
        name = v[0]["Name"]
        ext = Path(name).suffix.lower() or "(sin extension)"
        ext_bytes[ext] += (len(v) - 1) * int(v[0]["Length"])
        ext_files[ext] += len(v)

    top_ext = sorted(ext_bytes.items(), key=lambda x: x[1], reverse=True)[:12]

    roots: dict[str, int] = defaultdict(int)
    for v in groups.values():
        for row in v:
            p = row["FullName"]
            if len(p) >= 3 and p[1] == ":":
                roots[p[:2].upper()] += 1

    noise_names = {".ds_store", "._.ds_store", "thumbs.db", "desktop.ini"}
    noise_groups = sum(1 for v in groups.values() if len(v) > 1 and v[0]["Name"].lower() in noise_names)
    noise_files = sum(len(v) for v in groups.values() if len(v) > 1 and v[0]["Name"].lower() in noise_names)

    return {
        "path": path,
        "groups": num_groups,
        "files": num_files,
        "recoverable_gb": recoverable / 1024**3,
        "top": top,
        "top_ext": top_ext,
        "ext_files": ext_files,
        "roots": dict(sorted(roots.items(), key=lambda x: -x[1])),
        "noise_groups": noise_groups,
        "noise_files": noise_files,
    }


def main() -> None:
    paths = sys.argv[1:] or [r"D:\duplicados-disco-D.csv", r"F:\duplicados-disco-F.csv"]
    total_groups = 0
    total_files = 0
    total_gb = 0.0

    for path in paths:
        r = analyze(path)
        total_groups += r["groups"]
        total_files += r["files"]
        total_gb += r["recoverable_gb"]

        print(f"=== {path} ===")
        print(f"Grupos duplicados: {r['groups']:,}")
        print(f"Archivos en esos grupos: {r['files']:,}")
        print(f"GB recuperables (dejando 1 copia/grupo): {r['recoverable_gb']:.2f}")
        print(f"Ruido de sistema (.DS_Store, Thumbs.db, etc.): {r['noise_groups']:,} grupos, {r['noise_files']:,} archivos")
        print("Raices de ruta en el CSV:")
        for root, count in r["roots"].items():
            print(f"  {root}: {count:,} entradas")
        print("Top extensiones por GB recuperable:")
        for ext, b in r["top_ext"]:
            print(f"  {ext}: {b / 1024**3:.2f} GB ({r['ext_files'][ext]:,} archivos)")
        print("Top 10 grupos por espacio recuperable:")
        for _, cnt, size, rec, name, sample in r["top"][:10]:
            print(f"  {name} | {cnt} copias | {size / 1024**2:.1f} MB c/u | {rec / 1024**3:.2f} GB")
            print(f"    ejemplo: {sample}")
        print()

    print("=== TOTAL COMBINADO (sin deduplicar entre discos) ===")
    print(f"Grupos: {total_groups:,}")
    print(f"Archivos: {total_files:,}")
    print(f"GB recuperables: {total_gb:.2f}")


if __name__ == "__main__":
    main()
