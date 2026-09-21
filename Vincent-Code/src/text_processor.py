"""Text processor using spaCy for intelligent filler word removal and cleaning."""

import os
import re
import logging
from typing import Optional, Dict, Set, Tuple
import spacy

logger = logging.getLogger(__name__)

# Mapping from language codes to spaCy models
LANGUAGE_MODEL_MAP: Dict[str, str] = {
    'en': 'en_core_web_sm',
    'es': 'es_core_news_sm',
    # Add more languages as needed:
    # 'fr': 'fr_core_news_sm',
    # 'de': 'de_core_news_sm',
    # 'it': 'it_core_news_sm',
    # 'pt': 'pt_core_news_sm',
}

# Default fallback model
DEFAULT_MODEL = 'en_core_web_sm'

VTT_MARKUP_RE = re.compile(r"<c[\s>]|captions Language\s*:|<\.\d|Kind:\s*captions", re.I)


def normalize_language_code(language_code: Optional[str]) -> str:
    """Map es-419, en-US, etc. to a spaCy model key (en, es, ...)."""
    if not language_code:
        return "en"
    base = language_code.split("-")[0].lower()
    return base if base in LANGUAGE_MODEL_MAP else "en"

# Language-specific filler words
FILLER_WORDS: Dict[str, Set[str]] = {
    'en': {'um', 'uh', 'er', 'ah', 'hmm', 'hm'},
    'es': {'eh', 'este', 'bueno', 'pues', 'como', 'entonces'},
}

# Language-specific filler phrases
FILLER_PHRASES: Dict[str, Set[str]] = {
    'en': {'you know', 'i mean', 'sort of', 'kind of', 'you see'},
    'es': {'o sea', 'es decir', 'quiero decir', 'digo yo', 'me entiendes'},
}


class TextProcessor:
    """Processes and cleans transcripts using spaCy."""
    
    def __init__(self, model_name: str = "en_core_web_sm"):
        """
        Initialize text processor with spaCy model.
        
        Args:
            model_name: spaCy model name (default: en_core_web_sm)
        """
        self.current_language = None
        self.loaded_models: Dict[str, spacy.Language] = {}
        self._load_model(model_name)
    
    def _load_model(self, model_name: str) -> None:
        """
        Load a spaCy model.
        
        Args:
            model_name: spaCy model name
        """
        if model_name in self.loaded_models:
            self.nlp = self.loaded_models[model_name]
            logger.debug(f"Using cached model: {model_name}")
            return
        
        try:
            self.nlp = spacy.load(model_name)
            self.loaded_models[model_name] = self.nlp
            logger.info(f"Loaded spaCy model: {model_name}")
        except OSError:
            logger.error(f"spaCy model '{model_name}' not found. Please install it with: python -m spacy download {model_name}")
            raise
    
    def get_model_for_language(self, language_code: str) -> str:
        """
        Get spaCy model name for a given language code.
        
        Args:
            language_code: Language code (e.g., 'en', 'es')
            
        Returns:
            spaCy model name
        """
        return LANGUAGE_MODEL_MAP.get(normalize_language_code(language_code), DEFAULT_MODEL)
    
    def get_filler_words_for_language(self, language_code: str) -> Set[str]:
        return FILLER_WORDS.get(
            normalize_language_code(language_code), FILLER_WORDS.get("en", set())
        )
    
    def get_filler_phrases_for_language(self, language_code: str) -> Set[str]:
        return FILLER_PHRASES.get(
            normalize_language_code(language_code), FILLER_PHRASES.get("en", set())
        )
    
    def load_model_for_language(self, language_code: str) -> None:
        lang = normalize_language_code(language_code)
        model_name = self.get_model_for_language(lang)
        if self.current_language != lang:
            self._load_model(model_name)
            self.current_language = lang
            logger.debug(f"Switched to language: {lang} (model: {model_name})")
    
    def clean_transcript(self, text: str, remove_timestamps: bool = True, 
                        remove_speaker_labels: bool = True) -> str:
        """
        Clean transcript by removing timestamps and speaker labels.
        
        Args:
            text: Raw transcript text
            remove_timestamps: Whether to remove timestamps
            remove_speaker_labels: Whether to remove speaker labels
            
        Returns:
            Cleaned text
        """
        cleaned = text

        # YouTube VTT karaoke markup (<c>, <00:01.234>) — strip if it leaked through
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = re.sub(
            r"^(?:Kind:\s*captions\s*)?(?:Language:\s*\w+\s*|captions Language\s*:\s*\w+\s*)",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        
        # Remove timestamps (e.g., [00:01:23] or 00:01:23)
        if remove_timestamps:
            cleaned = re.sub(r'\[?\d{1,2}:\d{2}(?::\d{2})?\]?', '', cleaned)
            cleaned = re.sub(r'\d{1,2}:\d{2}(?::\d{2})?', '', cleaned)
        
        # Remove speaker labels (e.g., "Speaker 1:", "John:")
        if remove_speaker_labels:
            cleaned = re.sub(r'^(?:Speaker\s+\d+|[\w\s]+):\s*', '', cleaned, flags=re.MULTILINE)
            cleaned = re.sub(r'\[Speaker\s+\d+\]', '', cleaned, flags=re.IGNORECASE)

        if VTT_MARKUP_RE.search(cleaned):
            cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        
        return cleaned.strip()
    
    def remove_filler_words(self, text: str, language_code: str = 'en') -> str:
        """
        Remove filler words using spaCy POS tagging.
        
        Args:
            text: Text to process
            language_code: Language code for language-specific filler words (default: 'en')
            
        Returns:
            Text with filler words removed
        """
        # Ensure correct model is loaded
        lang = normalize_language_code(language_code)
        self.load_model_for_language(lang)
        
        doc = self.nlp(text)
        filtered_tokens = []
        
        # Get language-specific filler words and phrases
        filler_words = self.get_filler_words_for_language(lang)
        filler_phrases = self.get_filler_phrases_for_language(lang)
        
        i = 0
        while i < len(doc):
            token = doc[i]
            token_lower = token.text.lower()
            
            # Check for filler phrases first (multi-word)
            phrase_found = False
            for phrase in filler_phrases:
                phrase_words = phrase.split()
                if i + len(phrase_words) <= len(doc):
                    tokens_text = ' '.join([t.text.lower() for t in doc[i:i+len(phrase_words)]])
                    if tokens_text == phrase:
                        # Skip filler phrase
                        i += len(phrase_words)
                        phrase_found = True
                        break
            
            if phrase_found:
                continue
            
            # Language-specific handling
            if lang == 'en':
                # Handle "like" as filler word (but preserve functional uses)
                if token_lower == 'like':
                    # Check POS tag - if it's a verb, preposition, or subordinating conjunction, keep it
                    if token.pos_ not in ['VERB', 'ADP', 'SCONJ']:
                        # Likely a filler, skip it
                        i += 1
                        continue
            
            # Check for single-word fillers
            if token_lower in filler_words:
                # Check if it's an interjection (INTJ) - likely a filler
                if token.pos_ == 'INTJ':
                    i += 1
                    continue
            
            # Keep the token
            filtered_tokens.append(token)
            i += 1
        
        # Preserve original spacing/punctuation between tokens
        result = "".join(t.text_with_ws for t in filtered_tokens).strip()
        result = re.sub(r"\s+", " ", result)
        return result.strip()
    
    def format_text(self, text: str, language_code: str = 'en') -> str:
        """Normalize spacing; add trailing period if missing."""
        formatted = re.sub(r"\s+", " ", text).strip()
        if formatted and formatted[-1] not in ".!?":
            formatted += "."
        return formatted
    
    def process(self, text: str, remove_timestamps: bool = True, 
                remove_speaker_labels: bool = True, remove_fillers: bool = True,
                language_code: str = 'en') -> str:
        """
        Complete text processing pipeline.
        
        Args:
            text: Raw transcript text
            remove_timestamps: Whether to remove timestamps
            remove_speaker_labels: Whether to remove speaker labels
            remove_fillers: Whether to remove filler words
            language_code: Language code for language-specific processing (default: 'en')
            
        Returns:
            Processed text
        """
        lang = normalize_language_code(language_code)
        self.load_model_for_language(lang)
        
        # Step 1: Clean timestamps and speaker labels
        processed = self.clean_transcript(text, remove_timestamps, remove_speaker_labels)
        
        # Step 2: Remove filler words (language-specific)
        if remove_fillers:
            processed = self.remove_filler_words(processed, lang)
        
        # Step 3: Normalize spacing / trailing punctuation
        processed = self.format_text(processed, lang)
        
        return processed
    
    def save_processed_text(self, text: str, source_id: str, output_dir: str = "processed_transcripts"):
        """
        Save processed text to file.
        
        Args:
            text: Processed text
            source_id: Identifier for the source (e.g., video_id or URL slug)
            output_dir: Output directory
        """
        os.makedirs(output_dir, exist_ok=True)
        
        # Create safe filename
        safe_filename = ''.join(c if c.isalnum() or c in ('-', '_', '.') else '_' for c in source_id)
        safe_filename = safe_filename[:200]
        
        file_path = os.path.join(output_dir, f"processed_{safe_filename}.txt")
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(text)
        
        logger.info(f"Saved processed text to {file_path}")

