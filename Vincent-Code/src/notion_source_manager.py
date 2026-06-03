"""Source manager for reading and writing sources from Notion database."""

import logging
from datetime import datetime
from typing import List, Dict, Optional
from notion_client import Client

logger = logging.getLogger(__name__)


class NotionSourceManager:
    """Manages sources stored in Notion database."""
    
    def __init__(self, api_token: str, sources_db_id: str):
        """
        Initialize Notion source manager.
        
        Args:
            api_token: Notion API token
            sources_db_id: Database ID for sources
        """
        self.client = Client(auth=api_token, notion_version="2025-09-03")
        self.api_token = api_token  # Store for manual requests if needed
        self.sources_db_id = sources_db_id
        
        # Fetch data source ID for sources database
        self.sources_data_source_id = self._get_data_source_id(sources_db_id)
        
        # Cache property names
        self._name_property = None
        self._url_property = None
        self._source_type_property = None
        self._active_property = None
        self._last_processed_property = None
        self._processed_video_ids_property = None
    
    def _get_data_source_id(self, database_id: str) -> str:
        """
        Get the data source ID for a database.
        
        According to Notion API 2025-09-03, databases can have multiple data sources.
        For single-source databases (most common case), we use the first data source.
        
        Args:
            database_id: Database ID
            
        Returns:
            Data source ID
        """
        try:
            response = self.client.databases.retrieve(database_id=database_id)
            data_sources = response.get("data_sources", [])
            
            if not data_sources:
                logger.warning(f"No data sources found for database {database_id}, using database_id as fallback")
                return database_id
            
            # For single-source databases, use the first (and only) data source
            data_source_id = data_sources[0]["id"]
            logger.info(f"Found data source {data_source_id} for database {database_id}")
            return data_source_id
            
        except Exception as e:
            logger.error(f"Error fetching data source ID for database {database_id}: {e}")
            # Fallback to database_id if data source fetch fails
            logger.warning(f"Falling back to database_id: {database_id}")
            return database_id
    
    def _get_property_names(self) -> Dict[str, str]:
        """
        Get property names from the database/data source.
        Caches the result for performance.
        
        Returns:
            Dictionary mapping property types to property names
        """
        if self._name_property is not None:
            return {
                'name': self._name_property,
                'url': self._url_property,
                'source_type': self._source_type_property,
                'active': self._active_property,
                'last_processed': self._last_processed_property,
                'processed_video_ids': self._processed_video_ids_property
            }
        
        try:
            # Get properties from data source or database
            if self.sources_data_source_id == self.sources_db_id:
                # Fallback: get from database
                db = self.client.databases.retrieve(database_id=self.sources_db_id)
                properties = db.get("properties", {})
            else:
                # Get from data source
                ds = self.client.data_sources.retrieve(data_source_id=self.sources_data_source_id)
                properties = ds.get("properties", {})
            
            # Find properties by type
            for prop_name, prop_def in properties.items():
                prop_type = prop_def.get("type")
                
                if prop_type == "title":
                    self._name_property = prop_name
                elif prop_type == "url":
                    self._url_property = prop_name
                elif prop_type == "select":
                    self._source_type_property = prop_name
                elif prop_type == "checkbox":
                    self._active_property = prop_name
                elif prop_type == "date":
                    # Could be "Last Processed" or other date fields
                    if "processed" in prop_name.lower() or "last" in prop_name.lower():
                        self._last_processed_property = prop_name
                elif prop_type == "rich_text":
                    # Could be "Processed Video IDs" or other text fields
                    if "video" in prop_name.lower() or "processed" in prop_name.lower():
                        self._processed_video_ids_property = prop_name
            
            # Set defaults if not found
            if not self._name_property:
                self._name_property = "Name"
            if not self._url_property:
                self._url_property = "URL"
            if not self._source_type_property:
                self._source_type_property = "Source Type"
            if not self._active_property:
                self._active_property = "Active"
            if not self._last_processed_property:
                self._last_processed_property = "Last Processed"
            if not self._processed_video_ids_property:
                self._processed_video_ids_property = "Processed Video IDs"
            
            logger.debug(f"Property names: name={self._name_property}, url={self._url_property}, "
                        f"source_type={self._source_type_property}, active={self._active_property}, "
                        f"last_processed={self._last_processed_property}, "
                        f"processed_video_ids={self._processed_video_ids_property}")
            
            return {
                'name': self._name_property,
                'url': self._url_property,
                'source_type': self._source_type_property,
                'active': self._active_property,
                'last_processed': self._last_processed_property,
                'processed_video_ids': self._processed_video_ids_property
            }
            
        except Exception as e:
            logger.warning(f"Error detecting property names: {e}, using defaults")
            # Return defaults
            return {
                'name': "Name",
                'url': "URL",
                'source_type': "Source Type",
                'active': "Active",
                'last_processed': "Last Processed",
                'processed_video_ids': "Processed Video IDs"
            }
    
    def _get_property_value(self, properties: Dict, prop_name: str, prop_type: str):
        """
        Extract property value from Notion properties.
        
        Args:
            properties: Notion properties dictionary
            prop_name: Property name
            prop_type: Expected property type
            
        Returns:
            Extracted value or None
        """
        prop = properties.get(prop_name, {})
        
        if prop_type == "url":
            return prop.get("url", "")
        elif prop_type == "select":
            select_obj = prop.get("select", {})
            return select_obj.get("name", "") if select_obj else ""
        elif prop_type == "rich_text":
            rich_text = prop.get("rich_text", [])
            if rich_text:
                return rich_text[0].get("text", {}).get("content", "")
            return ""
        elif prop_type == "date":
            date_obj = prop.get("date", {})
            return date_obj.get("start", "") if date_obj else None
        elif prop_type == "checkbox":
            return prop.get("checkbox", False)
        elif prop_type == "title":
            title = prop.get("title", [])
            if title:
                return title[0].get("text", {}).get("content", "")
            return ""
        
        return None
    
    def get_sources(self) -> List[Dict]:
        """
        Get all active sources from Notion.
        
        Returns:
            List of source dictionaries with id, url, source_type, last_processed, processed_video_ids
        """
        try:
            prop_names = self._get_property_names()
            logger.info(f"Using property names: Active='{prop_names['active']}', URL='{prop_names['url']}', "
                       f"Source Type='{prop_names['source_type']}'")
            
            # First, get ALL sources (without filter) to see what we have
            logger.info("Fetching all sources from Notion database...")
            if self.sources_data_source_id == self.sources_db_id:
                all_response = self.client.databases.query(database_id=self.sources_db_id)
            else:
                if hasattr(self.client, 'data_sources') and hasattr(self.client.data_sources, 'query'):
                    all_response = self.client.data_sources.query(data_source_id=self.sources_data_source_id)
                else:
                    import requests
                    headers = {
                        "Authorization": f"Bearer {self.api_token}",
                        "Notion-Version": "2025-09-03",
                        "Content-Type": "application/json"
                    }
                    all_response = requests.post(
                        f"https://api.notion.com/v1/data_sources/{self.sources_data_source_id}/query",
                        headers=headers,
                        json={}
                    ).json()
            
            all_results = all_response.get("results", [])
            logger.info(f"Found {len(all_results)} total sources in database")
            
            # Log all sources found (for debugging)
            for idx, page in enumerate(all_results, 1):
                properties = page.get("properties", {})
                page_id = page.get("id")
                name = self._get_property_value(properties, prop_names['name'], "title")
                url = self._get_property_value(properties, prop_names['url'], "url")
                source_type = self._get_property_value(properties, prop_names['source_type'], "select")
                active = self._get_property_value(properties, prop_names['active'], "checkbox")
                logger.info(f"  Source {idx}: '{name}' | Type: {source_type} | URL: {url} | Active: {active}")
            
            # Query for active sources only
            filter_dict = {
                "property": prop_names['active'],
                "checkbox": {
                    "equals": True
                }
            }
            
            logger.info(f"Filtering for active sources (where '{prop_names['active']}' = True)...")
            
            # Use data source query (API 2025-09-03)
            if self.sources_data_source_id == self.sources_db_id:
                # Fallback: use old database query API
                response = self.client.databases.query(
                    database_id=self.sources_db_id,
                    filter=filter_dict
                )
            else:
                # New API: use data source query
                if hasattr(self.client, 'data_sources') and hasattr(self.client.data_sources, 'query'):
                    response = self.client.data_sources.query(
                        data_source_id=self.sources_data_source_id,
                        filter=filter_dict
                    )
                else:
                    # Manual request for SDK versions that don't have data_sources.query yet
                    import requests
                    headers = {
                        "Authorization": f"Bearer {self.api_token}",
                        "Notion-Version": "2025-09-03",
                        "Content-Type": "application/json"
                    }
                    response = requests.post(
                        f"https://api.notion.com/v1/data_sources/{self.sources_data_source_id}/query",
                        headers=headers,
                        json={"filter": filter_dict}
                    ).json()
            
            results = response.get("results", [])
            sources = []
            
            for page in results:
                properties = page.get("properties", {})
                page_id = page.get("id")
                
                # Extract property values
                name = self._get_property_value(properties, prop_names['name'], "title")
                url = self._get_property_value(properties, prop_names['url'], "url")
                source_type = self._get_property_value(properties, prop_names['source_type'], "select")
                last_processed = self._get_property_value(properties, prop_names['last_processed'], "date")
                processed_video_ids_str = self._get_property_value(properties, prop_names['processed_video_ids'], "rich_text")
                
                # Parse processed_video_ids from comma-separated string to list
                processed_video_ids = []
                if processed_video_ids_str:
                    processed_video_ids = [vid.strip() for vid in processed_video_ids_str.split(',') if vid.strip()]
                
                sources.append({
                    'id': page_id,  # Use Notion page ID as source ID
                    'url': url,
                    'source_type': source_type,
                    'last_processed': last_processed,
                    'processed_video_ids': processed_video_ids
                })
                
                logger.info(f"  ✓ Active source: '{name}' ({source_type}) - {url}")
            
            logger.info(f"Retrieved {len(sources)} active sources from Notion")
            return sources
            
        except Exception as e:
            logger.error(f"Error retrieving sources from Notion: {e}")
            import traceback
            logger.debug(f"Full error traceback: {traceback.format_exc()}")
            raise
    
    def update_source_last_processed(self, source_id: str, processed_video_ids: Optional[List[str]] = None) -> None:
        """
        Update source's last processed date and processed video IDs in Notion.
        
        Args:
            source_id: Source ID (Notion page ID, from get_sources())
            processed_video_ids: Optional list of processed video IDs (for YouTube channels)
        """
        try:
            prop_names = self._get_property_names()
            
            # Prepare update properties
            update_properties = {
                prop_names['last_processed']: {
                    "date": {
                        "start": datetime.now().isoformat()
                    }
                }
            }
            
            # Update processed video IDs if provided
            if processed_video_ids is not None:
                # Convert list to comma-separated string
                processed_video_ids_str = ", ".join(processed_video_ids)
                update_properties[prop_names['processed_video_ids']] = {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": processed_video_ids_str
                            }
                        }
                    ]
                }
            
            # Update the page
            self.client.pages.update(
                page_id=source_id,
                properties=update_properties
            )
            
            logger.info(f"Updated source {source_id} last processed date in Notion")
            
        except Exception as e:
            logger.error(f"Error updating source {source_id} in Notion: {e}")
            import traceback
            logger.debug(f"Full error traceback: {traceback.format_exc()}")
            raise

