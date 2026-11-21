"""Google Gemini API Integration for Semantic Event Image Understanding.

Uses the official google-genai SDK to extract:
- Broad event context
- Moment categorization (ceremonies, group photos, candid, celebration, etc.)
- Short objective descriptions
- Contextual captions
- Searchable metadata tags

CRITICAL PRIVACY SAFEGUARDS:
- Guest selfies are NEVER passed to Gemini.
- Face embeddings and biometric data are NEVER passed to Gemini.
- Gemini is optional; if GEMINI_API_KEY is not set or quota is exceeded,
  core photo sharing and local OpenCV face matching continue uninterrupted.
"""

import json
import logging
from typing import TypedDict
from .config import GEMINI_API_KEY, GEMINI_MODEL

log = logging.getLogger('clickbook.gemini')

class GeminiMetadata(TypedDict, total=False):
    description: str
    context: str
    moment_type: str
    tags: list[str]
    caption: str

_client = None

def get_client():
    global _client
    if _client is None and GEMINI_API_KEY:
        try:
            from google import genai
            _client = genai.Client(api_key=GEMINI_API_KEY)
            log.info('Initialized Google Gemini client (model: %s)', GEMINI_MODEL)
        except Exception as e:
            log.warning('Could not initialize Google Gemini client: %s', e)
            _client = None
    return _client

def is_gemini_available() -> bool:
    """Return whether the Gemini integration is configured with an API key."""
    return bool(GEMINI_API_KEY and GEMINI_API_KEY != 'placeholder_gemini_api_key')

ANALYSIS_PROMPT = """Analyze this event photograph for an event gallery.
Provide structured metadata in valid JSON format with exactly these fields:
{
  "description": "A concise, objective 1-2 sentence visual description of what is happening in the photo.",
  "context": "Broad event setting/context (e.g., 'outdoor wedding ceremony', 'indoor music festival', 'corporate banquet', 'conference hall', 'dance floor celebration').",
  "moment_type": "One primary category: 'ceremony', 'group_portrait', 'candid_moment', 'celebration', 'stage_performance', 'keynote_speech', 'venue_details', or 'other'.",
  "tags": ["array", "of", "4_to_8", "concise", "lowercase", "searchable", "keywords"],
  "caption": "An optional natural event photo caption (max 150 characters)."
}
Do not guess personal names or private identities. Output strictly the JSON object."""

def analyze_photo(jpeg_bytes: bytes) -> GeminiMetadata | None:
    """Analyze an event photo using Gemini multimodal vision.
    
    Returns structured metadata dictionary or None if analysis was unavailable.
    """
    if not is_gemini_available():
        return None

    client = get_client()
    if not client:
        return None

    try:
        from google.genai import types

        image_part = types.Part.from_bytes(
            data=jpeg_bytes,
            mime_type='image/jpeg'
        )

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[image_part, ANALYSIS_PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
                max_output_tokens=500
            )
        )

        text = response.text.strip()
        # Clean any accidental markdown code blocks
        if text.startswith('```'):
            lines = text.split('\n')
            if lines[0].startswith('```'):
                lines = lines[1:]
            if lines and lines[-1].startswith('```'):
                lines = lines[:-1]
            text = '\n'.join(lines).strip()

        data = json.loads(text)
        return {
            'description': str(data.get('description', '')).strip(),
            'context': str(data.get('context', ''))[:120].strip(),
            'moment_type': str(data.get('moment_type', 'other'))[:64].strip(),
            'tags': [str(t).lower().strip() for t in data.get('tags', []) if isinstance(t, str)][:10],
            'caption': str(data.get('caption', ''))[:300].strip(),
        }

    except Exception as e:
        log.warning('Gemini API analysis failed or quota limit reached: %s', e)
        return None
