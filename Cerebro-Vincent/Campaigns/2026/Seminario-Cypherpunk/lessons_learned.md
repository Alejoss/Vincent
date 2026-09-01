# Lecciones — Seminario Cypherpunk

## Contenido y formato

- El asunto con referencia al Club de Lectura fue claro.
- La imagen-flyer al final como link al CTA funcionó bien.
- El texto largo + CTA explícito encaja con la audiencia existente.

## Deliverability (newsletter)

- DKIM del dominio de envío debe estar verificado en SMTP2GO.
- Sin DKIM alineado, Gmail marcaba DMARC FAIL y enviaba a spam.
- Tras verificar DKIM, Gmail y Private Email recibieron en bandeja principal.
- Lista importada de newsletter anterior = audiencia fría; conviene pedir "No es spam" y engagement.

## Operaciones

- Segmento `test` para pruebas; `general` para envío real (36 suscriptores).
- Registro de envíos en `Vincent-Code/data/newsletter.db`.
- Estadísticas de apertura/clics en SMTP2GO Reports, no duplicar en local.

## Próxima vez

- [ ] Completar analytics.md con datos reales de SMTP2GO tras 48h
- [ ] Publicar en Telegram, X, Instagram con mensajes adaptados
- [ ] Registrar conversiones en landing si hay analytics web
