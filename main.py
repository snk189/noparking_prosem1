from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import json, os, base64, easyocr, cv2, numpy as np, re

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

DATA_FILE = "data.json"
FINE_AMOUNT = 100
BUFFER_SECONDS = 5
ocr_reader = easyocr.Reader(['en'])
PLATE_PATTERN = r"[A-Z]{2}[0-9]{1,2}[A-Z]{1,2}[0-9]{1,4}"

if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f: json.dump({}, f)

class Payment(BaseModel):
    number: str
    amount: int

def read_data():
    with open(DATA_FILE, "r") as f: return json.load(f)

def write_data(data):
    with open(DATA_FILE, "w") as f: json.dump(data, f, indent=4)

def formatted_time():
    return datetime.now().strftime("%d %B %Y - %I:%M:%S %p")

def process_image(image_bytes):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    results = ocr_reader.readtext(img)
    detected = None

    for bbox, text, _ in results:
        clean = text.replace(" ", "").upper()
        if re.fullmatch(PLATE_PATTERN, clean):
            detected = clean
            (tl, tr, br, bl) = bbox
            tl = tuple(map(int, tl))
            br = tuple(map(int, br))
            cv2.rectangle(img, tl, br, (0,255,0), 2)
            cv2.putText(img, clean, (tl[0], tl[1]-10),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)
            break

    if not detected: return None, None
    _, buffer_img = cv2.imencode('.jpg', img)
    return detected, base64.b64encode(buffer_img).decode("utf-8")

@app.post("/api/new_violation_image")
async def new_violation_image(file: UploadFile = File(...)):
    img_bytes = await file.read()
    plate, b64 = process_image(img_bytes)
    if not plate: return {"status": "error", "message": "No number plate detected."}

    data = read_data()
    now = datetime.now()

    if plate not in data:
        data[plate] = {
            "fine": FINE_AMOUNT,
            "last_update": now.isoformat(),
            "breakdown": [{
                "type": "FINE",
                "amount": FINE_AMOUNT,
                "timestamp": formatted_time(),
                "image": b64
            }]
        }
        write_data(data)
        return {"status": "added", "plate": plate, "fine": FINE_AMOUNT}

    last = datetime.fromisoformat(data[plate]["last_update"])
    if (now - last).total_seconds() < BUFFER_SECONDS:
        wait = BUFFER_SECONDS - int((now-last).total_seconds())
        return {"status": "wait", "message": f"Wait {wait}s"}

    data[plate]["fine"] += FINE_AMOUNT
    data[plate]["last_update"] = now.isoformat()
    data[plate]["breakdown"].append({
        "type": "FINE",
        "amount": FINE_AMOUNT,
        "timestamp": formatted_time(),
        "image": b64
    })

    write_data(data)
    return {"status": "updated", "plate": plate, "fine": data[plate]["fine"]}

@app.post("/api/pay_fine")
def pay_fine(p: Payment):
    data = read_data()
    plate = p.number.upper()
    if plate not in data: return {"status": "no_record"}

    if p.amount > data[plate]["fine"]:
        return {"status":"excess","remaining":data[plate]["fine"]}

    data[plate]["fine"] -= p.amount
    data[plate]["breakdown"].append({
        "type": "PAYMENT",
        "amount": -p.amount,
        "timestamp": formatted_time()
    })
    write_data(data)
    return {"status":"paid","remaining":data[plate]["fine"]}

@app.get("/api/get_vehicle/{plate}")
def get_vehicle(plate: str):
    data = read_data()
    if plate.upper() not in data: return {"status":"no_record"}
    return {"status":"found","record":data[plate.upper()]}
