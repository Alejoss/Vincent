"""Blog scraper using trafilatura and feedparser."""

import os
import logging
import requests
from typing import Optional, List, Dict
import feedparser
import trafilatura
from urllib.parse import urljoin

logger = logging.getLogger(__name__)


class BlogScraper:
    """Scrapes blog content from URLs and RSS feeds."""
    
    def __init__(self, timeout: int = 30):
        """
        Initialize blog scraper.
        
        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def scrape_url(self, url: str) -> Optional[str]:
        """
        Scrape content from a blog URL using trafilatura.
        
        Args:
            url: Blog URL
            
        Returns:
            Extracted text content or None
        """
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            # Extract main content using trafilatura
            text = trafilatura.extract(
                response.text,
                include_comments=False,
                include_tables=False,
                include_images=False,
                include_links=False
            )
            
            if text:
                logger.info(f"Successfully scraped content from {url}")
                return text.strip()
            else:
                logger.warning(f"No content extracted from {url}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching URL {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")
            return None
    
    def parse_rss_feed(self, feed_url: str) -> List[Dict]:
        """
        Parse RSS feed and extract article URLs and metadata.
        
        Args:
            feed_url: RSS feed URL
            
        Returns:
            List of article dictionaries with url, title, published, etc.
        """
        articles = []
        
        try:
            feed = feedparser.parse(feed_url)
            
            if feed.bozo and feed.bozo_exception:
                logger.warning(f"Feed parsing warning for {feed_url}: {feed.bozo_exception}")
            
            for entry in feed.entries:
                article = {
                    'url': entry.get('link', ''),
                    'title': entry.get('title', 'Untitled'),
                    'published': entry.get('published', ''),
                    'author': entry.get('author', ''),
                    'summary': entry.get('summary', '')
                }
                
                # Handle relative URLs
                if article['url'] and not article['url'].startswith('http'):
                    article['url'] = urljoin(feed_url, article['url'])
                
                articles.append(article)
            
            logger.info(f"Parsed {len(articles)} articles from RSS feed {feed_url}")
            
        except Exception as e:
            logger.error(f"Error parsing RSS feed {feed_url}: {e}")
        
        return articles
    
    def process_rss_feed(self, feed_url: str) -> List[Dict]:
        """
        Process RSS feed and scrape each article.
        
        Args:
            feed_url: RSS feed URL
            
        Returns:
            List of dictionaries with url, title, content, etc.
        """
        articles = self.parse_rss_feed(feed_url)
        processed_articles = []
        
        for article in articles:
            if not article['url']:
                continue
            
            content = self.scrape_url(article['url'])
            if content:
                article['content'] = content
                processed_articles.append(article)
            else:
                logger.warning(f"Could not scrape content for article: {article['title']}")
        
        return processed_articles
    
    def save_raw_content(self, url: str, content: str, output_dir: str = "raw_transcripts"):
        """
        Save raw blog content to file.
        
        Args:
            url: Source URL
            content: Content text
            output_dir: Output directory
        """
        os.makedirs(output_dir, exist_ok=True)
        
        # Create safe filename from URL
        safe_filename = url.replace('https://', '').replace('http://', '').replace('/', '_')
        safe_filename = ''.join(c if c.isalnum() or c in ('-', '_', '.') else '_' for c in safe_filename)
        safe_filename = safe_filename[:200]  # Limit filename length
        
        file_path = os.path.join(output_dir, f"blog_{safe_filename}.txt")
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        logger.info(f"Saved raw content to {file_path}")

