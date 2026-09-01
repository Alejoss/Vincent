# Campañas editoriales

Cada campaña es **autocontenida** con subcarpetas por tipo de contenido:

```
Campaigns/2026/Seminario-Cypherpunk/
  campaign.md
  newsletters/                          ← emails (uno por envío)
    01-lanzamiento-lista-general.md
    02-bienvenida-inscritos.md
  posts/                                ← redes (canal + número + propósito)
    youtube-01-lanzamiento-comunidad.md
  editorial/                            ← outline + ensayo canónico (motor IA)
    outline.md
    essay.md
  assets/                               ← imágenes de esta campaña
  analytics.md
  lessons_learned.md
```

## Convención de nombres

| Carpeta | Patrón | Ejemplo |
|---------|--------|---------|
| `newsletters/` | `NN-propósito-audiencia.md` | `01-lanzamiento-lista-general.md` |
| `posts/` | `{canal}-NN-propósito.md` | `youtube-01-lanzamiento-comunidad.md` |

El prefijo numérico (`01`, `02`) ordena los envíos en el tiempo.

## Reglas

1. **Un archivo = un envío publicado o borrador** — el nombre debe decir qué es sin abrirlo.
2. **Assets en `assets/`** — desde `newsletters/` usa `../assets/imagen.png`.
3. **Audiencia de emails** — lista en `newsletters/suscriptores.md` (fuera de Campaigns).
