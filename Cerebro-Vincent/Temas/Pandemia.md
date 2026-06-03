---
type: tema
---

# Pandemia

## Descripción
_Definición pendiente._

## Noticias

```dataview
TABLE titulo, fuente
FROM "30_News/Noticias"
WHERE type = "noticia" AND contains(join(temas, " "), this.file.name)
```

Tik Tok Hospitales:
https://x.com/FightWithMemes/status/2011007562322268186?s=20

Enfermedades vacuna
https://needtoknow.news/2025/10/an-inconvenient-study-reveals-453-more-neurodevelopmental-disorders-in-vaccinated-children/

Jhon Hopkins próxima pandemia
https://pure.johnshopkins.edu/en/publications/the-spars-pandemic-20252028-a-futuristic-scenario-to-facilitate-m/
