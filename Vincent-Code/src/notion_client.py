"""Notion API client for optional backup of processed transcripts."""

import os
from datetime import datetime
from typing import List, Dict, Optional
from notion_client import Client
import logging
import json

logger = logging.getLogger(__name__)


class NotionClient:
    """Client for optional backup of processed transcripts to Notion."""
    
    def __init__(self, api_token: str, transcripts_db_id: str):
        """
        Initialize Notion client with API version 2025-09-03.
        
        Args:
            api_token: Notion API token
            transcripts_db_id: Database ID for transcripts (optional backup)
        """
        self.client = Client(auth=api_token, notion_version="2025-09-03")
        self.api_token = api_token  # Store for manual requests if needed
        self.transcripts_db_id = transcripts_db_id
        
        # Fetch data source ID for transcripts database
        self.transcripts_data_source_id = self._get_data_source_id(transcripts_db_id)
        
        # Cache the title property name for transcripts database
        self._transcripts_title_property = None
    
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
    
    def _get_title_property_name(self) -> str:
        """
        Get the name of the title property in the transcripts database.
        Caches the result for performance.
        
        Returns:
            Name of the title property (e.g., "Title" or "Name")
        """
        if self._transcripts_title_property is not None:
            return self._transcripts_title_property
        
        try:
            # Get data source properties
            if self.transcripts_data_source_id == self.transcripts_db_id:
                # Fallback: get from database
                db = self.client.databases.retrieve(database_id=self.transcripts_db_id)
                properties = db.get("properties", {})
            else:
                # Get from data source
                ds = self.client.data_sources.retrieve(data_source_id=self.transcripts_data_source_id)
                properties = ds.get("properties", {})
            
            # Find the title property
            for prop_name, prop_def in properties.items():
                if prop_def.get("type") == "title":
                    self._transcripts_title_property = prop_name
                    logger.debug(f"Found title property: '{prop_name}'")
                    return prop_name
            
            # Default to "Title" if not found
            logger.warning("No title property found, defaulting to 'Title'")
            self._transcripts_title_property = "Title"
            return "Title"
            
        except Exception as e:
            logger.warning(f"Error detecting title property: {e}, defaulting to 'Title'")
            self._transcripts_title_property = "Title"
            return "Title"
    
    def save_processed_text(self, title: str, content: str, source_url: str, 
                            source_type: str, save_content: bool = False) -> Optional[str]:
        """
        Save processed text content to Notion (optional backup).
        By default, only saves metadata (no content) to avoid Notion block limits.
        Set save_content=True to save content (will truncate if too long).
        
        Args:
            title: Title of the transcript
            content: Processed transcript content
            source_url: Original source URL
            source_type: Type of source (YouTube/Blog/RSS)
            save_content: Whether to save content blocks (default: False, metadata only)
            
        Returns:
            Page ID of created transcript, or None if failed
        """
        try:
            # Get the actual title property name from the database
            title_prop_name = self._get_title_property_name()
            
            properties = {
                title_prop_name: {
                    "title": [
                        {
                            "text": {
                                "content": title[:2000]  # Notion title limit
                            }
                        }
                    ]
                },
                "Source URL": {
                    "url": source_url
                },
                "Source Type": {
                    "select": {
                        "name": source_type
                    }
                },
                "Date Added": {
                    "date": {
                        "start": datetime.now().isoformat()
                    }
                },
                "Processed Date": {
                    "date": {
                        "start": datetime.now().isoformat()
                    }
                }
            }
            
            # Only add content blocks if requested and content is not too long
            content_blocks = []
            if save_content:
                content_blocks = self._text_to_blocks(content)
                # Notion has a limit of 100 children blocks per page creation
                # If content is too long, truncate to first 100 blocks
                if len(content_blocks) > 100:
                    logger.warning(f"Content too long ({len(content_blocks)} blocks), truncating to 100 blocks")
                    content_blocks = content_blocks[:100]
            
            # Use data_source_id instead of database_id (API 2025-09-03)
            # Note: If data_source_id fetch failed and we're using database_id as fallback,
            # we need to use database_id parent type instead
            if self.transcripts_data_source_id == self.transcripts_db_id:
                # Fallback: using database_id (old API)
                parent = {"type": "database_id", "database_id": self.transcripts_db_id}
            else:
                # New API: using data_source_id
                parent = {"type": "data_source_id", "data_source_id": self.transcripts_data_source_id}
            
            # Create the transcript page (metadata only by default)
            page = self.client.pages.create(
                parent=parent,
                properties=properties,
                children=content_blocks
            )
            
            page_id = page["id"]
            if save_content:
                logger.info(f"Saved processed text to Notion backup: {title}")
            else:
                logger.info(f"Saved transcript metadata to Notion: {title}")
            return page_id
            
        except Exception as e:
            logger.warning(f"Error saving processed text to Notion backup: {e}")
            return None
    
    def transcript_exists(self, source_url: str) -> bool:
        """
        Check if a transcript already exists for a given source URL.
        
        Args:
            source_url: Source URL to check
            
        Returns:
            True if transcript exists, False otherwise
        """
        try:
            # Use data source query (API 2025-09-03)
            # SDK v5+ should support data_sources.query method
            # If data_source_id equals database_id (fallback case), use old API
            if self.transcripts_data_source_id == self.transcripts_db_id:
                # Fallback: use old database query API
                response = self.client.databases.query(
                    database_id=self.transcripts_db_id,
                    filter={
                        "property": "Source URL",
                        "url": {
                            "equals": source_url
                        }
                    }
                )
            else:
                # New API: use data source query
                # Try SDK v5 method first, fallback to manual request if needed
                if hasattr(self.client, 'data_sources') and hasattr(self.client.data_sources, 'query'):
                    response = self.client.data_sources.query(
                        data_source_id=self.transcripts_data_source_id,
                        filter={
                            "property": "Source URL",
                            "url": {
                                "equals": source_url
                            }
                        }
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
                        f"https://api.notion.com/v1/data_sources/{self.transcripts_data_source_id}/query",
                        headers=headers,
                        json={
                            "filter": {
                                "property": "Source URL",
                                "url": {
                                    "equals": source_url
                                }
                            }
                        }
                    ).json()
            
            return len(response.get("results", [])) > 0
            
        except Exception as e:
            logger.error(f"Error checking if transcript exists: {e}")
            return False
    
    def get_transcript_by_url(self, source_url: str) -> Optional[Dict]:
        """
        Get transcript page from Notion by source URL.
        
        Args:
            source_url: Source URL to look up
            
        Returns:
            Dictionary with page_id, title, embeddings_ready status, or None if not found
        """
        try:
            if self.transcripts_data_source_id == self.transcripts_db_id:
                response = self.client.databases.query(
                    database_id=self.transcripts_db_id,
                    filter={
                        "property": "Source URL",
                        "url": {
                            "equals": source_url
                        }
                    }
                )
            else:
                if hasattr(self.client, 'data_sources') and hasattr(self.client.data_sources, 'query'):
                    response = self.client.data_sources.query(
                        data_source_id=self.transcripts_data_source_id,
                        filter={
                            "property": "Source URL",
                            "url": {
                                "equals": source_url
                            }
                        }
                    )
                else:
                    import requests
                    headers = {
                        "Authorization": f"Bearer {self.api_token}",
                        "Notion-Version": "2025-09-03",
                        "Content-Type": "application/json"
                    }
                    response = requests.post(
                        f"https://api.notion.com/v1/data_sources/{self.transcripts_data_source_id}/query",
                        headers=headers,
                        json={
                            "filter": {
                                "property": "Source URL",
                                "url": {
                                    "equals": source_url
                                }
                            }
                        }
                    ).json()
            
            results = response.get("results", [])
            if not results:
                return None
            
            page = results[0]
            properties = page.get("properties", {})
            
            # Extract values
            title_prop_name = self._get_title_property_name()
            title = self._get_property_value(properties, title_prop_name, "title")
            embeddings_ready = self._get_property_value(properties, "Embeddings Ready", "checkbox")
            source_type = self._get_property_value(properties, "Source Type", "select")
            
            return {
                "page_id": page.get("id"),
                "title": title,
                "source_url": source_url,
                "source_type": source_type,
                "embeddings_ready": embeddings_ready if embeddings_ready is not None else False
            }
            
        except Exception as e:
            logger.error(f"Error getting transcript by URL: {e}")
            return None
    
    def update_embeddings_status(self, page_id: str, embeddings_ready: bool = True) -> bool:
        """
        Update the "Embeddings Ready" status for a transcript page.
        
        Args:
            page_id: Notion page ID of the transcript
            embeddings_ready: Whether embeddings are ready (default: True)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.client.pages.update(
                page_id=page_id,
                properties={
                    "Embeddings Ready": {
                        "checkbox": embeddings_ready
                    }
                }
            )
            logger.info(f"Updated embeddings status for page {page_id}: {embeddings_ready}")
            return True
        except Exception as e:
            logger.error(f"Error updating embeddings status for page {page_id}: {e}")
            return False
    
    def summary_exists(self, source_url: str) -> bool:
        """
        Check if a summary already exists for a given source URL by checking
        the "Summary Ready" property in the Processed Transcripts database.
        
        Args:
            source_url: Source URL to check
            
        Returns:
            True if summary exists (Summary Ready = True), False otherwise
        """
        try:
            transcript_info = self.get_transcript_by_url(source_url)
            if not transcript_info:
                return False
            
            # Check if "Summary Ready" property exists and is True
            # We need to get the full page to check the property
            page_id = transcript_info['page_id']
            page = self.client.pages.retrieve(page_id=page_id)
            properties = page.get("properties", {})
            
            summary_ready = self._get_property_value(properties, "Summary Ready", "checkbox")
            return summary_ready is True
            
        except Exception as e:
            logger.debug(f"Error checking if summary exists for {source_url}: {e}")
            return False
    
    def update_summary_status(self, page_id: str, summary_ready: bool = True) -> bool:
        """
        Update the "Summary Ready" status for a transcript page.
        
        Args:
            page_id: Notion page ID of the transcript
            summary_ready: Whether summary is ready (default: True)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.client.pages.update(
                page_id=page_id,
                properties={
                    "Summary Ready": {
                        "checkbox": summary_ready
                    }
                }
            )
            logger.info(f"Updated summary status for page {page_id}: {summary_ready}")
            return True
        except Exception as e:
            logger.error(f"Error updating summary status for page {page_id}: {e}")
            return False
    
    def get_all_transcripts(self) -> List[Dict]:
        """
        Get all transcripts from the database.
        
        Returns:
            List of transcript dictionaries with page_id, title, source_url, source_type, embeddings_ready
        """
        try:
            # Query for all transcripts (empty filter)
            if self.transcripts_data_source_id == self.transcripts_db_id:
                response = self.client.databases.query(database_id=self.transcripts_db_id)
            else:
                if hasattr(self.client, 'data_sources') and hasattr(self.client.data_sources, 'query'):
                    response = self.client.data_sources.query(data_source_id=self.transcripts_data_source_id)
                else:
                    import requests
                    headers = {
                        "Authorization": f"Bearer {self.api_token}",
                        "Notion-Version": "2025-09-03",
                        "Content-Type": "application/json"
                    }
                    response = requests.post(
                        f"https://api.notion.com/v1/data_sources/{self.transcripts_data_source_id}/query",
                        headers=headers,
                        json={}
                    ).json()
            
            results = response.get("results", [])
            transcripts = []
            title_prop_name = self._get_title_property_name()
            
            for page in results:
                properties = page.get("properties", {})
                title = self._get_property_value(properties, title_prop_name, "title")
                source_url = self._get_property_value(properties, "Source URL", "url")
                source_type = self._get_property_value(properties, "Source Type", "select")
                embeddings_ready = self._get_property_value(properties, "Embeddings Ready", "checkbox")
                
                if not source_url:
                    continue  # Skip entries without source URL
                
                transcripts.append({
                    "page_id": page.get("id"),
                    "title": title,
                    "source_url": source_url,
                    "source_type": source_type,
                    "embeddings_ready": embeddings_ready if embeddings_ready is not None else False
                })
            
            logger.info(f"Found {len(transcripts)} transcripts in database")
            return transcripts
            
        except Exception as e:
            logger.error(f"Error getting all transcripts: {e}")
            return []
    
    def get_transcripts_needing_embeddings(self) -> List[Dict]:
        """
        Get all transcripts that don't have embeddings ready yet.
        
        Returns:
            List of transcript dictionaries with page_id, title, source_url, source_type
        """
        try:
            # Query for transcripts where "Embeddings Ready" is False
            # Note: Checkboxes can't be "empty" in Notion - they're either True or False
            # So we just check for False (which includes unset checkboxes that default to False)
            filter_dict = {
                "property": "Embeddings Ready",
                "checkbox": {
                    "equals": False
                }
            }
            
            if self.transcripts_data_source_id == self.transcripts_db_id:
                response = self.client.databases.query(
                    database_id=self.transcripts_db_id,
                    filter=filter_dict
                )
            else:
                if hasattr(self.client, 'data_sources') and hasattr(self.client.data_sources, 'query'):
                    response = self.client.data_sources.query(
                        data_source_id=self.transcripts_data_source_id,
                        filter=filter_dict
                    )
                else:
                    import requests
                    headers = {
                        "Authorization": f"Bearer {self.api_token}",
                        "Notion-Version": "2025-09-03",
                        "Content-Type": "application/json"
                    }
                    response = requests.post(
                        f"https://api.notion.com/v1/data_sources/{self.transcripts_data_source_id}/query",
                        headers=headers,
                        json={"filter": filter_dict}
                    ).json()
            
            results = response.get("results", [])
            transcripts = []
            title_prop_name = self._get_title_property_name()
            
            for page in results:
                properties = page.get("properties", {})
                title = self._get_property_value(properties, title_prop_name, "title")
                source_url = self._get_property_value(properties, "Source URL", "url")
                source_type = self._get_property_value(properties, "Source Type", "select")
                
                transcripts.append({
                    "page_id": page.get("id"),
                    "title": title,
                    "source_url": source_url,
                    "source_type": source_type
                })
            
            logger.info(f"Found {len(transcripts)} transcripts needing embeddings")
            return transcripts
            
        except Exception as e:
            logger.error(f"Error getting transcripts needing embeddings: {e}")
            return []
    
    def _get_property_value(self, properties: Dict, prop_name: str, prop_type: str):
        """Extract property value from Notion properties."""
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
            return date_obj.get("start", "") if date_obj else ""
        elif prop_type == "checkbox":
            return prop.get("checkbox", False)
        
        return None
    
    def _text_to_blocks(self, text: str) -> List[Dict]:
        """Convert text to Notion content blocks."""
        # Notion has a strict limit of 2000 characters per text block
        # Use 1999 to ensure we're always under the limit
        max_chunk_size = 1999
        chunks = []
        
        # Split text into chunks, ensuring each chunk is ≤ max_chunk_size
        # First, try to split by paragraphs for better readability
        paragraphs = text.split("\n\n")
        current_chunk = ""
        
        for para in paragraphs:
            # If paragraph itself exceeds limit, split it further
            if len(para) > max_chunk_size:
                # Save current chunk if it exists
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = ""
                
                # Split the long paragraph into smaller chunks
                para_chunks = self._split_text(para, max_chunk_size)
                chunks.extend(para_chunks)
            else:
                # Calculate separator length (2 for "\n\n" if current_chunk exists)
                separator_len = 2 if current_chunk else 0
                potential_length = len(current_chunk) + separator_len + len(para)
                
                if potential_length > max_chunk_size:
                    # Current chunk + new paragraph would exceed limit
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    # If para itself fits, use it; otherwise split it
                    if len(para) <= max_chunk_size:
                        current_chunk = para
                    else:
                        para_chunks = self._split_text(para, max_chunk_size)
                        chunks.extend(para_chunks[:-1])  # Add all but last
                        current_chunk = para_chunks[-1] if para_chunks else ""
                else:
                    # Add paragraph to current chunk
                    current_chunk += "\n\n" + para if current_chunk else para
        
        # Add remaining chunk
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        # Convert to Notion blocks with strict validation
        blocks = []
        for chunk in chunks:
            # Ensure chunk is within limit - split if necessary
            # Use a more aggressive approach: split any chunk that's >= 2000
            if len(chunk) >= 2000:
                # Split into smaller chunks
                sub_chunks = self._split_text(chunk, max_chunk_size)
                for sub_chunk in sub_chunks:
                    # Double-check: ensure sub_chunk is strictly < 2000
                    final_chunk = sub_chunk[:max_chunk_size] if len(sub_chunk) > max_chunk_size else sub_chunk
                    if len(final_chunk) > 0:  # Only add non-empty chunks
                        blocks.append({
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": [
                                    {
                                        "type": "text",
                                        "text": {
                                            "content": final_chunk
                                        }
                                    }
                                ]
                            }
                        })
            else:
                # Chunk is within limit, but verify it's not exactly 2000
                safe_chunk = chunk[:max_chunk_size] if len(chunk) > max_chunk_size else chunk
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": safe_chunk
                                }
                            }
                        ]
                    }
                })
        
        return blocks
    
    def _split_text(self, text: str, max_size: int) -> List[str]:
        """
        Split text into chunks of max_size characters (strictly < max_size+1).
        Tries to split at word boundaries when possible.
        """
        chunks = []
        
        # If text is already small enough, return as-is
        if len(text) <= max_size:
            return [text]
        
        # Try to split at word boundaries first
        words = text.split()
        current_chunk = ""
        
        for word in words:
            # Check if adding this word would exceed limit
            space_needed = 1 if current_chunk else 0
            potential_chunk = current_chunk + (" " * space_needed) + word
            
            if len(potential_chunk) <= max_size:
                current_chunk = potential_chunk
            else:
                # Save current chunk and start new one
                if current_chunk:
                    chunks.append(current_chunk)
                # If single word exceeds limit, split it character-wise
                if len(word) > max_size:
                    # Split word into character chunks (strictly max_size)
                    for i in range(0, len(word), max_size):
                        chunk = word[i:i + max_size]
                        if chunk:  # Only add non-empty chunks
                            chunks.append(chunk)
                    current_chunk = ""
                else:
                    current_chunk = word
        
        # Add remaining chunk
        if current_chunk:
            chunks.append(current_chunk)
        
        # Final validation: ensure all chunks are <= max_size
        validated_chunks = []
        for chunk in chunks:
            if len(chunk) > max_size:
                # Split further if somehow still too large
                for i in range(0, len(chunk), max_size):
                    sub_chunk = chunk[i:i + max_size]
                    if sub_chunk:
                        validated_chunks.append(sub_chunk)
            else:
                validated_chunks.append(chunk)
        
        return validated_chunks
    
    def _split_rich_text(self, text: str, max_length: int = 2000) -> List[Dict]:
        """
        Split text into multiple rich_text segments to comply with Notion's 2000 character limit.
        
        Args:
            text: Text to split
            max_length: Maximum length per segment (default: 2000)
        
        Returns:
            List of rich_text segment dictionaries
        """
        if not text:
            return []
        
        segments = []
        # Split text into chunks of max_length
        for i in range(0, len(text), max_length):
            chunk = text[i:i + max_length]
            segments.append({
                "type": "text",
                "text": {
                    "content": chunk
                }
            })
        
        return segments
    
    def save_processed_script(self, title: str, source_content_id: str, 
                             original_script: str, processed_script: str,
                             links_count: int, processed_scripts_db_id: str) -> Optional[str]:
        """
        Save processed script tracking record to Processed Scripts database.
        Note: Scripts are stored in Obsidian, Notion only tracks metadata.
        
        Args:
            title: Title of the processed script
            source_content_id: Page ID from Contenido database
            original_script: Original script content (not stored in Notion, kept for compatibility)
            processed_script: Processed script with links added (not stored in Notion, kept for compatibility)
            links_count: Number of Perplexity links added
            processed_scripts_db_id: Processed Scripts database ID
        
        Returns:
            Page ID of created tracking record, or None if failed
        """
        try:
            # Get data source ID for processed scripts database
            processed_scripts_data_source_id = self._get_data_source_id(processed_scripts_db_id)
            
            # Get title property name
            if processed_scripts_data_source_id == processed_scripts_db_id:
                db = self.client.databases.retrieve(database_id=processed_scripts_db_id)
                properties = db.get("properties", {})
            else:
                ds = self.client.data_sources.retrieve(data_source_id=processed_scripts_data_source_id)
                properties = ds.get("properties", {})
            
            title_prop_name = "Title"
            for prop_name, prop_def in properties.items():
                if prop_def.get("type") == "title":
                    title_prop_name = prop_name
                    break
            
            # Build properties - only metadata, no script content
            page_properties = {
                title_prop_name: {
                    "title": [
                        {
                            "text": {
                                "content": title[:2000]  # Notion title limit
                            }
                        }
                    ]
                },
                "Processing Date": {
                    "date": {
                        "start": datetime.now().isoformat()
                    }
                },
                "Status": {
                    "select": {
                        "name": "Completed"
                    }
                },
                "Perplexity Links Count": {
                    "number": links_count
                }
            }
            
            # Add relation to source content if relation property exists
            if "Source Content ID" in properties:
                page_properties["Source Content ID"] = {
                    "relation": [
                        {
                            "id": source_content_id
                        }
                    ]
                }
            
            # Determine parent type
            if processed_scripts_data_source_id == processed_scripts_db_id:
                parent = {"type": "database_id", "database_id": processed_scripts_db_id}
            else:
                parent = {"type": "data_source_id", "data_source_id": processed_scripts_data_source_id}
            
            # Create the page with just metadata (no content blocks)
            page = self.client.pages.create(
                parent=parent,
                properties=page_properties
            )
            
            page_id = page["id"]
            logger.info(f"Saved processed script tracking to Notion: {title} (Page ID: {page_id})")
            return page_id
            
        except Exception as e:
            logger.error(f"Error saving processed script tracking to Notion: {e}")
            return None
    
    def update_content_status(self, page_id: str, new_status: str, contenido_db_id: str = None) -> bool:
        """
        Update Estado property in Contenido database.
        
        Args:
            page_id: Notion page ID from Contenido database
            new_status: New status value (e.g., "Editando")
            contenido_db_id: Optional Contenido database ID (for validation)
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Detect Estado property name and type
            estado_property_name = "Estado"
            estado_property_type = "select"  # default
            
            if contenido_db_id:
                # Try to get property name and type from database
                try:
                    db = self.client.databases.retrieve(database_id=contenido_db_id)
                    data_sources = db.get("data_sources", [])
                    
                    if data_sources:
                        ds = self.client.data_sources.retrieve(data_source_id=data_sources[0]["id"])
                        properties = ds.get("properties", {})
                    else:
                        properties = db.get("properties", {})
                    
                    for prop_name, prop_def in properties.items():
                        prop_type = prop_def.get("type", "")
                        if prop_type in ["select", "status"] and prop_name.lower() in ["estado", "status", "state"]:
                            estado_property_name = prop_name
                            estado_property_type = prop_type
                            break
                except Exception as e:
                    logger.warning(f"Could not detect Estado property name/type: {e}, using default")
            
            # Build properties update with correct format based on property type
            if estado_property_type == "status":
                properties_to_update = {
                    estado_property_name: {
                        "status": {
                            "name": new_status
                        }
                    }
                }
            else:
                # Default to select format
                properties_to_update = {
                    estado_property_name: {
                        "select": {
                            "name": new_status
                        }
                    }
                }
            
            # Update the page
            self.client.pages.update(
                page_id=page_id,
                properties=properties_to_update
            )
            
            logger.info(f"Updated status for page {page_id} to '{new_status}' (using {estado_property_type} format)")
            return True
            
        except Exception as e:
            logger.error(f"Error updating content status for page {page_id}: {e}")
            return False

