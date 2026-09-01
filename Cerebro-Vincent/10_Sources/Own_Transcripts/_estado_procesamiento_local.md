---
title: "Estado — transcripciones locales (resumen)"
input_dir: "E:\Vincent\Vincent-Code"
updated_at: "2026-07-24 18:34 UTC"
tags: [transcript, pipeline, own-video, local-video]
---

# Estado del pipeline local (resumen)

Fuente de verdad (no editar a mano):
`E:\Vincent\Vincent-Code\cache\video_transcripts\state.sqlite3`

Export derivado con el listado completo:
[[_estado_videos_local.json]]

Carpeta de vídeos: `E:\Vincent\Vincent-Code`
Actualizado: 2026-07-24 18:34 UTC

## Conteo

| Estado | Cantidad |
|--------|----------|
| done | 45 |
| pending | 1 |
| needs_repair | 0 |
| failed | 0 |
| skipped | 0 |
| **total** | **46** |

## Regenerar

```powershell
cd E:\Vincent\Vincent-Code
.\venv\Scripts\python.exe scripts\export_local_transcript_status.py
```
