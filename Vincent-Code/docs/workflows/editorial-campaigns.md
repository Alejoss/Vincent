# Workflow: Campañas editoriales

Cada campaña vive en Obsidian bajo `Campaigns/`. El newsletter se envía desde ahí; no hay scripts extra que correr en el día a día.

## Flujo normal (todo lo que necesitas)

1. Edita `Campaigns/YYYY/Nombre-Campaña/newsletter.md` en Obsidian.
2. Abre la app: `scripts\run_newsletter_app.bat`
3. **Componer** → cargar campaña → **Vista previa** → **Enviar**.

O por CLI:

```powershell
python scripts/newsletter_cli.py preview --editorial seminario-cypherpunk-2026
python scripts/newsletter_cli.py test --editorial seminario-cypherpunk-2026
python scripts/newsletter_cli.py send --editorial seminario-cypherpunk-2026 -y
```

La app lee las campañas **directamente desde Obsidian** (no hace falta sincronizar nada antes de componer o enviar). Al enviar, el registro en SQLite se actualiza solo.

**Checklist completo de envío** (dónde registrar cada cosa): [newsletter-smtp2go.md](newsletter-smtp2go.md) → sección *Proceso completo* y *Dónde se registra cada cosa*.

## Estructura en Obsidian (dos carpetas, sin solapamiento)

```
Cerebro-Vincent/
  Campaigns/2026/Seminario-Cypherpunk/
    newsletters/
      01-lanzamiento-lista-general.md
      02-bienvenida-inscritos.md
    posts/
      youtube-01-lanzamiento-comunidad.md
    assets/
  newsletters/            # SOLO audiencia (suscriptores.md)
    suscriptores.md
```

| Carpeta | Contiene |
|---------|----------|
| `Campaigns/.../newsletters/` | Un archivo por email (nombre = propósito + audiencia) |
| `Campaigns/.../posts/` | Un archivo por post en redes (`youtube-01-...`) |
| `newsletters/` (raíz vault) | Solo `suscriptores.md` |

## Crear una campaña nueva

**Opción A (recomendada):** copia la carpeta `_templates` en Obsidian, renómbrala y edita `campaign.md` + `newsletter.md`.

**Opción B (opcional):** scaffolding por terminal, una sola vez al crear:

```powershell
python scripts/campaign_new.py --slug mi-campana-2026 --title "Mi Campaña" --year 2026
```

## Qué hace SQLite (automático)

`data/newsletter.db` guarda historial de envíos. Se escribe solo cuando envías; no requiere mantenimiento manual. Las estadísticas de aperturas/clics siguen en SMTP2GO Reports.

## Variables (.env)

```env
CAMPAIGNS_DIR=../Cerebro-Vincent/Campaigns
NEWSLETTER_PROVIDER=smtp2go
SMTP2GO_API_KEY=api-...
NEWSLETTER_FROM_EMAIL=news@newsletter.academiablockchain.com
NEWSLETTER_FROM_NAME=Alejandro de Academia Blockchain
```

## Al publicar un post (YouTube, Telegram, X, etc.)

Sin scripts. Tres lugares en Obsidian:

| Archivo | Qué guardar |
|---------|-------------|
| `youtube.md` (o `telegram.md`, etc.) | Texto **tal como se publicó** + `status: published` + `published_at: YYYY-MM-DD` |
| `analytics.md` | Fila «Publicado \| sí \| fecha»; métricas cuando las tengas |
| `campaign.md` → Notas | Una línea de registro (opcional) |

La **fecha de publicación** va en el frontmatter del archivo del canal (`published_at`). SQLite no se toca para posts manuales; solo el newsletter auto-registra en `channel_sends` al enviar desde la app.

## Editorial Memory

Los posts con `status: published` en `Campaigns/` alimentan ejemplos para futuros writers (scan en `load_editorial_examples`).

Ver también: [motor editorial](editorial-engine.md) · [newsletter](newsletter-smtp2go.md)
