---
type: tema
---

# Alimentos

## Descripción
_Definición pendiente._

## Noticias

```dataview
TABLE titulo, fuente
FROM "30_News/Noticias"
WHERE type = "noticia" AND contains(join(temas, " "), this.file.name)
```

New Zeland Apicultores obligados a quemar panales:
https://x.com/ValerieAnne1970/status/2036503313273987575?s=20

