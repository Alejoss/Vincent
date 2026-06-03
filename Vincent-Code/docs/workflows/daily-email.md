# Workflow: Email Diario

Genera y opcionalmente envia un email diario con contenido consolidado desde Notion.

## Script principal

```powershell
python scripts/compose_daily_email.py
python scripts/compose_daily_email.py --send
```

Wrapper recomendado en Windows:

```powershell
scripts\run_daily_email_send.bat
```

## Variables SMTP (solo para --send)

- `SMTP_HOST`
- `SMTP_PORT` (default 587)
- `SMTP_USER`
- `SMTP_PASSWORD` o `EMAIL_APP_PASSWORD`
- `EMAIL_FROM`
- `EMAIL_TO`

## Comportamiento anti-duplicado

Con `--send`, envia como maximo 1 correo por dia usando:

- `.last_sent_date`
