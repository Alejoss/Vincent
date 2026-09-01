# Audiencia (newsletter)

Un solo archivo maestro: **`suscriptores.md`**.

## Segmentos

| Segmento | Quién va aquí |
|----------|----------------|
| `test` | Tus correos para pruebas |
| `general` | Suscriptores newsletter (lista amplia) |
| `club-de-lectura` | **Solo** quien se inscribió al seminario / club |

Una persona puede estar en **varios segmentos** (filas distintas con el mismo email) o en uno solo. Al enviar, eliges el segmento en la app.

**Regla:** no envíes correos del club a `general`. Los inscritos al seminario van con `segmento: club-de-lectura`.

Ejemplo:

| email | nombre | segmento | activo | notas |
|-------|--------|----------|--------|-------|
| persona@mail.com | Ana | general | sí | Newsletter |
| persona@mail.com | Ana | club-de-lectura | sí | Inscrita landing 2026-07-10 |

## ¿Dónde va el asunto del email?

**No** en `suscriptores.md`. El asunto está en el frontmatter del newsletter:

`Campaigns/2026/Seminario-Cypherpunk/newsletters/02-bienvenida-inscritos.md`

```yaml
subject: "Gracias por inscribirte — comenzamos el 20 de julio"
```

## ¿Dónde va el nombre del remitente («Alejandro de Academia Blockchain»)?

En `.env` o Streamlit → Configuración:

```env
NEWSLETTER_FROM_NAME=Alejandro de Academia Blockchain
NEWSLETTER_FROM_EMAIL=news@newsletter.academiablockchain.com
```

Eso es lo que Gmail muestra como remitente, no el campo `subject`.

## Contenido de campañas

Emails y posts: `Campaigns/YYYY/Nombre-Campaña/newsletters/` y `posts/`.
