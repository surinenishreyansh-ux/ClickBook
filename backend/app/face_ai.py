"""Local face detection + embeddings with OpenCV Zoo YuNet and SFace.

Source models are downloaded separately by `python models/download_models.py`.
No biometric queries are sent to an external AI service.
"""
import threading
import numpy as np
from .config import MODEL_DIR, FACE_THRESHOLD, CLUSTER_THRESHOLD

DETECTOR_NAME = 'face_detection_yunet_2023mar.onnx'
RECOGNIZER_NAME = 'face_recognition_sface_2021dec.onnx'
_lock=threading.Lock()
_models=None

def models_available():
    return (MODEL_DIR/DETECTOR_NAME).is_file() and (MODEL_DIR/DETECTOR_NAME).stat().st_size>100_000 and (MODEL_DIR/RECOGNIZER_NAME).is_file() and (MODEL_DIR/RECOGNIZER_NAME).stat().st_size>25_000_000

def _load():
    import cv2
    global _models
    if not models_available():
        raise RuntimeError('AI model files missing. Run: python models/download_models.py')
    if _models is None:
        detector=cv2.FaceDetectorYN.create(str(MODEL_DIR/DETECTOR_NAME),'',(320,320),score_threshold=0.75,nms_threshold=0.3,top_k=5000)
        recognizer=cv2.FaceRecognizerSF.create(str(MODEL_DIR/RECOGNIZER_NAME),'')
        _models=(detector,recognizer)
    return _models

def extract_faces(jpeg_bytes:bytes):
    """Returns list of {'box': normalized [x,y,w,h], 'vector': unit-norm 128-d list}.
    Models are shared behind a lock because detector.setInputSize mutates shared state.
    """
    import cv2
    arr=np.frombuffer(jpeg_bytes, dtype=np.uint8)
    bgr=cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None: raise ValueError('Unable to decode image')
    h,w=bgr.shape[:2]
    if w<60 or h<60: return []
    # Resize to reduce CPU load and memory; coordinates stay relative to resized image.
    scale=min(1.,1600/max(w,h))
    if scale<1:
        bgr=cv2.resize(bgr,(int(w*scale),int(h*scale)),interpolation=cv2.INTER_AREA)
    h,w=bgr.shape[:2]
    with _lock:
        detector,recognizer=_load()
        detector.setInputSize((w,h))
        _, faces=detector.detect(bgr)
        output=[]
        if faces is None:return output
        for box in faces[:80]:
            if float(box[2])<20 or float(box[3])<20: continue
            try:
                aligned=recognizer.alignCrop(bgr,box)
                feature=recognizer.feature(aligned).flatten().astype(np.float32)
                norm=float(np.linalg.norm(feature))
                if norm<1e-8:continue
                feature/=norm
                bbox=[max(0.,float(box[0])/w),max(0.,float(box[1])/h),min(1.,float(box[2])/w),min(1.,float(box[3])/h)]
                output.append({'box':[round(v,5) for v in bbox], 'vector':feature.tolist()})
            except cv2.error:
                continue
    return output

def cosine(a,b):
    return float(np.dot(np.asarray(a,dtype=np.float32),np.asarray(b,dtype=np.float32)))

def choose_cluster(vector, candidate_faces):
    """Join the best existing event cluster or create a new cluster ID.
    Conservative threshold minimizes incorrect merging of distinct guests.
    """
    from .db import uid
    if not candidate_faces:return uid()
    best=max(candidate_faces,key=lambda f:cosine(vector,f.embedding))
    if cosine(vector,best.embedding)>=CLUSTER_THRESHOLD:return best.cluster_id
    return uid()

def match_photos(vector, candidate_faces, threshold=None):
    """One score per photo, ordered by strongest similarity."""
    threshold=FACE_THRESHOLD if threshold is None else threshold
    scores={}
    for f in candidate_faces:
        score=cosine(vector,f.embedding)
        if score>=threshold and score>scores.get(f.photo_id,-1):
            scores[f.photo_id]=score
    return sorted(scores.items(),key=lambda kv:kv[1],reverse=True)
