---
title: "Instrucciones: Emails diarios (desde Vincent)"
source: https://www.notion.so/Instrucciones-Emails-diarios-desde-Vincent-81b05041de7448fc921aec4ad9ca5900
last_edited: "2026-02-16T00:20:00.000Z"
---

# Instrucciones: Emails diarios (desde Vincent)

> Este documento define la configuración para generar un email diario usando datos de la base Vincent (data source ).

### 0) Mapeo a la BD real (Vincent)

Estados válidos (columna Estado)

- Inbox/Todo

- Pendiente

- En progreso

- Bloqueado

- Hecho

- Archivado

Tipos válidos (columna Tipo)

- Tasks

- Problemas

- Decisiones

- Ideas

- Logs

- Sistemas

- Projects

- Areas

- Personas

- Metrics

- Diario-Original

Campos disponibles (los más útiles para email)

- Item (title)

- Resumen (text)

- Estado (status)

- Tipo (select)

- Prioridad (select: Low/Medium/High)

- PriorityScore (number: 1/2/3)

- Fecha (date)

- Tags (multi-select)

- Proyecto (relation)

- Área (relation)

- Fuente (url)

- SourceID (text)

> Nota: Actualmente Vincent no tiene due_date. Por eso, cualquier regla de “overdue” o “due in 3 days” debe definirse de otra forma (por ejemplo usando Fecha como “fecha de registro” o agregando una propiedad nueva “Vence” en el futuro).

---

### 1) Reglas generales de selección (para cualquier día)

Definiciones estándar

- is_open:

- is_closed:

- exclude_archived:

- exclude_closed:

Heurística de “alto impacto”

- Incluir primero ítems con:

Reglas de redacción

- Máximo 7 bullets en total (incluyendo subtítulos si los usas como bullets).

- No inventar información que no esté en Item/Resumen/Contexto.

- 1 línea por bullet.

- Preferir Resumen si existe; si no, usar Item.

- Incluir links cuando sea posible (al menos el link del ítem en Notion).

---

### 2) Formato del email

Subject

- [{DAY_SHORT}] {FOCUS_TITLE} — {YYYY-MM-DD}

Body

- Título corto

- Secciones por categoría (cada sección con 1–3 bullets)

- Si una sección no tiene resultados, omitirla.

Ejemplo de bullet recomendado:

- • 🔥 {Resumen} — ({Estado}) [{Proyecto}] + link

---

### 3) Edición rápida: qué se envía cada día (lo que debes editar tú)

La idea es que esta sección sea lo único que edites a futuro.

Regla adicional (contexto útil): siempre incluir Proyecto si existe

- En cada bullet, si el ítem tiene relación Proyecto, incluirlo como sufijo corto \[{Proyecto}\].

- Si hay más de 2 proyectos relacionados, mostrar máximo 2 y agregar “+N” (ej. [ACBC YouTube, Patreon +1]).

- Cada día tiene un FOCO (título) y una lista de Secciones.

- Cada sección describe:

> Tu script ya está construido: úsalo para mapear estas reglas a tus queries reales. Si en el futuro cambias el formato del script, solo mantén consistente el “contrato” con esta sección.

🟢 Lunes — Foco semanal

- 🔥 Prioridades (3)

- 🚧 Bloqueos (2)

- 🧠 Decisiones recientes (2)

🔵 Martes — Mejora continua

- 📘 Aprendizajes recientes (3)

- ⚠ Problemas abiertos (2)

- 🔁 Problema recurrente (1)

🟠 Miércoles — Ejecución

- 🔥 3 tareas críticas (3)

- ⏳ Vence pronto (2)

🟣 Jueves — Fricción y cuellos de botella

- 🚧 Bloqueado (3)

- ⚠ Problemas activos (2)

- 📥 Inbox viejo (2)

🟡 Viernes — Expansión

- 💡 Ideas de contenido (3)

- 📈 Métricas recientes (2)

---

### 4) Configuración estable (toca esto rara vez)

Estas reglas casi nunca deberían cambiar:

- Máximo 7 bullets totales.

- 1 línea por bullet.

- Excluir Estado = Archivado (y normalmente también Hecho).

- Preferir Resumen y si está vacío, usar Item.

- Link por ítem.

Anti-repetición (dedupe)

- Antes de armar los bullets finales, deduplicar por tema.

Anti-fatiga semanal (evitar repetir lo mismo todos los días)

- Mantener un registro (en tu script) de los dedupe_key enviados en los últimos 7 días.

- Regla: un mismo dedupe_key no debe aparecer más de 2 veces en la semana, a menos que se cumpla alguna condición de excepción.

- Excepciones (sí permitir repetirlo):

- Si un ítem es filtrado por anti-fatiga pero sigue siendo importante, el script puede:

- Regla recomendada:

- Si un ítem eliminado por dedupe tiene un detalle importante (por ejemplo, “antes del beta”), incorporarlo como sufijo corto en el que se mantiene.

Ejemplo:

- "Desarrollar Vincent; se considera la tarea más importante" y "Desarrollar Vincent para leer el diario; antes del beta" → dejar uno como:

### 5) Notas para el script (mínimas)

- “Recurrente” = conteo por Item normalizado.

- “Proyecto sin avance” = usar relación Proyecto y tomar la última Fecha asociada a cualquier item del proyecto.
