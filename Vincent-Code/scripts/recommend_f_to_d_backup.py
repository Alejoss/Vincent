"""Encuentra carpetas top-level en F: con contenido que NO existe en D: (nombre+tamaño)."""
import os
import sys
import time
from collections import defaultdict

D_ROOT = "D:\\"
F_ROOT = "F:\\"

SKIP_PARTS = {"node_modules", ".pnpm", "__MACOSX", "System Volume Information", "$RECYCLE.BIN"}


def should_skip(path: str) -> bool:
    lower = path.lower()
    return any(p.lower() in lower for p in SKIP_PARTS)


def build_index(root: str) -> set[str]:
    index: set[str] = set()
    count = 0
    t0 = time.time()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not should_skip(os.path.join(dirpath, d))]
        for name in filenames:
            full = os.path.join(dirpath, name)
            if should_skip(full):
                continue
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            index.add(f"{name.lower()}|{size}")
            count += 1
            if count % 50000 == 0:
                print(f"  D index: {count:,} archivos ({time.time()-t0:.0f}s)...")
    print(f"D index listo: {count:,} archivos, {len(index):,} claves")
    return index


def analyze_f_folder(folder_path: str, d_index: set[str]) -> dict:
    total_bytes = 0
    unique_bytes = 0
    duplicate_bytes = 0
    total_files = 0
    unique_files = 0

    for dirpath, dirnames, filenames in os.walk(folder_path):
        dirnames[:] = [d for d in dirnames if not should_skip(os.path.join(dirpath, d))]
        for name in filenames:
            full = os.path.join(dirpath, name)
            if should_skip(full):
                continue
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            total_files += 1
            total_bytes += size
            clave = f"{name.lower()}|{size}"
            if clave in d_index:
                duplicate_bytes += size
            else:
                unique_bytes += size
                unique_files += 1

    return {
        "total_gb": total_bytes / 1024**3,
        "unique_gb": unique_bytes / 1024**3,
        "dup_gb": duplicate_bytes / 1024**3,
        "total_files": total_files,
        "unique_files": unique_files,
        "pct_unique": (unique_bytes / total_bytes * 100) if total_bytes else 0,
    }


def main() -> None:
    budget_gb = float(sys.argv[1]) if len(sys.argv) > 1 else 500.0

    print("Indexando D: (puede tardar varios minutos)...")
    d_index = build_index(D_ROOT)

    print("\nAnalizando carpetas top-level en F:...")
    results = []
    for name in sorted(os.listdir(F_ROOT)):
        path = os.path.join(F_ROOT, name)
        if not os.path.isdir(path):
            continue
        if name in SKIP_PARTS or name.startswith("."):
            continue
        print(f"  Escaneando F:\\{name}...")
        stats = analyze_f_folder(path, d_index)
        stats["name"] = name
        stats["path"] = path
        results.append(stats)

    results.sort(key=lambda x: -x["unique_gb"])

    print(f"\n=== Carpetas F: por contenido UNICO vs D: (presupuesto ~{budget_gb:.0f} GB) ===")
    print(f"{'Carpeta':<30} {'Total GB':>9} {'Unico GB':>9} {'Dup GB':>9} {'%Unico':>7}")
    print("-" * 70)
    for r in results:
        print(
            f"{r['name']:<30} {r['total_gb']:9.1f} {r['unique_gb']:9.1f} "
            f"{r['dup_gb']:9.1f} {r['pct_unique']:6.0f}%"
        )

    print("\n=== Recomendacion: carpetas enteras sin duplicar D: ===")
    cumulative = 0.0
    picks = []
    for r in results:
        if r["unique_gb"] < 1:
            continue
        if r["pct_unique"] < 50 and r["dup_gb"] > 20:
            note = "MUCHA solapamiento con D:"
        elif r["pct_unique"] >= 80:
            note = "Buena candidata"
        elif r["unique_gb"] >= r["dup_gb"]:
            note = "Aceptable"
        else:
            note = "Revisar (muchos duplicados)"
        if r["total_gb"] > budget_gb * 1.5:
            note += " | NO cabe entera"

        fits = cumulative + r["unique_gb"] <= budget_gb
        if r["pct_unique"] >= 70 or (r["unique_gb"] > 10 and r["unique_gb"] >= r["dup_gb"]):
            picks.append((r, note, fits))
            if fits:
                cumulative += r["unique_gb"]

    for r, note, fits in picks[:12]:
        mark = "[CABE]" if fits and cumulative <= budget_gb else "[---]"
        print(f"  {mark} F:\\{r['name']}  ->  {r['unique_gb']:.1f} GB unicos  ({note})")

    print(f"\nSuma unica de candidatas marcadas CABE: ~{cumulative:.0f} GB")


if __name__ == "__main__":
    main()
