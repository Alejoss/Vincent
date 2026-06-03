"""
Main orchestrator for YouTube and Blog Transcript Pipeline.
Reads sources from Notion, fetches/processes transcripts, and writes to the second brain
(Obsidian vault) in 10_Sources/Transcripts/. See OBSIDIAN_SETUP.md and SECOND_BRAIN.md.
"""

import os
import sys
import logging
from datetime import datetime
from dotenv import load_dotenv

from src.notion_source_manager import NotionSourceManager
from src.markdown_writer import MarkdownWriter
from src.youtube_transcript import YouTubeTranscriptFetcher
from src.blog_scraper import BlogScraper
from src.text_processor import TextProcessor

# Load environment variables (override=True ensures .env file takes precedence over system env vars)
load_dotenv(override=True)

# Configure logging
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

# Configure root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# File handler with detailed logging
file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

# Console handler with user-friendly format
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(message)s'))

# Suppress verbose HTTP logs from httpx and googleapiclient
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('googleapiclient').setLevel(logging.WARNING)
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.WARNING)

root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)


def setup_components():
    """Initialize all components."""
    # Get configuration from environment
    youtube_api_key = os.getenv('YOUTUBE_API_KEY')
    notion_api_token = os.getenv('NOTION_API_TOKEN')
    notion_sources_db_id = os.getenv('NOTION_SOURCES_DATABASE_ID')
    obsidian_vault_path = os.getenv('OBSIDIAN_VAULT_PATH', './obsidian')
    
    if not youtube_api_key:
        logger.error("Missing required environment variable: YOUTUBE_API_KEY")
        sys.exit(1)
    
    if not notion_api_token:
        logger.error("Missing required environment variable: NOTION_API_TOKEN")
        sys.exit(1)
    
    if not notion_sources_db_id:
        logger.error("Missing required environment variable: NOTION_SOURCES_DATABASE_ID")
        sys.exit(1)
    
    # Initialize components
    source_manager = NotionSourceManager(notion_api_token, notion_sources_db_id)
    markdown_writer = MarkdownWriter(obsidian_vault_path, folder_name="Transcripts")
    youtube_fetcher = YouTubeTranscriptFetcher(youtube_api_key)
    blog_scraper = BlogScraper()
    text_processor = TextProcessor()
    
    # Initialize Notion client for transcript tracking (optional)
    notion_transcripts_db_id = os.getenv('NOTION_TRANSCRIPTS_DATABASE_ID')
    notion_client = None
    if notion_transcripts_db_id:
        try:
            from src.notion_client import NotionClient
            notion_client = NotionClient(notion_api_token, notion_transcripts_db_id)
            logger.info("Notion transcript tracking enabled")
        except Exception as e:
            logger.warning(f"Could not initialize Notion transcript client: {e}")
            notion_client = None
    
    return source_manager, markdown_writer, youtube_fetcher, blog_scraper, text_processor, notion_client


def process_youtube_source(source_manager, markdown_writer, youtube_fetcher, text_processor, source, notion_client=None):
    """Process a YouTube source (channel or video)."""
    source_id = source['id']
    url = source['url']
    source_type = source['source_type']
    processed_video_ids = source.get('processed_video_ids', [])
    if isinstance(processed_video_ids, str):
        processed_video_ids = [vid.strip() for vid in processed_video_ids.split(',') if vid.strip()]
    
    logger.debug(f"Processing YouTube source: {url}")
    
    # Check if it's a channel or individual video
    video_id = youtube_fetcher.extract_video_id(url)
    
    if video_id:
        # Individual video
        # Check Notion first (if available), then local files
        transcript_exists = False
        if notion_client:
            transcript_exists = notion_client.transcript_exists(url)
        if not transcript_exists:
            transcript_exists = markdown_writer.transcript_exists(url)
        
        if transcript_exists:
            logger.info(f"      ℹ️  Transcript already exists for video {url}")
            return
        
        result = youtube_fetcher.process_video(url)
        if result:
            video_id, transcript, language_code = result
            
            # Save raw transcript
            youtube_fetcher.save_raw_transcript(video_id, transcript)
            
            # Process transcript with language-specific processing
            processed_text = text_processor.process(transcript, language_code=language_code)
            text_processor.save_processed_text(processed_text, video_id)
            
            # Get video metadata (title and upload date)
            video_metadata = youtube_fetcher.get_video_metadata(video_id)
            if video_metadata:
                title = video_metadata['title']
                upload_date = video_metadata['publishedAt']
            else:
                title = f"YouTube Video {video_id}"
                upload_date = None
            
            processed_date = datetime.now().isoformat()
            
            # Save to Obsidian markdown
            markdown_writer.save_transcript(
                title=title,
                content=processed_text,
                source_url=url,
                source_type="YouTube",
                upload_date=upload_date,
                processed_date=processed_date,
                language_code=language_code
            )
            
            # Create Notion entry (metadata only)
            if notion_client:
                notion_client.save_processed_text(
                    title=title,
                    content=processed_text,
                    source_url=url,
                    source_type="YouTube",
                    save_content=False  # Metadata only
                )
            
            logger.info(f"      ✓ Processed video {video_id} (language: {language_code})")
        else:
            logger.warning(f"      ⚠️  Could not fetch transcript for video {url}")
    else:
        # Channel - check for new videos
        new_videos = youtube_fetcher.get_new_videos(url, processed_video_ids)
        
        updated_video_ids = processed_video_ids.copy()
        
        for video in new_videos:
            video_id = video['id']
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            
            # Check Notion first (if available), then local files
            transcript_exists = False
            if notion_client:
                transcript_exists = notion_client.transcript_exists(video_url)
            if not transcript_exists:
                transcript_exists = markdown_writer.transcript_exists(video_url)
            
            if transcript_exists:
                logger.info(f"      ℹ️  Transcript already exists for video {video_id}")
                updated_video_ids.append(video_id)
                continue
            
            result = youtube_fetcher.fetch_transcript(video_id)
            if result:
                transcript, language_code = result
                
                # Save raw transcript
                youtube_fetcher.save_raw_transcript(video_id, transcript)
                
                # Process transcript with language-specific processing
                processed_text = text_processor.process(transcript, language_code=language_code)
                text_processor.save_processed_text(processed_text, video_id)
                
                # Use upload date from video metadata (publishedAt)
                upload_date = video.get('publishedAt')
                processed_date = datetime.now().isoformat()
                
                # Save to Obsidian markdown
                markdown_writer.save_transcript(
                    title=video['title'],
                    content=processed_text,
                    source_url=video_url,
                    source_type="YouTube",
                    upload_date=upload_date,
                    processed_date=processed_date,
                    language_code=language_code  # From YouTube API
                )
                
                # Create Notion entry (metadata only)
                if notion_client:
                    notion_client.save_processed_text(
                        title=video['title'],
                        content=processed_text,
                        source_url=video_url,
                        source_type="YouTube",
                        save_content=False  # Metadata only
                    )
                
                updated_video_ids.append(video_id)
                logger.info(f"      ✓ Processed video {video_id}: {video['title']} (language: {language_code})")
            else:
                logger.warning(f"      ⚠️  Could not fetch transcript for video {video_id}")
        
        # Update source with processed video IDs
        if updated_video_ids != processed_video_ids:
            source_manager.update_source_last_processed(source_id, updated_video_ids)
        else:
            source_manager.update_source_last_processed(source_id)


def process_blog_source(source_manager, markdown_writer, blog_scraper, text_processor, source, notion_client=None):
    """Process a blog source (individual URL)."""
    source_id = source['id']
    url = source['url']
    
    logger.debug(f"Processing blog source: {url}")
    
    # Check Notion first (if available), then local files
    transcript_exists = False
    if notion_client:
        transcript_exists = notion_client.transcript_exists(url)
    if not transcript_exists:
        transcript_exists = markdown_writer.transcript_exists(url)
    
    if transcript_exists:
        logger.info(f"      ℹ️  Transcript already exists for blog {url}")
        return
    
    content = blog_scraper.scrape_url(url)
    if content:
        # Save raw content
        blog_scraper.save_raw_content(url, content)
        
        # Process content
        processed_text = text_processor.process(content, remove_timestamps=False, remove_speaker_labels=False)
        text_processor.save_processed_text(processed_text, url.replace('https://', '').replace('http://', ''))
        
        # Extract title from URL or use default
        title = url.split('/')[-1] or "Blog Post"
        title = title.replace('-', ' ').replace('_', ' ').title()
        processed_date = datetime.now().isoformat()
        
        # Save to Obsidian markdown
        markdown_writer.save_transcript(
            title=title,
            content=processed_text,
            source_url=url,
            source_type="Blog",
            processed_date=processed_date
        )
        
        # Create Notion entry (metadata only)
        if notion_client:
            notion_client.save_processed_text(
                title=title,
                content=processed_text,
                source_url=url,
                source_type="Blog",
                save_content=False  # Metadata only
            )
        
        # Update source
        source_manager.update_source_last_processed(source_id)
        
        logger.info(f"      ✓ Successfully processed blog {url}")
    else:
        logger.warning(f"      ⚠️  Could not scrape content from {url}")


def process_rss_source(source_manager, markdown_writer, blog_scraper, text_processor, source, notion_client=None):
    """Process an RSS feed source."""
    source_id = source['id']
    feed_url = source['url']
    
    logger.debug(f"Processing RSS feed: {feed_url}")
    
    articles = blog_scraper.process_rss_feed(feed_url)
    
    processed_count = 0
    for article in articles:
        url = article['url']
        
        # Check Notion first (if available), then local files
        transcript_exists = False
        if notion_client:
            transcript_exists = notion_client.transcript_exists(url)
        if not transcript_exists:
            transcript_exists = markdown_writer.transcript_exists(url)
        
        if transcript_exists:
            logger.info(f"      ℹ️  Transcript already exists for article {url}")
            continue
        
        content = article.get('content')
        if content:
            # Save raw content
            blog_scraper.save_raw_content(url, content)
            
            # Process content
            processed_text = text_processor.process(content, remove_timestamps=False, remove_speaker_labels=False)
            text_processor.save_processed_text(processed_text, url.replace('https://', '').replace('http://', ''))
            
            # Parse published date from RSS (if available)
            upload_date = None
            if article.get('published'):
                try:
                    # RSS dates are typically in RFC 2822 format, convert to ISO
                    from email.utils import parsedate_to_datetime
                    pub_date = parsedate_to_datetime(article['published'])
                    upload_date = pub_date.isoformat()
                except Exception:
                    # If parsing fails, try using the string directly or skip
                    pass
            
            processed_date = datetime.now().isoformat()
            markdown_writer.save_transcript(
                title=article['title'],
                content=processed_text,
                source_url=url,
                source_type="RSS",
                upload_date=upload_date,
                processed_date=processed_date
            )
            
            # Create Notion entry (metadata only)
            if notion_client:
                notion_client.save_processed_text(
                    title=article['title'],
                    content=processed_text,
                    source_url=url,
                    source_type="RSS",
                    save_content=False  # Metadata only
                )
            
            processed_count += 1
            logger.info(f"      ✓ Processed article: {article['title']}")
    
    # Update source
    if processed_count > 0:
        source_manager.update_source_last_processed(source_id)
    
    logger.info(f"      ✓ Processed {processed_count} article(s) from RSS feed {feed_url}")


def main():
    """Main execution function."""
    logger.info("=" * 60)
    logger.info("Starting Transcript Pipeline")
    logger.info("=" * 60)
    
    try:
        # Setup components
        logger.info("\n📦 Initializing components...")
        source_manager, markdown_writer, youtube_fetcher, blog_scraper, text_processor, notion_client = setup_components()
        logger.info("✓ Components initialized successfully\n")
        
        # Get sources from Notion
        logger.info("🔍 Loading sources from Notion...")
        sources = source_manager.get_sources()
        
        if len(sources) == 0:
            logger.warning("\n⚠️  No active sources found to process!")
            logger.info("   Please check your Notion database and ensure sources are marked as 'Active'")
            logger.info("   Transcript Pipeline completed (no sources to process)")
            return
        
        logger.info(f"\n✓ Found {len(sources)} active source(s) to process\n")
        logger.info("-" * 60)
        
        # Process each source
        for idx, source in enumerate(sources, 1):
            try:
                source_type = source['source_type']
                source_url = source.get('url', 'unknown')
                
                logger.info(f"\n[{idx}/{len(sources)}] Processing {source_type} source:")
                logger.info(f"   URL: {source_url}")
                
                if source_type == 'YouTube':
                    process_youtube_source(source_manager, markdown_writer, youtube_fetcher, text_processor, source, notion_client)
                elif source_type == 'Blog':
                    process_blog_source(source_manager, markdown_writer, blog_scraper, text_processor, source, notion_client)
                elif source_type == 'RSS':
                    process_rss_source(source_manager, markdown_writer, blog_scraper, text_processor, source, notion_client)
                else:
                    logger.warning(f"   ⚠️  Unknown source type: {source_type}")
                    logger.warning(f"   Skipping this source...")
                
                logger.info(f"   ✓ Completed processing {source_type} source")
                logger.info("-" * 60)
                    
            except Exception as e:
                logger.error(f"\n   ❌ Error processing source {source.get('url', 'unknown')}: {e}")
                logger.debug(f"   Full error details: {e}", exc_info=True)
                logger.info("-" * 60)
                continue
        
        logger.info("\n" + "=" * 60)
        logger.info("✓ Transcript Pipeline completed successfully")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"\n❌ Fatal error in pipeline: {e}")
        logger.debug(f"Full error details:", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

