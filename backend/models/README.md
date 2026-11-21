## On-device server-side facial AI models

Download once with `python models/download_models.py` (internet required).

* YuNet face detector: `face_detection_yunet_2023mar.onnx`
* SFace 128-dimensional face embeddings: `face_recognition_sface_2021dec.onnx`

These model files belong to OpenCV Zoo; check official license and model cards before commercial distribution: https://github.com/opencv/opencv_zoo . No face data is sent to an external AI endpoint. OpenCV matching is statistical, not identity proof; evaluate precision on your actual events.

The files are not in this ZIP because this build environment could not download external binary model weights. Running the download script installs the actual, freely published model weights. Face search remains disabled/nonfunctional without them; regular photo sharing works.
