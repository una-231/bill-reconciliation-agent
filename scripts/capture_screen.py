import hashlib
import json
import sys
from datetime import datetime,timezone
from pathlib import Path
from PIL import ImageGrab

ROOT=Path(__file__).resolve().parents[1]

if __name__=='__main__':
    target=ROOT/'docs/screenshots'/sys.argv[1]
    target.parent.mkdir(parents=True,exist_ok=True)
    ImageGrab.grab(all_screens=False).save(target)
    print(json.dumps(dict(file=str(target),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),captured_at=datetime.now(timezone.utc).isoformat()),ensure_ascii=False))
