"""
Notion client for the Vincent productivity database (diario de productividad).
Discovers schema (property names and types) and runs filtered queries for daily email composition.
"""

import logging
from typing import Dict, List, Optional, Any

from notion_client import Client

logger = logging.getLogger(__name__)

# Default Vincent database ID (productivity journal)
NOTION_VINCENT_DATABASE_ID = "6e82d5ffee04490f8ede6aa8026e3f88"


def normalize_id(block_id: str) -> str:
    """Format Notion ID with hyphens if 32 chars without."""
    s = (block_id or "").replace("-", "").strip()
    if len(s) == 32:
        return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}"
    return block_id or ""


# Logical names from plan_inicial_emails_diarios: Item, Resumen, Estado, Tipo, Prioridad, PriorityScore, Fecha
# We map by type and by name hint (case-insensitive).
LOGICAL_PROP_CONFIG = [
    ("item", "title", ["item", "name", "titulo", "title"]),
    ("resumen", "rich_text", ["resumen", "summary"]),
    ("estado", None, ["estado", "status"]),  # type: status or select
    ("tipo", "select", ["tipo", "type"]),
    ("prioridad", "select", ["prioridad", "priority"]),
    ("priority_score", "number", ["priorityscore", "priority_score", "prioridad score"]),
    ("fecha", "date", ["fecha", "date"]),
]


class VincentNotionClient:
    """Client for the Vincent Notion database: schema discovery and query."""

    def __init__(self, api_token: str, database_id: Optional[str] = None):
        self.client = Client(auth=api_token, notion_version="2025-09-03")
        self.api_token = api_token
        self.database_id = normalize_id(database_id or NOTION_VINCENT_DATABASE_ID)
        self._data_source_id: Optional[str] = None
        self._properties: Optional[Dict[str, Any]] = None
        self._prop_names: Optional[Dict[str, Dict[str, Any]]] = None

    def _get_data_source_id(self) -> str:
        if self._data_source_id is not None:
            return self._data_source_id
        try:
            response = self.client.databases.retrieve(database_id=self.database_id)
            data_sources = response.get("data_sources", [])
            if not data_sources:
                logger.warning("No data_sources for database %s, using database_id", self.database_id)
                self._data_source_id = self.database_id
            else:
                self._data_source_id = data_sources[0]["id"]
            return self._data_source_id
        except Exception as e:
            logger.warning("Failed to get data_source_id: %s, using database_id", e)
            self._data_source_id = self.database_id
            return self._data_source_id

    def _get_properties(self) -> Dict[str, Any]:
        if self._properties is not None:
            return self._properties
        ds_id = self._get_data_source_id()
        try:
            if ds_id == self.database_id:
                db = self.client.databases.retrieve(database_id=self.database_id)
                self._properties = db.get("properties", {})
            else:
                ds = self.client.data_sources.retrieve(data_source_id=ds_id)
                self._properties = ds.get("properties", {})
        except Exception as e:
            logger.error("Failed to get properties: %s", e)
            self._properties = {}
        return self._properties

    def get_vincent_property_names(self) -> Dict[str, Dict[str, Any]]:
        """
        Return mapping of logical name -> { "name": actual_prop_name, "type": notion_type }.
        Keys: item, resumen, estado, tipo, prioridad, priority_score, fecha.
        """
        if self._prop_names is not None:
            return self._prop_names
        props = self._get_properties()
        result: Dict[str, Dict[str, Any]] = {}
        for prop_name, prop_def in props.items():
            prop_type = prop_def.get("type")
            name_lower = (prop_name or "").strip().lower().replace(" ", "").replace("-", "").replace("_", "")
            for logical, expected_type, hints in LOGICAL_PROP_CONFIG:
                if logical in result:
                    continue
                for hint in hints:
                    if hint.replace(" ", "").replace("_", "") in name_lower or name_lower in hint.replace(" ", ""):
                        if expected_type is None or prop_type == expected_type:
                            result[logical] = {"name": prop_name, "type": prop_type}
                            break
                        if logical == "estado" and prop_type in ("status", "select"):
                            result[logical] = {"name": prop_name, "type": prop_type}
                            break
                else:
                    continue
                break
        # Fallback: by type only for item (first title), resumen (first rich_text), etc.
        if "item" not in result:
            for prop_name, prop_def in props.items():
                if prop_def.get("type") == "title":
                    result["item"] = {"name": prop_name, "type": "title"}
                    break
        if "resumen" not in result:
            for prop_name, prop_def in props.items():
                if prop_def.get("type") == "rich_text":
                    result["resumen"] = {"name": prop_name, "type": "rich_text"}
                    break
        if "estado" not in result:
            for prop_name, prop_def in props.items():
                t = prop_def.get("type")
                if t in ("status", "select") and "estado" in (prop_name or "").lower():
                    result["estado"] = {"name": prop_name, "type": t}
                    break
        if "fecha" not in result:
            for prop_name, prop_def in props.items():
                if prop_def.get("type") == "date":
                    result["fecha"] = {"name": prop_name, "type": "date"}
                    break
        self._prop_names = result
        logger.debug("Vincent property names: %s", result)
        return result

    def _get_property_value(self, properties: Dict, logical_key: str) -> Any:
        """Get value for a logical property from a page's properties dict."""
        pnames = self.get_vincent_property_names()
        if logical_key not in pnames:
            return None
        info = pnames[logical_key]
        prop_name = info["name"]
        prop_type = info["type"]
        prop = properties.get(prop_name, {})
        if prop_type == "title":
            title = prop.get("title", [])
            if title:
                return title[0].get("plain_text") or title[0].get("text", {}).get("content", "") or ""
            return ""
        if prop_type == "rich_text":
            rt = prop.get("rich_text", [])
            if rt:
                return rt[0].get("plain_text") or rt[0].get("text", {}).get("content", "") or ""
            return ""
        if prop_type == "status":
            st = prop.get("status", {})
            return st.get("name", "") if st else ""
        if prop_type == "select":
            sel = prop.get("select", {})
            return sel.get("name", "") if sel else ""
        if prop_type == "date":
            d = prop.get("date", {})
            return d.get("start") if d else None
        if prop_type == "number":
            return prop.get("number")
        return None

    def query(
        self,
        filter_obj: Optional[Dict] = None,
        sorts: Optional[List[Dict]] = None,
        page_size: int = 100,
    ) -> List[Dict]:
        """
        Query Vincent database. Returns list of page objects (each has id, properties, url).
        Uses data_sources.query if available, else databases.query.
        """
        ds_id = self._get_data_source_id()
        kwargs = {"page_size": min(page_size, 100)}
        if filter_obj:
            kwargs["filter"] = filter_obj
        if sorts:
            kwargs["sorts"] = sorts
        try:
            if ds_id == self.database_id:
                response = self.client.databases.query(database_id=self.database_id, **kwargs)
            else:
                if hasattr(self.client, "data_sources") and hasattr(self.client.data_sources, "query"):
                    response = self.client.data_sources.query(data_source_id=ds_id, **kwargs)
                else:
                    import requests
                    body = {"page_size": kwargs["page_size"]}
                    if filter_obj:
                        body["filter"] = filter_obj
                    if sorts:
                        body["sorts"] = sorts
                    response = requests.post(
                        f"https://api.notion.com/v1/data_sources/{ds_id}/query",
                        headers={
                            "Authorization": f"Bearer {self.api_token}",
                            "Notion-Version": "2025-09-03",
                            "Content-Type": "application/json",
                        },
                        json=body,
                    ).json()
            results = response.get("results", [])
            # Notion page URL: https://www.notion.so/workspace/ PAGE_ID
            for page in results:
                if not page.get("url") and page.get("id"):
                    page["url"] = f"https://www.notion.so/{page['id'].replace('-', '')}"
            return results
        except Exception as e:
            logger.error("Vincent query failed: %s", e)
            return []

    def page_to_item(self, page: Dict) -> Dict[str, Any]:
        """Convert a Notion page result to a simple item dict: item, resumen, estado, url."""
        props = page.get("properties", {})
        item_text = self._get_property_value(props, "item") or ""
        resumen_text = self._get_property_value(props, "resumen") or ""
        estado = self._get_property_value(props, "estado") or ""
        url = page.get("url") or ("https://www.notion.so/" + (page.get("id") or "").replace("-", ""))
        return {
            "item": item_text,
            "resumen": resumen_text,
            "estado": estado,
            "url": url,
        }
