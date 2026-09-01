# Pipeline: Own_Transcripts → extracción de conocimiento

Transforma transcripts propios en activos intelectuales estructurados para newsletters y posts.

Complementa el pipeline de transcripción (`process_local_videos.py`, `process_youtube_channel.py`). Lee lo que ya está en `10_Sources/Own_Transcripts/` y escribe en `20_Extractions/Own_Transcripts/`.

---

## Resumen rápido

| Qué | Dónde |
|-----|--------|
| Script principal | `scripts/extract_own_transcript_knowledge.py` |
| Atajo Windows | `scripts/run_knowledge_extraction.bat` |
| Input Obsidian | `Cerebro-Vincent/10_Sources/Own_Transcripts/` |
| Output Obsidian | `Cerebro-Vincent/20_Extractions/Own_Transcripts/{stem}-knowledge.md` |
| JSON cache | `Vincent-Code/cache/knowledge_extractions/json/{stem}.json` |
| Fuente de verdad (estado) | `cache/knowledge_extractions/state.sqlite3` |
| Export legible (vault) | `_estado_extracciones.json`, `_estado_extracciones.md` |
| Log última ejecución | `logs/knowledge_extraction_latest.log` |

---

## Comando diario

Desde PowerShell o CMD, con el `.env` ya configurado:

```powershell
cd E:\Vincent\Vincent-Code
.\scripts\run_knowledge_extraction.bat
```

Equivalente explícito:

```powershell
cd E:\Vincent\Vincent-Code
$env:PYTHONIOENCODING='utf-8'
.\venv\Scripts\python.exe scripts\extract_own_transcript_knowledge.py
```

### Variantes útiles

```powershell
# Ver cola sin llamar al LLM
.\scripts\run_knowledge_extraction.bat --dry-run

# Procesar solo 3 pendientes
.\scripts\run_knowledge_extraction.bat --limit 3

# Un solo video por stem del archivo
.\scripts\run_knowledge_extraction.bat --id 2026-02-25-qué-es-paragon-solutions-y-qué-tiene-que-ver-con-epstein

# Reintentar fallidos
.\scripts\run_knowledge_extraction.bat --retry-failed

# Re-extraer aunque ya esté done
.\scripts\run_knowledge_extraction.bat --reprocess

# Solo regenerar estado en el vault
.\scripts\run_knowledge_extraction.bat --export-status
```

---

## Rutina recomendada

| Orden | Pipeline | Comando |
|-------|----------|---------|
| 1 | Transcripciones (YouTube o local) | `run_youtube_channel_transcripts.bat` o `run_local_videos_transcripts.bat` |
| 2 | Extracción de conocimiento | `run_knowledge_extraction.bat` |

---

## Variables de entorno

| Variable | Uso |
|----------|-----|
| `OBSIDIAN_VAULT_PATH` | Ruta al vault (default: `../Cerebro-Vincent`) |
| `LLM_PROVIDER` | `openai`, `groq`, `ollama` o `auto` |
| `LLM_MODEL` | Modelo (default según proveedor) |
| `OPENAI_API_KEY` | Requerido si `LLM_PROVIDER=openai` |
| `KNOWLEDGE_TRANSCRIPT_FOLDER` | Subcarpeta bajo `10_Sources` (default: `Own_Transcripts`) |
| `KNOWLEDGE_EXTRACTION_FOLDER` | Subcarpeta bajo `20_Extractions` (default: `Own_Transcripts`) |

Para extracción estructurada se recomienda un modelo capaz (`gpt-4o` o similar). `gpt-4o-mini` funciona pero puede perder matices en videos largos.

---

## Salida

Cada transcript genera:

1. **Markdown en Obsidian** (`-knowledge.md`) con secciones legibles: Summary, Theses, Arguments, Content Angles, Quotes, etc.
2. **JSON en cache** con el mismo contenido estructurado + `meta` (modelo, fecha, formato detectado).

El transcript fuente se enlaza con:

```yaml
source_transcript: "[[10_Sources/Own_Transcripts/{stem}]]"
```

---

## Estado y re-proceso

- SQLite es la fuente de verdad.
- `_estado_extracciones.json` en el vault es un export derivado (no editar a mano).
- Si cambia el body del transcript (hash distinto), una fila `done` vuelve a `pending`.
- Si falta el archivo `-knowledge.md`, `done` vuelve a `pending`.

---

## Archivos de código

- `src/knowledge_extraction_state.py` — SQLite + exports
- `src/knowledge_extractor.py` — prompt, validación, escritura md/json
- `scripts/extract_own_transcript_knowledge.py` — CLI
