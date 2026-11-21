"""Download official OpenCV Zoo YuNet/SFace weights (Apache 2.0) once.
Run: python models/download_models.py
Requires internet access; also automatically used in the Docker image build.
"""
import hashlib
from pathlib import Path
from urllib.request import urlopen, Request

ROOT=Path(__file__).resolve().parent
MODELS={
 'face_detection_yunet_2023mar.onnx':'https://raw.githubusercontent.com/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx',
 'face_recognition_sface_2021dec.onnx':'https://raw.githubusercontent.com/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx',
}

def download():
    for name,url in MODELS.items():
        path=ROOT/name
        if path.exists() and path.stat().st_size>(25_000_000 if 'sface' in name else 100_000):
            print('Already present:',name);continue
        print('Downloading',name,flush=True)
        temp=path.with_suffix('.download')
        candidates=[url, url.replace('https://raw.githubusercontent.com/opencv/opencv_zoo/main/', 'https://media.githubusercontent.com/media/opencv/opencv_zoo/main/'), url.replace('https://raw.githubusercontent.com/opencv/opencv_zoo/main/', 'https://huggingface.co/opencv/opencv_zoo/resolve/main/')]
        required=25_000_000 if 'sface' in name else 100_000
        for candidate in candidates:
            try:
                with urlopen(Request(candidate,headers={'User-Agent':'Clickbook/1.0'}),timeout=180) as source,temp.open('wb') as output:
                    while chunk:=source.read(1024*1024):output.write(chunk)
                if temp.stat().st_size>=required:break
                print('  Incomplete model from',candidate,'trying another mirror',flush=True)
            except Exception as exc:
                print('  Mirror failed:',str(exc)[:160],flush=True)
        if not temp.exists() or temp.stat().st_size<required:
            temp.unlink(missing_ok=True)
            raise RuntimeError(f'Model download incomplete: {name}. See backend/models/README.md')
        temp.replace(path)
        print(name, f'{path.stat().st_size/(1024*1024):.1f} MB', flush=True)
    print('Face detection and matching models installed.')
if __name__=='__main__': download()
