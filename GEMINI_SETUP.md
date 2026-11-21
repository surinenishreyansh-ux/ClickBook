# Google Gemini Multimodal Vision API Setup Guide

ClickBook integrates the official **Google Gemini API** (`google-genai` Python SDK) for semantic event photo categorization, moment recognition, keyword tagging, and search.

---

## 1. Obtain a Google Gemini API Key

1. Go to [Google AI Studio](https://aistudio.google.com/).
2. Sign in with your Google account.
3. Click **Get API key** > **Create API key**.
4. Select or create a Google Cloud project.
5. Copy your newly generated API key.

*(Note: Google AI Studio offers a generous Free Tier with no credit card required for standard development and testing).*

---

## 2. Configure Environment Variables

Add your API key to `.env`:

```env
GEMINI_API_KEY=AIzaSy...your_actual_key_here
GEMINI_MODEL=gemini-2.5-flash
```

If you do not want to use Gemini, simply leave `GEMINI_API_KEY` blank or omit it. The application detects this and cleanly disables Gemini features without throwing errors.

---

## 3. Gemini Responsibilities & Capabilities

Gemini is executed asynchronously in ClickBook's persistent background job queue on each uploaded event photo:

| Feature | Description | Example Output |
|---|---|---|
| **Moment Type** | Categorizes the photographic moment | `ceremony`, `group_portrait`, `celebration`, `candid_moment`, `stage_performance` |
| **Event Context** | Identifies the physical setting and event theme | `outdoor sunset wedding reception`, `indoor acoustic concert stage` |
| **Description** | 1–2 sentence objective visual description | `A couple exchanging vows under a floral arch while guests watch.` |
| **Searchable Tags** | 4–8 lowercase keywords for instant gallery searching | `["stage", "lights", "applause", "band", "guitar"]` |
| **Photo Caption** | Natural event caption | `The bride and groom cutting the three-tiered cake.` |

---

## 4. Privacy & Biometric Architecture Safeguards

ClickBook enforces strict privacy boundaries:
1. **NO Selfies Sent to Gemini:** Guest search selfies are processed strictly in-memory by the local OpenCV YuNet/SFace neural networks. Selfies are NEVER sent to Gemini or external cloud services.
2. **NO Face Embeddings Sent to Gemini:** Biometric face vectors (128D) are calculated and matched strictly by OpenCV locally on your server.
3. **Event Scope:** Only approved photographer photos uploaded to an event are processed by Gemini.
4. **Graceful Quota Handling:** If your Gemini API quota is reached, indexing errors are logged in the database, and the core photo gallery and face matching continue working without interruption.
