---
type: proyecto
---

# Desarrollo de Software para Vincent

## Entradas

```dataview
TABLE tipo, referencia_temporal, fecha_objetivo, file.folder as carpeta
FROM "0_Diario_Productividad/Tareas-Ideas" OR "0_Diario_Productividad/Aprendizajes"
WHERE proyecto = this.file.name
SORT file.name DESC
```

