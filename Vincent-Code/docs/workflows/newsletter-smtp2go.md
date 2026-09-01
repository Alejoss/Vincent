# Workflow: Newsletter (SMTP2GO)

Herramienta local para **escribir**, **previsualizar** y **enviar** newsletters. Las estadísticas (aperturas, clics, rebotes) se consultan en SMTP2GO → Reports.

Guía de campañas: [editorial-campaigns.md](editorial-campaigns.md)

---

## Proceso completo: enviar un correo

### 1. Preparar audiencia (Obsidian)

Archivo: `Cerebro-Vincent/newsletters/suscriptores.md`

| Columna | Uso |
|---------|-----|
| `email` | Destinatario |
| `nombre` | Opcional |
| `segmento` | Quién recibe este envío (`test`, `general`, `club-de-lectura`, …) |
| `activo` | Solo `sí` recibe correo |
| `notas` | Contexto humano |

Una misma persona puede tener **varias filas** (ej. `general` + `club-de-lectura`). Al enviar eliges **un** segmento.

### 2. Escribir el newsletter (Obsidian)

Archivo: `Campaigns/YYYY/Nombre-Campaña/newsletters/NN-proposito.md`

```yaml
---
subject: "Asunto del email"          # ← lo que ve el destinatario como asunto
preview_text: "Preheader"
tag: mi-tag-envio                    # ← etiqueta del envío (analytics / logs)
segment: club-de-lectura             # ← segmento por defecto al enviar
status: draft
hide_note_title: true                # el H1 de Obsidian no va al email
---

Hola,

Cuerpo del email…

![…](../assets/imagen.png)
```

| Campo | Dónde vive | No confundir con |
|-------|------------|------------------|
| **Asunto** | `subject` en el frontmatter | Nombre del archivo / H1 de la nota |
| **Remitente** | `NEWSLETTER_FROM_NAME` en `.env` | El asunto |
| **Quién recibe** | columna `segmento` en `suscriptores.md` | Tag del email |

En `campaign.md`, el tag por defecto de la campaña es `email_tag` (no el asunto).

### 3. Probar

```powershell
cd E:\Vincent\Vincent-Code
python scripts/newsletter_cli.py test --md "…\newsletters\02-bienvenida-inscritos.md"
```

O Streamlit → **Componer** → cargar newsletter → **Vista previa** → **Enviar prueba**.

### 4. Enviar campaña

```powershell
python scripts/newsletter_cli.py send --md "…\02-bienvenida-inscritos.md" --segment club-de-lectura -y
```

O Streamlit → **Enviar** → segmento → confirmar → enviar.

---

## Dónde se registra cada cosa

### Automático (al enviar con CLI/app)

| Qué | Dónde | Detalle |
|-----|-------|---------|
| Resumen del envío | `Vincent-Code/data/newsletter.db` → tabla `campaigns` | Asunto, tag, segmento, fecha, OK, método |
| **Lista de emails que lo recibieron** | `newsletter.db` → tabla `campaign_deliveries` | Un registro por destinatario (envío #N) |
| Log rápido | `Vincent-Code/data/newsletter_send_log.jsonl` | Una línea JSON por intento |
| Vínculo a campaña editorial | `newsletter.db` → `channel_sends` + `editorial_slug` | Si enviaste con `--editorial` o se vinculó después |
| Entrega real + aperturas/clics | **SMTP2GO** Reports | Fuente de verdad de métricas de email |

Consultar destinatarios del envío #2:

```powershell
.\venv\Scripts\python.exe -c "from src.newsletter.campaign_log import get_campaign_recipients; print([r['email'] for r in get_campaign_recipients(2)])"
```

### Manual (después de enviar — checklist Obsidian)

| Archivo | Qué actualizar |
|---------|----------------|
| `newsletters/NN-….md` | `status: published` + `published_at: YYYY-MM-DD` |
| `campaign.md` | Tabla de activos (estado) + línea en **Notas** |
| `analytics.md` | Fila del envío: enviados, tag, fecha (open rate/CTR cuando los mires en SMTP2GO) |

SQLite ya sabe **a quién** se envió. Obsidian guarda el **contexto editorial** (qué era el envío, cuándo se publicó, métricas humanas).

### Qué NO se registra en SQLite

- Posts de YouTube / Telegram / X / Instagram → solo Obsidian (`posts/…` + `published_at`)
- Lista de suscriptores → solo `newsletters/suscriptores.md`

---

## Mapa rápido

```
suscriptores.md          →  quién puede recibir (por segmento)
newsletter NN.md         →  qué se envía (asunto, cuerpo, tag)
     │
     ▼  send (CLI o Streamlit)
     │
newsletter.db            →  a quién se envió (campaign_deliveries)
newsletter_send_log.jsonl→  log local rápido
SMTP2GO                  →  entrega + opens + clicks
     │
     ▼  (manual)
campaign.md / analytics.md / status published
```

---

## UI (Streamlit)

```powershell
cd E:\Vincent\Vincent-Code
scripts\run_newsletter_app.bat
```

Abre `http://localhost:8501`.

## CLI

```powershell
# Por archivo (recomendado cuando hay varios newsletters en la campaña)
python scripts/newsletter_cli.py preview --md "…\newsletters\02-bienvenida-inscritos.md"
python scripts/newsletter_cli.py test --md "…\02-bienvenida-inscritos.md"
python scripts/newsletter_cli.py send --md "…\02-bienvenida-inscritos.md" --segment club-de-lectura -y

# Por campaña (usa primary_newsletter del campaign.md)
python scripts/newsletter_cli.py send --editorial seminario-cypherpunk-2026 -y
```

## Variables (.env)

```env
NEWSLETTER_PROVIDER=smtp2go
SMTP2GO_API_KEY=api-...
NEWSLETTER_FROM_EMAIL=news@newsletter.academiablockchain.com
NEWSLETTER_FROM_NAME=Alejandro de Academia Blockchain
NEWSLETTER_REPLY_TO=alejandro@academiablockchain.com
NEWSLETTER_TEST_EMAIL=alejandro@academiablockchain.com
NEWSLETTER_MD_DIR=../Cerebro-Vincent/newsletters
CAMPAIGNS_DIR=../Cerebro-Vincent/Campaigns
```

También se acepta el typo `SMPT2GO_API_KEY`. Overrides de UI: `data/newsletter_settings.json` (gitignored).

## Segmentos típicos

| Segmento | Uso |
|----------|-----|
| `test` | Solo tus correos |
| `general` | Lista amplia de newsletter |
| `club-de-lectura` | Solo inscritos al seminario |

**No** envíes correos del club a `general`.

## Privacidad

Cada destinatario recibe su propio correo (`To` individual). No se usa CCO/BCC masivo.

## Preview HTML

Exportados en `emails/preview/` (fuera del vault).
