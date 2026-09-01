"""Carpetas en F: cuyo contenido no aparece en D: (por clave nombre+tamaño)."""
import csv
import sys
from collections import Counter, defaultdict

D_CSV = r"D:\duplicados-disco-D.csv"
F_CSV = r"E:\duplicados-disco-F.csv"


def load_keys(path: str) -> tuple[set[str], dict[str, list[str]]]:
    keys: set[str] = set()
    paths: dict[str, list[str]] = defaultdict(list)
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            keys.add(row["Clave"])
            paths[row["Clave"]].append(row["FullName"])
    return keys, paths


def top_folder(path: str, depth: int = 3) -> str:
    parts = path.split("\\")
    return "\\".join(parts[:depth]) if len(parts) >= depth else path


def main() -> None:
    d_keys, d_paths = load_keys(D_CSV)
    f_keys, f_paths = load_keys(F_CSV)

    # All F paths indexed by clave (from full F scan entries in CSV - only dup groups!)
    # Note: CSV only has duplicate groups, not all files. Need filesystem scan for accurate unique GB.

    common = d_keys & f_keys
    only_f_keys = f_keys - d_keys

    print("=== Desde CSV de duplicados (solo grupos duplicados) ===")
    print(f"Claves compartidas D+F: {len(common):,}")
    print(f"Claves solo en grupos F (no en CSV D): {len(only_f_keys):,}")
    print()

    folder_gb: Counter[str] = Counter()
    for k in only_f_keys:
        sz = int(f_paths[k][0].split("|")[-1]) if False else 0
        # get length from first path - parse clave
        length = int(k.split("|")[-1])
        for p in f_paths[k]:
            if p.upper().startswith("F:\\"):
                folder_gb[top_folder(p)] += length
                break

    print("En grupos duplicados de F, carpetas con claves no listadas en D:")
    for name, gb in folder_gb.most_common(15):
        print(f"  {gb/1024**3:7.1f} GB  {name}")


if __name__ == "__main__":
    main()
