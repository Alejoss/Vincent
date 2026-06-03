# 0_Diario_Productividad

Estructura simplificada para entradas provenientes de Slack.

## Subcarpetas activas

| Carpeta | Propósito |
|---------|-----------|
| **Input** | Entrada bruta de `sync_slack_inbox_to_obsidian.py` antes de clasificar. |
| **Tareas-Ideas** | Notas clasificadas como `Tarea` o `Idea`. |
| **Aprendizajes** | Notas clasificadas como `Aprendizaje`. |
| **Projects** | Vistas por proyecto (Dataview) para revisar entradas filtradas por `proyecto`. |

El script `Vincent-Code/scripts/classify_slack_input_with_ollama.py` añade `tipo`, `proyecto`, `referencia_temporal` y `fecha_objetivo` a la nota, escribe esos datos en el cuerpo y la mueve automáticamente a su carpeta final.
