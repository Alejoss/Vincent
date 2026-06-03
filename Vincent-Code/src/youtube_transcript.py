"""YouTube transcript fetcher using YouTube Data API v3 and youtube-transcript-api."""

import re
import os
import logging
from typing import List, Dict, Optional, Tuple
from googleapiclient.discovery import build
try:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
except ImportError:
    raise ImportError("Could not import youtube-transcript-api. Please install it: pip install youtube-transcript-api")

logger = logging.getLogger(__name__)


class YouTubeTranscriptFetcher:
    """Fetches YouTube transcripts and monitors channels for new videos."""
    
    def __init__(self, api_key: str):
        """
        Initialize YouTube transcript fetcher.
        
        Args:
            api_key: YouTube Data API v3 key
        """
        self.youtube = build('youtube', 'v3', developerKey=api_key)
    
    def extract_video_id(self, url: str) -> Optional[str]:
        """
        Extract video ID from YouTube URL.
        
        Args:
            url: YouTube URL (various formats supported)
            
        Returns:
            Video ID or None if invalid
        """
        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
            r'youtube\.com\/watch\?.*v=([a-zA-Z0-9_-]{11})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        return None
    
    def extract_channel_id(self, url: str) -> Optional[str]:
        """
        Extract channel ID from YouTube URL.
        
        Args:
            url: YouTube channel URL
            
        Returns:
            Channel ID or None if invalid
        """
        # Handle various URL formats
        patterns = [
            r'youtube\.com\/channel\/([a-zA-Z0-9_-]+)',
            r'youtube\.com\/c\/([a-zA-Z0-9_-]+)',
            r'youtube\.com\/user\/([a-zA-Z0-9_-]+)',
            r'youtube\.com\/@([a-zA-Z0-9_-]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                channel_identifier = match.group(1)
                # If it's a channel ID (starts with UC), return directly
                if channel_identifier.startswith('UC') and len(channel_identifier) == 24:
                    return channel_identifier
                # Otherwise, resolve username/handle to channel ID
                return self._resolve_channel_id(channel_identifier)
        
        return None
    
    def _resolve_channel_id(self, identifier: str) -> Optional[str]:
        """Resolve channel username/handle to channel ID."""
        try:
            # Try to get channel by username (for old format)
            try:
                request = self.youtube.channels().list(
                    part='id',
                    forUsername=identifier
                )
                response = request.execute()
                
                if response.get('items'):
                    return response['items'][0]['id']
            except:
                pass
            
            # Try handle format (@username)
            # Note: YouTube API doesn't directly support @handles, so we use search
            if identifier.startswith('@'):
                identifier = identifier[1:]  # Remove @
            
            # Use search API to find channel by handle
            request = self.youtube.search().list(
                part='snippet',
                q=identifier,
                type='channel',
                maxResults=1
            )
            response = request.execute()
            
            if response.get('items'):
                return response['items'][0]['snippet']['channelId']
                
        except Exception as e:
            logger.warning(f"Could not resolve channel ID for {identifier}: {e}")
        
        return None
    
    def get_channel_uploads_playlist_id(self, channel_id: str) -> Optional[str]:
        """
        Get the uploads playlist ID for a channel.
        
        Args:
            channel_id: YouTube channel ID
            
        Returns:
            Uploads playlist ID or None
        """
        try:
            request = self.youtube.channels().list(
                part='contentDetails',
                id=channel_id
            )
            response = request.execute()
            
            if response.get('items'):
                uploads_playlist_id = response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
                return uploads_playlist_id
                
        except Exception as e:
            logger.error(f"Error getting uploads playlist for channel {channel_id}: {e}")
        
        return None
    
    def get_channel_videos(self, playlist_id: str, max_results: int = 1) -> List[Dict]:
        """
        Get videos from a channel's uploads playlist.
        
        Args:
            playlist_id: Uploads playlist ID
            max_results: Maximum number of videos to retrieve
            
        Returns:
            List of video dictionaries with id, title, publishedAt
        """
        videos = []
        next_page_token = None
        
        try:
            while len(videos) < max_results:
                request = self.youtube.playlistItems().list(
                    part='snippet',
                    playlistId=playlist_id,
                    maxResults=min(50, max_results - len(videos)),
                    pageToken=next_page_token
                    # Note: order parameter is not supported for playlistItems().list()
                    # Playlist items are returned in playlist order (uploads are newest first)
                )
                response = request.execute()
                
                logger.debug(f"YouTube API response: {len(response.get('items', []))} items")
                
                for item in response.get('items', []):
                    snippet = item['snippet']
                    videos.append({
                        'id': snippet['resourceId']['videoId'],
                        'title': snippet['title'],
                        'publishedAt': snippet['publishedAt']
                    })
                
                next_page_token = response.get('nextPageToken')
                if not next_page_token:
                    break
                    
        except Exception as e:
            logger.error(f"Error getting channel videos: {e}")
            import traceback
            logger.debug(f"Full error traceback: {traceback.format_exc()}")
        
        return videos
    
    def get_new_videos(self, channel_url: str, processed_video_ids: List[str]) -> List[Dict]:
        """
        Get new videos from a channel that haven't been processed.
        
        Args:
            channel_url: YouTube channel URL
            processed_video_ids: List of already processed video IDs
            
        Returns:
            List of new video dictionaries
        """
        channel_id = self.extract_channel_id(channel_url)
        if not channel_id:
            logger.error(f"Could not extract channel ID from {channel_url}")
            return []
        
        playlist_id = self.get_channel_uploads_playlist_id(channel_id)
        if not playlist_id:
            logger.error(f"Could not get uploads playlist for channel {channel_id}")
            return []
        
        all_videos = self.get_channel_videos(playlist_id)
        logger.info(f"Retrieved {len(all_videos)} videos from channel")
        
        if all_videos:
            logger.debug(f"First video: {all_videos[0]['title']} ({all_videos[0]['id']})")
            logger.debug(f"Last video: {all_videos[-1]['title']} ({all_videos[-1]['id']})")
        
        processed_set = set(processed_video_ids)
        logger.debug(f"Already processed {len(processed_set)} video IDs")
        
        new_videos = [v for v in all_videos if v['id'] not in processed_set]
        
        logger.info(f"Found {len(new_videos)} new videos out of {len(all_videos)} total")
        if new_videos:
            logger.info(f"New videos to process: {[v['title'] for v in new_videos]}")
        
        return new_videos
    
    def fetch_transcript(self, video_id: str, languages: List[str] = None) -> Optional[Tuple[str, str]]:
        """
        Fetch transcript for a YouTube video.
        
        Args:
            video_id: YouTube video ID
            languages: Preferred languages (default: ['en'])
            
        Returns:
            Tuple of (transcript_text, language_code) or None if not available
        """
        if languages is None:
            languages = ['en']
        
        try:
            # Create an instance of YouTubeTranscriptApi
            ytt_api = YouTubeTranscriptApi()
            
            # Try to get transcript in preferred language first
            transcript_data = None
            language_code = None
            
            try:
                # Use fetch() method with preferred languages
                fetched_transcript = ytt_api.fetch(video_id, languages=languages)
                # Convert to raw data format (list of dicts with 'text', 'start', 'duration')
                transcript_data = fetched_transcript.to_raw_data()
                # Get language code from fetched transcript
                language_code = fetched_transcript.language_code
                logger.debug(f"Found transcript in preferred language: {language_code}")
            except (TranscriptsDisabled, NoTranscriptFound):
                # If preferred language not found, try to get any available transcript
                logger.debug(f"Preferred languages not available, trying any available transcript")
                try:
                    # Use list() to get available transcripts
                    transcript_list = ytt_api.list(video_id)
                    # Iterate over available transcripts and fetch the first one
                    for transcript in transcript_list:
                        try:
                            fetched_transcript = transcript.fetch()
                            transcript_data = fetched_transcript.to_raw_data()
                            language_code = fetched_transcript.language_code
                            logger.debug(f"Using transcript in language: {language_code}")
                            break
                        except Exception as e:
                            logger.debug(f"Could not fetch transcript in {transcript.language_code}: {e}")
                            continue
                except Exception as e:
                    logger.warning(f"Could not get transcript list: {e}")
            
            if not transcript_data or not language_code:
                return None
            
            # Combine all text
            text_parts = [entry['text'] for entry in transcript_data]
            full_text = ' '.join(text_parts)
            
            logger.info(f"Successfully fetched transcript for video {video_id} in language: {language_code}")
            return (full_text, language_code)
            
        except (TranscriptsDisabled, NoTranscriptFound) as e:
            logger.warning(f"No transcript available for video {video_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching transcript for video {video_id}: {e}")
            import traceback
            logger.debug(f"Full error traceback: {traceback.format_exc()}")
            return None
    
    def get_video_metadata(self, video_id: str) -> Optional[Dict]:
        """
        Get video metadata including upload date and title.
        
        Args:
            video_id: YouTube video ID
            
        Returns:
            Dictionary with id, title, publishedAt, or None
        """
        try:
            request = self.youtube.videos().list(
                part='snippet',
                id=video_id
            )
            response = request.execute()
            
            if response.get('items'):
                snippet = response['items'][0]['snippet']
                return {
                    'id': video_id,
                    'title': snippet['title'],
                    'publishedAt': snippet['publishedAt']
                }
        except Exception as e:
            logger.error(f"Error getting video metadata for {video_id}: {e}")
        
        return None
    
    def process_video(self, video_url: str) -> Optional[Tuple[str, str, str]]:
        """
        Process a single video URL and return transcript.
        
        Args:
            video_url: YouTube video URL
            
        Returns:
            Tuple of (video_id, transcript_text, language_code) or None
        """
        video_id = self.extract_video_id(video_url)
        if not video_id:
            logger.error(f"Could not extract video ID from {video_url}")
            return None
        
        result = self.fetch_transcript(video_id)
        if result:
            transcript_text, language_code = result
            return (video_id, transcript_text, language_code)
        
        return None
    
    def save_raw_transcript(self, video_id: str, transcript: str, output_dir: str = "raw_transcripts"):
        """
        Save raw transcript to file.
        
        Args:
            video_id: YouTube video ID
            transcript: Transcript text
            output_dir: Output directory
        """
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, f"youtube_{video_id}.txt")
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(transcript)
        
        logger.info(f"Saved raw transcript to {file_path}")

