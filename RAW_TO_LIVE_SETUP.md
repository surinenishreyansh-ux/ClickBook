# ClickBook — Camera RAW to Live Gallery

The photographer can shoot RAW (Canon CR2/CR3, Nikon NEF, Sony ARW,
Adobe DNG, Fujifilm RAF and other LibRaw-compatible files). ClickBook's
desktop uploader monitors the tethered camera folder, **develops each RAW
file locally into a high-resolution JPEG**, then uploads the JPEG to your
existing event. The guests see it appear in the live QR gallery after
ClickBook/Cloudinary finish uploading.

**Your original RAW never leaves the photographer's computer.** The
conversion doesn't overwrite or save a converted file next to the original.
The backend receives a JPEG; it builds a 4000-pixel-maximum full image,
1600-pixel gallery image and 650-pixel thumbnail, strips EXIF, and stores
all variants privately with Cloudinary.

## Windows one-time installation

From the root of your checked-out ClickBook repository, in PowerShell:

```powershell
python -m pip install -r uploader/requirements-raw.txt
```

For ordinary JPG/PNG/WebP camera files, the uploader needs **no additional
Python packages**; RAW development requires `rawpy` (LibRaw) and Pillow on
the photographer's computer, not on Render. New RAW camera models require a
LibRaw version that supports that camera. A file extension is **not a guarantee
that a particular RAW encoding is supported**.

## Launch for your in-person event

1. Sign in to ClickBook at https://clickbook-live.onrender.com.
2. Have the organizer create an event and invite your photographer.
3. Accept the photographer invite with your account, and get the
   **event ID** from the event workspace (NOT the guest QR code).
4. Configure the manufacturer's tethering app to save photos to a local
   folder, for example `C:\EventPhotos\Capture`.
5. With that folder already created, run:

```powershell
python uploader/clickbook_uploader.py --api https://clickbook-live.onrender.com --event YOUR_EVENT_ID --folder "C:\EventPhotos\Capture" --email photographer@example.com
```

The uploader prompts for your ClickBook password securely and scans the
camera folder every 3 seconds. A file is uploaded only after its file
size and modification time are unchanged across two scans, reducing the
chance of partially written camera files.

**RAW-only workflow:** When the camera saves only RAW, the uploader uses
camera white balance, converts into sRGB and exports a high-quality
progressive JPEG at up to 4000 pixels on its longest side. Development
takes some CPU time depending on your computer and camera format, so
"live" means *after conversion and upload*, not instant shutter-to-screen.

**RAW+JPEG workflow (recommended for speed):** When both have the same
base filename (for example `DSC_0001.CR3` and `DSC_0001.JPG`), the
uploader prefers the camera-generated JPEG for faster delivery. It
won't upload a second copy of the same shot. If RAW was published before
its JPEG arrived, that JPEG is skipped too.

To use smaller conversions on an older laptop:

```powershell
python uploader/clickbook_uploader.py --api https://clickbook-live.onrender.com --event YOUR_EVENT_ID --folder "C:\EventPhotos\Capture" --email photographer@example.com --raw-half-size
```

To adjust RAW JPEG quality (default 88) and long-edge output (default 4000):

```powershell
python uploader/clickbook_uploader.py --api https://clickbook-live.onrender.com --event YOUR_EVENT_ID --folder "C:\EventPhotos\Capture" --email photographer@example.com --raw-quality 90 --raw-max-side 4000
```

## Privacy, limits and backups

- RAW is developed locally; the original stays intact on the camera card or
  photographer's laptop. No RAW byte stream is sent to ClickBook.
- Converted JPEG is uploaded to the authenticated photographer endpoint;
  the backend still validates it, removes metadata and saves protected JPEGs.
- ClickBook's 25 MiB incoming file limit still applies to the *converted*
  JPEG. The uploader recompresses and reduces dimensions as needed.
- Render Free and Cloudinary's Free plan have latency, upload and quota
  limits. For a time-critical live event, keep camera-card backups and a
  mobile hotspot available.
- Watch the console for errors. A failed photo stays in the folder and is
  retried on the next scan. Already uploaded photos are recorded in
  `.clickbook-upload-state.json` inside the watched folder.
- The uploader requires the photographer to have been invited/approved
  for the target event. A guest QR alone cannot upload.
- **In-person rehearsal:** Test 2–3 actual RAW samples from the precise
  camera model before guests arrive. Some CR3/RAF/other camera codecs
  need newer LibRaw builds; unsupported input must be handled on the PC.
- For original RAW archival or professional editing, retain a separate
  RAW backup. ClickBook's cloud variants are *processed JPEGs*, not the
  original RAW or a 16-bit editing negative.

This feature does **not** run AI super-resolution or magically recover
detail that the camera never captured. It develops RAW into a usable,
color-corrected, high-resolution JPEG appropriate for a guest gallery.
