# Active Tasks database

Unfinished entries were copied from Tareas Ideas into **Tasks** under
Productividad. The original database is retained as historical data.

- Old database: `20d793a2-5b64-4663-bca9-641d927171ca`
- Active database: `0b762000-e576-4adc-b064-921992a2c9ad`
- Active data source: `72df91aa-9179-4713-8391-83cc789f6e8a`
- Unfiltered All tasks view: `3e4a1c4e-08e8-8144-9529-000c2024f774`

18 unfinished entries were copied, including a task received during migration.
Pending and unset statuses become Sin empezar; En progreso is preserved.
Dates, titles, projects, priorities, Slack text, notes, and paragraph content
were compared against the original pages. The 68 completed entries stay in
the old database.

`state/tasks_migration_20260923.json` records old-to-new page IDs. Corresponding
Obsidian notes link to the new pages. Notes linked to the old database remain
excluded from the active database by the existing database-id routing rule.
Reminder history is copied to new IDs to avoid duplicate reminders.

Local `.env` and GitHub environment `Ramdau` use the active database in
`NOTION_TASKS_DATABASE_ID`. This controls sync, Slack task updates, reminders,
and local Vincent task tools. No Slack messages are sent by the migration.
Existing Notion edits remain authoritative.

The local initial backup is `logs/tasks-migration-20260923.json`; the original
Notion pages also remain intact. The migration script is for this cutover only;
do not rerun it after ongoing task management resumes.
