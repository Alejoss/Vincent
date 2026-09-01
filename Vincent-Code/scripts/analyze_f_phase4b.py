"""Analiza duplicados internos en Backup Lacie (fase 4b)."""
import csv
import sys
from collections import Counter, defaultdict

BACKUP = "F:\\Backup Lacie HardDrive"
ALEJANDRO = "F:\\Alejandro Data"


def top_subfolder(path: str) -> str:
    parts = path.split("\\")
    return "\\".join(parts[:3]) if len(parts) >= 3 else path


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else r"E:\duplicados-disco-F.csv"
    groups: dict[str, list[dict]] = defaultdict(list)
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            groups[row["Clave"]].append(row)

    pure_backup: list[tuple[int, list[dict]]] = []
    for clave, rows in groups.items():
        if len(rows) < 2:
            continue
        paths = [r["FullName"] for r in rows]
        in_backup = [p for p in paths if p.lower().startswith(BACKUP.lower())]
        in_alejandro = [p for p in paths if p.lower().startswith(ALEJANDRO.lower())]
        if len(in_backup) >= 2 and len(in_alejandro) == 0:
            rec = (len(rows) - 1) * int(rows[0]["Length"])
            pure_backup.append((rec, rows))

    total = sum(x[0] for x in pure_backup)
    print("=== Fase 4b: duplicados SOLO dentro de Backup Lacie ===")
    print(f"Grupos: {len(pure_backup):,}")
    print(f"GB recuperables (dejando 1 copia/grupo): {total / 1024**3:.2f}")
    print()

    sub_bytes: Counter[str] = Counter()
    for rec, rows in pure_backup:
        for r in rows:
            p = r["FullName"]
            if p.lower().startswith(BACKUP.lower()):
                sub_bytes[top_subfolder(p)] += rec / len(rows)

    print("Subcarpetas de Backup mas afectadas:")
    for k, v in sub_bytes.most_common(15):
        print(f"  {v / 1024**3:7.2f} GB  {k}")
    print()

    ext: Counter[str] = Counter()
    for rec, rows in pure_backup:
        name = rows[0]["Name"]
        e = name.rsplit(".", 1)[-1].lower() if "." in name else "(sin ext)"
        ext[e] += rec
    print("Tipos de archivo (GB recuperables):")
    for e, b in ext.most_common(12):
        print(f"  .{e}: {b / 1024**3:.1f} GB")
    print()

    print("Top 10 ejemplos:")
    for rec, rows in sorted(pure_backup, key=lambda x: -x[0])[:10]:
        name = rows[0]["Name"]
        print(f"  {rec / 1024**3:.2f} GB | {len(rows)} copias | {name}")
        for r in rows[:4]:
            print(f"    - {r['FullName']}")
        if len(rows) > 4:
            print(f"    ... +{len(rows) - 4} mas")
        print()


if __name__ == "__main__":
    main()
