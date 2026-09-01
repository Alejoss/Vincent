---
title: "Orden de publicación — podcasts (mp3)"
folder: "E:\\Vincent\\VideosParaPodcast\\mp3"
updated_at: "2026-07-01"
transcripts: "16/16 en Own_Transcripts"
tags: [podcast, publicacion, mp3]
---

# Orden sugerido para publicar podcasts

Episodios en `mp3/`, ordenados del **más antiguo al más reciente** según la **fecha de modificación del `.mp4`** en la carpeta padre (`VideosParaPodcast/`).

> **Nota:** las fechas de creación de los `.mp3` no sirven para ordenar — casi todos se generaron el **2026-06-24** en un batch de conversión (21:40–21:47). El orden del batch solo refleja el proceso ffmpeg, no la cronología del contenido.

## Tabla

| # | Archivo MP3 | Fecha vídeo (.mp4) | Duración | Transcript | Fuente |
|---|-------------|-------------------|----------|------------|--------|
| 1 | `MercadoTrampa2_final.mp3` | 2024-02-13 | ~25 min | `2024-02-13-mercadotrampa2.md` | Whisper |
| 2 | `guerra_tecnologica_version_publica.mp3` | 2024-04-07 | ~21 min | `2024-04-06-guerra-tecnologica-3.md` | Whisper |
| 3 | `Bitcoin_no_NSA_final.mp3` | 2024-04-09 | ~18 min | `2024-04-12-bitcoin-fue-creado-por-la-nsa-no-hay-esperanza.md` | YouTube |
| 4 | `Farsa_Ripple_Satoshi_Emails2.mp3` | 2024-07-23 | ~15 min | `2024-07-23-cambiaron-la-historia-de-bitcoin-emails-de-satoshi-malmi…` | YouTube |
| 5 | `cripta_vs_ancap_final.mp3` | 2025-02-09 | ~43 min | `2025-02-09-cripta-vs-ancap.md` | Whisper |
| 6 | `recordemos_falsa_historia_btc6.mp3` | 2025-05-16 | ~13 min | `2025-05-17-se-rindieron-a-cambiar-la-historia-de-bitcoin.md` | **Scraper** |
| 7 | `noticias_guerra_cripto_final.mp3` | 2025-06-04 | ~12 min | `2025-06-04-noticias-guerra-cripto.md` | Whisper |
| 8 | `skynet_escenario_final3.mp3` | 2025-06-12 | ~16 min | `2024-08-30-la-inteligencia-artificial-sola-no-va-a-matarte-es-más-sutil.md` | YouTube |
| 9 | `Jhon McAfee final.mp3` | 2025-08-06 | ~31 min | `2025-08-07-quién-mató-a-john-mcafee.md` | **Scraper** |
| 10 | `criptoanarquismo_puro_TE_final.mp3` | 2025-10-17 | ~129 min | `2025-10-20-criptoanarquismo-puro-tertuliaermi-te-remaster-audio.md` | **Scraper** |
| 11 | `china_anuncio_acbc_final.mp3` | 2025-12-03 | ~23 min | `2025-12-06-china-silencia-a-los-influencers-la-historia-oculta-sin-filtros.md` | **Scraper** |
| 12 | `epstein_files_btc.mp3` | 2026-02-06 | ~26 min | `2026-02-07-por-qué-bitcoin-aparece-cuando-se-destapan-los-epstein-files.md` | **Scraper** |
| 13 | `Anom Privacidad.mp3` | 2026-03-23 | ~37 min | `2026-03-27-la-privacidad-nunca-existió-reportaje-la-historia-secreta-de-anom.md` | YouTube |
| 14 | `Debate Derecho Natural.mp3` | 2026-04-10 | ~107 min | `2026-04-10-filosofía-anarquista-para-el-siglo-21-debate-sobre-el-derecho-natural…` | YouTube |
| 15 | `Marx Armesilla.mp3` | 2026-05-30 | ~54 min | `2026-05-31-marxismo-vs-bitcoin-un-choque-inevitable…` | YouTube |
| 16 | `ACBC Hechicero_Banco_Dinero_final.mp3` | 2026-06-03 | ~50 min | `2026-06-03-acbc-hechicero-banco-dinero.md` | Whisper |

**Total:** 16 episodios · ~610 min (~10 h)

## Episodios largos

Conviene espaciarlos en el calendario de publicación:

- **#10** `criptoanarquismo_puro_TE_final` (~129 min)
- **#14** `Debate Derecho Natural` (~107 min)

## Regenerar fechas (PowerShell)

```powershell
Get-ChildItem "E:\Vincent\VideosParaPodcast\mp3" -File | ForEach-Object {
  $mp4 = Join-Path "E:\Vincent\VideosParaPodcast" ($_.BaseName + ".mp4")
  $src = Get-Item $mp4 -ErrorAction SilentlyContinue
  [PSCustomObject]@{
    MP3 = $_.Name
    VideoModified = if ($src) { $src.LastWriteTime.ToString('yyyy-MM-dd') } else { '?' }
  }
} | Sort-Object VideoModified | Format-Table -AutoSize
```
