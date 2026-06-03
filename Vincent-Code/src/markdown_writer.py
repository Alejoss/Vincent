"""Markdown writer for Obsidian-compatible transcript files."""

import os
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)


class MarkdownWriter:
    """
    Writes processed content as Obsidian-compatible markdown files.
    Used for transcripts (main.py → 10_Sources/Transcripts) and scripts (process_scripts.py → 10_Sources/Own Scripts).
    """
    
    def __init__(self, vault_path: str = "./obsidian", folder_name: str = "Own Scripts"):
        """
        Initialize markdown writer.
        
        Args:
            vault_path: Path to Obsidian vault root directory (e.g. Cerebro-Vincent).
            folder_name: Subfolder under 10_Sources (e.g. "Transcripts" or "Own Scripts"). Default: "Own Scripts".
        """
        self.vault_path = Path(vault_path)
        self.transcripts_dir = self.vault_path / "10_Sources" / folder_name
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Markdown writer initialized. Scripts will be saved to: {self.transcripts_dir}")
    
    def _slugify(self, text: str, max_length: int = 100) -> str:
        """
        Convert text to URL-friendly slug.
        
        Args:
            text: Text to slugify
            max_length: Maximum length of slug
            
        Returns:
            URL-friendly slug
        """
        # Remove special characters and convert to lowercase
        slug = re.sub(r'[^\w\s-]', '', text.lower())
        # Replace spaces and multiple dashes with single dash
        slug = re.sub(r'[-\s]+', '-', slug)
        # Remove leading/trailing dashes
        slug = slug.strip('-')
        # Truncate to max_length
        if len(slug) > max_length:
            slug = slug[:max_length].rstrip('-')
        return slug
    
    def _create_frontmatter(self, title: str, source_url: str, source_type: str, 
                           upload_date: Optional[str] = None,
                           processed_date: Optional[str] = None,
                           language_code: Optional[str] = None) -> str:
        """
        Create YAML frontmatter for Obsidian note.
        
        Args:
            title: Title of the transcript
            source_url: Original source URL
            source_type: Type of source (YouTube/Blog/RSS)
            upload_date: Date when the content was originally published/uploaded (ISO format)
            processed_date: Date when processed by this pipeline (ISO format)
            language_code: Language code (e.g., 'en', 'es') from source API
            
        Returns:
            YAML frontmatter string
        """
        if processed_date is None:
            processed_date = datetime.now().isoformat()
        
        # Determine tags based on source type
        tags = ["transcript", "source"]
        if source_type.lower() == "youtube":
            tags.append("youtube")
        elif source_type.lower() == "blog":
            tags.append("blog")
        elif source_type.lower() == "rss":
            tags.append("rss")
        
        # Build frontmatter - only include uploaded_date if we have it
        # Escape quotes in title for YAML
        escaped_title = title.replace('"', '\\"')
        frontmatter_lines = [
            "---",
            f'title: "{escaped_title}"',
            f'source_url: "{source_url}"',
            f'source_type: "{source_type}"',
        ]
        
        # Only add uploaded_date if we have an actual upload date
        if upload_date:
            frontmatter_lines.append(f'uploaded_date: "{upload_date}"')
        
        frontmatter_lines.append(f'processed_date: "{processed_date}"')
        
        # Add language_code if available
        if language_code:
            frontmatter_lines.append(f'language_code: "{language_code}"')
        
        frontmatter_lines.append(f"tags: {tags}")
        frontmatter_lines.append("---")
        frontmatter_lines.append("")
        
        frontmatter = "\n".join(frontmatter_lines) + "\n"
        return frontmatter
    
    def save_transcript(self, title: str, content: str, source_url: str, 
                       source_type: str, upload_date: Optional[str] = None,
                       processed_date: Optional[str] = None,
                       language_code: Optional[str] = None) -> str:
        """
        Save processed transcript as Obsidian markdown file.
        
        Args:
            title: Title of the transcript
            content: Processed transcript content
            source_url: Original source URL
            source_type: Type of source (YouTube/Blog/RSS)
            upload_date: Date when the content was originally published/uploaded (ISO format)
            processed_date: Date when processed by this pipeline (ISO format)
            language_code: Language code (e.g., 'en', 'es') from source API
            
        Returns:
            Path to the created markdown file
        """
        try:
            # Generate filename: YYYY-MM-DD-title-slug.md
            # Use upload_date for filename if available, otherwise use processed_date
            date_for_filename = upload_date if upload_date else processed_date
            if date_for_filename:
                try:
                    date_obj = datetime.fromisoformat(date_for_filename.replace('Z', '+00:00'))
                except:
                    date_obj = datetime.now()
            else:
                date_obj = datetime.now()
            
            date_str = date_obj.strftime("%Y-%m-%d")
            title_slug = self._slugify(title)
            filename = f"{date_str}-{title_slug}.md"
            
            file_path = self.transcripts_dir / filename
            
            # Handle duplicate filenames
            counter = 1
            original_path = file_path
            while file_path.exists():
                name_part = original_path.stem
                file_path = self.transcripts_dir / f"{name_part}-{counter}.md"
                counter += 1
            
            # Create frontmatter
            frontmatter = self._create_frontmatter(title, source_url, source_type, upload_date, processed_date, language_code)
            
            # Create content (source_url is already in frontmatter, no need to repeat)
            obsidian_content = f"{frontmatter}{content}"
            
            # Write file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(obsidian_content)
            
            logger.info(f"Saved transcript to Obsidian: {file_path}")
            return str(file_path)
            
        except Exception as e:
            logger.error(f"Error saving transcript to markdown: {e}")
            raise
    
    def transcript_exists(self, source_url: str) -> bool:
        """
        Check if a transcript already exists for a given source URL.
        
        Args:
            source_url: Source URL to check
            
        Returns:
            True if transcript exists, False otherwise
        """
        try:
            # Search for files containing the source_url in frontmatter
            for file_path in self.transcripts_dir.glob("*.md"):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # Check if source_url is in frontmatter
                        if f'source_url: "{source_url}"' in content or f"source_url: '{source_url}'" in content:
                            return True
                except Exception as e:
                    logger.debug(f"Error reading file {file_path} to check for transcript: {e}")
                    continue
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking if transcript exists: {e}")
            return False
    
    def find_transcript_by_source_url(self, source_url: str) -> Optional[str]:
        """
        Find and return the file path of a transcript for a given source URL.
        
        Args:
            source_url: Source URL to find
            
        Returns:
            File path if found, None otherwise
        """
        try:
            for file_path in self.transcripts_dir.glob("*.md"):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # Check if source_url is in frontmatter
                        if f'source_url: "{source_url}"' in content or f"source_url: '{source_url}'" in content:
                            return str(file_path)
                except Exception as e:
                    logger.debug(f"Error reading file {file_path}: {e}")
                    continue
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding transcript by source URL: {e}")
            return None
    
    def read_transcript_content(self, file_path: str) -> Optional[str]:
        """
        Read the content (body) of a transcript file, excluding frontmatter.
        
        Args:
            file_path: Path to the markdown file
            
        Returns:
            Content text without frontmatter, or None if error
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Remove frontmatter (between --- markers)
            if content.startswith('---'):
                # Find the end of frontmatter
                parts = content.split('---', 2)
                if len(parts) >= 3:
                    # Return content after frontmatter
                    return parts[2].strip()
                else:
                    # No closing ---, return all content
                    return content.strip()
            else:
                # No frontmatter, return all content
                return content.strip()
                
        except Exception as e:
            logger.error(f"Error reading transcript content from {file_path}: {e}")
            return None

