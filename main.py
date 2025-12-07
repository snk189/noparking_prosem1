from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional
import json, os, cv2, numpy as np, easyocr, re

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

DATA_FILE = "data.json"
EVIDENCE_DIR = "evidence"
FINE_AMOUNT = 100
BUFFER_SECONDS = 5  # buffer

if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f, indent=4)
if not os.path.exists(EVIDENCE_DIR):
    os.makedirs(EVIDENCE_DIR, exist_ok=True)

app.mount("/evidence", StaticFiles(directory=EVIDENCE_DIR), name="evidence")

class ViolationIn(BaseModel):
    number: str
    image_filename: Optional[str] = None

class Payment(BaseModel):
    number: str
    amount: int

def read_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def write_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def formatted_time():
    return datetime.now().strftime("%d %B %Y - %I:%M:%S %p")

def save_evidence_image(image: np.ndarray, plate: str):
    timestamp = datetime.now().strftime("%d-%b-%Y_%H-%M-%S")
    filename = f"{plate}_{timestamp}.jpg"
    path = os.path.join(EVIDENCE_DIR, filename)
    cv2.imwrite(path, image)
    return f"/evidence/{filename}"

@app.post("/api/new_violation_image")
async def new_violation_image(file: UploadFile = File(...)):
    image_bytes = await file.read()
    npimg = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(npimg, cv2.IMREAD_COLOR)
    reader = easyocr.Reader(['en'])
    results = reader.readtext(image)

    plate_pattern = r"[A-Z]{2}[0-9]{1,2}[A-Z]{1,2}[0-9]{1,4}"
    detected_plate = None

    for bbox, text, prob in results:
        text_clean = text.replace(" ", "").upper()
        if re.fullmatch(plate_pattern, text_clean):
            detected_plate = text_clean
            (top_left, top_right, bottom_right, bottom_left) = bbox
            top_left = tuple([int(val) for val in top_left])
            bottom_right = tuple([int(val) for val in bottom_right])
            cv2.rectangle(image, top_left, bottom_right, (0,255,0), 2)
            cv2.putText(image, text_clean, (top_left[0], top_left[1]-10),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)
            break

    if not detected_plate:
        return {"status":"error","message":"No number plate detected."}

    plate = detected_plate
    data = read_data()
    now = datetime.now()

    # Buffer check
    if plate in data:
        last_update = datetime.fromisoformat(data[plate]["last_update"])
        elapsed = (now - last_update).total_seconds()
        if elapsed < BUFFER_SECONDS:
            wait = BUFFER_SECONDS - int(elapsed)
            return {"status":"wait","message":f"Please wait {wait} seconds before updating again.", "wait_time":wait}

    # Save evidence image
    evidence_url = save_evidence_image(image, plate)

    breakdown_item = {
        "type":"FINE",
        "amount":FINE_AMOUNT,
        "timestamp":formatted_time(),
        "image":evidence_url
    }

    if plate not in data:
        data[plate] = {"fine":FINE_AMOUNT, "breakdown":[breakdown_item], "last_update": now.isoformat()}
    else:
        data[plate]["fine"] += FINE_AMOUNT
        data[plate]["breakdown"].append(breakdown_item)
        data[plate]["last_update"] = now.isoformat()

    write_data(data)
    return {"status":"success","message":f"Violation recorded for {plate}","fine":data[plate]["fine"],"image":evidence_url}

@app.post("/api/pay_fine")
def pay_fine(p: Payment):
    data = read_data()
    plate = p.number.upper().strip()
    amt = p.amount
    if plate not in data:
        return {"status":"no_record","message":"No violation exists for this vehicle."}
    if data[plate]["fine"] == 0:
        return {"status":"no_dues","message":"No dues to pay."}
    if amt > data[plate]["fine"]:
        return {"status":"excess","message":f"Excess amount tried to pay ({amt} Rs). Payment unsuccessful.", "remaining_fine": data[plate]["fine"]}

    data[plate]["fine"] -= amt
    payment_item = {"type":"PAYMENT","amount":-amt,"timestamp":formatted_time()}
    data[plate]["breakdown"].append(payment_item)
    write_data(data)
    return {"status":"paid","message":f"Payment successful. Remaining fine: {data[plate]['fine']} Rs","remaining_fine":data[plate]["fine"]}

@app.get("/api/get_vehicle/{plate}")
def get_vehicle(plate: str):
    data = read_data()
    plate = plate.upper().strip()
    if plate not in data:
        return {"status":"no_record","message":"No violation exists for this vehicle."}
    if data[plate]["fine"] == 0:
        return {"status":"no_dues","message":"No dues. All clear.","record":data[plate]}
    return {"status":"found","record":data[plate]}

@app.get("/api/get_all")
def get_all():
    return read_data()
