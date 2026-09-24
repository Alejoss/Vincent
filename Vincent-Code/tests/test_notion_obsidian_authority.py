"""Regression coverage for Notion-owned task properties."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sync_productivity_obsidian_to_notion as sync
from src.notion_obsidian_mirror import mirror_page
from src.slack_task_update_obsidian import should_skip_productivity_classify


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "slack-123.md"
        self.original = ('---\nslack_ts: "123"\ntipo: "Tarea"\ncustom: [one, two]\n'
                         'fecha_objetivo: "2026-07-20"\n---\nTitulo: Old\n'
                         'Fecha objetivo: 2026-07-20\n\n## Contenido completo (Slack)\n'
                         'Cancel Scribd on July 20.\n')
        self.path.write_text(self.original, encoding="utf-8")
        self.item = sync.NoteItem(self.path, "123", "2026-06-26", "", "Tarea", "nueva",
                                  "General", "Old", "July 20", "2026-07-20", "Old", "Original")
        self.map = {"title": "Tarea", "tipo": "Tipo", "proyecto": "Proyecto",
                    "slack_ts": "slack_ts", "slack_fecha": "Inicio", "inicio": "Inicio",
                    "fin": "Fin", "fin_type": "date", "estado": "Estado"}
        self.page = {"id": "page-1", "properties": {
            "Tarea": {"type": "title", "title": [{"plain_text": 'New "title"'}]},
            "Fin": {"type": "date", "date": {"start": "2026-09-20", "end": None}},
            "Estado": {"type": "status", "status": {"name": "En progreso"}},
            "Tipo": {"type": "select", "select": None},
            "Proyecto": {"type": "select", "select": {"name": "Personal"}},
        }}

    def test_changes_and_clears_mirror_without_touching_original(self):
        self.assertTrue(mirror_page(self.path, self.page, self.map, "db"))
        text = self.path.read_text(encoding="utf-8")
        self.assertIn('fecha_objetivo: "2026-09-20"', text)
        self.assertIn('estado: "En progreso"', text)
        self.assertIn('tipo: ""', text)
        self.assertIn('proyecto: "Personal"', text)
        self.assertIn('custom: [one, two]', text)
        self.assertEqual(text.split(sync.SLACK_BODY_SECTION)[1], self.original.split(sync.SLACK_BODY_SECTION)[1])
        self.assertFalse(mirror_page(self.path, self.page, self.map, "db"))
        self.page["properties"]["Fin"]["date"] = None
        mirror_page(self.path, self.page, self.map, "db")
        self.assertIn('fecha_objetivo: ""', self.path.read_text(encoding="utf-8"))

    def run_upsert(self, existing, dry_run=False):
        client = Mock()
        client.pages.retrieve.return_value = self.page
        client.pages.create.return_value = self.page
        with patch.object(sync, "get_ds_and_props", return_value=("db", {"slack_ts": {"type": "rich_text"}})), \
             patch.object(sync, "build_prop_map", return_value=self.map), \
             patch.object(sync, "find_page_by_slack_ts", return_value=existing):
            result = sync.upsert_items(client, "db", [self.item], dry_run)
        client.pages.update.assert_not_called()
        return client, result

    def test_existing_task_only_reads_notion(self):
        client, result = self.run_upsert("page-1")
        client.pages.create.assert_not_called()
        self.assertEqual(result, (0, 1, 0))

    def test_dry_run_changes_neither_side(self):
        client, _ = self.run_upsert("page-1", True)
        client.pages.create.assert_not_called()
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.original)

    def test_new_task_created_and_linked(self):
        client, result = self.run_upsert(None)
        self.assertEqual(result, (1, 0, 0))
        self.assertEqual(client.pages.create.call_args.kwargs["properties"]["Fin"]["date"]["start"], "2026-07-20")
        self.assertIn('notion_page_id: "page-1"', self.path.read_text(encoding="utf-8"))

    def test_new_database_spanish_default_status(self):
        props = {
            "Tarea": {"type": "title"}, "tipo": {"type": "select"},
            "Proyecto": {"type": "select"}, "slack_ts": {"type": "rich_text"},
            "Estado": {"type": "status", "status": {"options": [
                {"name": "Sin empezar"}, {"name": "En progreso"}, {"name": "Listo"}]}}
        }
        mapping = sync.build_prop_map(props)
        payload = sync.build_props(mapping, self.item, set_default_status=True)
        self.assertEqual(payload["Estado"], {"status": {"name": "Sin empezar"}})

    def test_link_survives_archiving_and_does_not_recreate(self):
        self.item.notion_page_id = "page-1"
        self.page["archived"] = True
        client, _ = self.run_upsert(None)
        client.pages.create.assert_not_called()
        self.assertIn('notion_archived: true', self.path.read_text(encoding="utf-8"))

    def test_linked_notes_skip_reclassification(self):
        self.assertTrue(should_skip_productivity_classify({"notion_page_id": '"page-1"'}))

    def test_cleared_type_still_gathered(self):
        folder = Path(self.temp.name) / "0_Diario_Productividad" / "Tareas-Ideas"
        folder.mkdir(parents=True)
        mirror_page(self.path, self.page, self.map, "db")
        self.path.rename(folder / self.path.name)
        notes = sync.gather_notes(self.temp.name)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].notion_database_id, "db")

    def test_cleared_fin_wins_over_other_due_date(self):
        self.map["fecha_objetivo"] = "Fecha objetivo"
        self.page["properties"]["Fecha objetivo"] = {"type": "date", "date": {"start": "2026-07-20"}}
        self.page["properties"]["Fin"]["date"] = None
        mirror_page(self.path, self.page, self.map, "db")
        self.assertIn('fecha_objetivo: ""', self.path.read_text(encoding="utf-8"))

    def test_date_range_preserved(self):
        self.page["properties"]["Fin"]["date"] = {
            "start": "2026-09-20T09:00:00", "end": "2026-09-21T10:00:00", "time_zone": "America/Guayaquil"}
        mirror_page(self.path, self.page, self.map, "db")
        text = self.path.read_text(encoding="utf-8")
        self.assertIn('fecha_objetivo_end: "2026-09-21T10:00:00"', text)
        self.assertIn('fecha_objetivo_time_zone: "America/Guayaquil"', text)

    def test_failed_read_does_not_create_replacement(self):
        self.item.notion_page_id = "page-1"
        client = Mock()
        client.pages.retrieve.side_effect = RuntimeError("Notion unavailable")
        with patch.object(sync, "get_ds_and_props", return_value=("db", {"slack_ts": {"type": "rich_text"}})), \
             patch.object(sync, "build_prop_map", return_value=self.map):
            with self.assertRaises(RuntimeError):
                sync.upsert_items(client, "db", [self.item], False)
        client.pages.create.assert_not_called()
        client.pages.update.assert_not_called()
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.original)


if __name__ == "__main__":
    unittest.main()
