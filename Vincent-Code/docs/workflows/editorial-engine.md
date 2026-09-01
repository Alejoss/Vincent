# Workflow: Motor editorial (Fase 1)

Transforma knowledge existente + campaña → outline → ensayo canónico → posts por canal.

**No re-extrae conocimiento.** Lee `20_Extractions/` vía `knowledge_sources` en `campaign.md`.

## Flujo

```
knowledge_sources (extracciones existentes)
        +
campaign.md (objetivo, CTA, landing)
        ↓
   outline.md          ← pensar (sin plataforma)
        ↓
   essay.md            ← ensayo canónico AV (500–900 palabras)
        ↓
newsletter.md, youtube.md, telegram.md, x.md, instagram.md
        ↓
Revisión humana en Obsidian
        ↓
Newsletter → run_newsletter_app.bat | resto → copiar/pegar manual
```

## Un solo comando

```powershell
cd E:\Vincent\Vincent-Code

# Por pasos
python scripts/editorial_cli.py outline --editorial seminario-cypherpunk-2026
python scripts/editorial_cli.py essay --editorial seminario-cypherpunk-2026
python scripts/editorial_cli.py channels --editorial seminario-cypherpunk-2026 --only newsletter,youtube

# Pipeline completo
python scripts/editorial_cli.py all --editorial seminario-cypherpunk-2026 --force

# Ver contenido
python scripts/editorial_cli.py show --editorial seminario-cypherpunk-2026 --channel essay
```

O en Streamlit: pestaña **Generar**.

## Modelos

| Tarea | Modelo |
|-------|--------|
| Extracción de knowledge | Ollama (`LLM_PROVIDER`) — pipeline existente |
| Outline, essay, writers | Premium (`EDITORIAL_LLM_MODEL`, default `gpt-4o`) |

```env
EDITORIAL_LLM_PROVIDER=openai
EDITORIAL_LLM_MODEL=gpt-4o
OPENAI_API_KEY=...
```

## Writers vs render

- **Writers (IA):** generan texto final para YouTube, Telegram, X, Instagram.
- **Newsletter:** writer genera `newsletter.md` → `renderer.py` (sin IA) → HTML SMTP2GO.

## Memorias

| Memoria | Implementación |
|---------|----------------|
| Knowledge | `20_Extractions/`, `extract_own_transcript_knowledge.py` |
| Editorial | Ejemplos de posts pasados en otras campañas (fase 1: scan simple; fase 2: embeddings) |

## Archivos por campaña

```
Campaigns/2026/Mi-Campaña/
  campaign.md
  outline.md
  essay.md
  newsletter.md
  youtube.md
  ...
```

## Prompts y brand book

`src/editorial/prompts/` — un system prompt por writer. Mismo modelo, instrucciones distintas.

Ver también: [editorial-campaigns.md](editorial-campaigns.md), [newsletter-smtp2go.md](newsletter-smtp2go.md)
