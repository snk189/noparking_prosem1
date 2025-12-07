from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import json
import os
import base64
import easyocr
import cv2
import numpy as np
import re

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

DATA_FILE = "data.json"
FINE_AMOUNT = 100
BUFFER_SECONDS = 5

# Indian number plate pattern
PLATE_PATTERN = r"[A-Z]{2}[0-9]{1,2}[A-Z]{1,2}[0-9]{1,4}"

# Initialize OCR
ocr_reader = easyocr.Reader(['en'])

# Create JSON if missing
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f, indent=4)

# Pydantic models
class Payment(BaseModel):
    number: str
    amount: int

# Helper functions
def read_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def write_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def formatted_time():
    return datetime.now().strftime("%d %B %Y - %I:%M:%S %p")

# Detect number plate and draw rectangle
def process_image(image_bytes):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    results = ocr_reader.readtext(img)
    detected_plate = None

    for bbox, text, prob in results:
        text_clean = text.replace(" ", "").upper()
        if re.fullmatch(PLATE_PATTERN, text_clean):
            detected_plate = text_clean
            # Draw rectangle and text
            (top_left, top_right, bottom_right, bottom_left) = bbox
            top_left = tuple([int(val) for val in top_left])
            bottom_right = tuple([int(val) for val in bottom_right])
            cv2.rectangle(img, top_left, bottom_right, (0, 255, 0), 2)
            cv2.putText(img, text_clean, (top_left[0], top_left[1]-10),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)
            break

    if detected_plate:
        _, buffer_img = cv2.imencode('.jpg', img)
        img_b64 = base64.b64encode(buffer_img).decode("utf-8")
        return detected_plate, f"data:image/jpeg;base64,{img_b64}"
    else:
        return None, None

# API: upload image and add violation
@app.post("/api/new_violation_image")
async def new_violation_image(file: UploadFile = File(...)):
    image_bytes = await file.read()
    plate, img_b64 = process_image(image_bytes)

    if not plate:
        return {"status": "error", "message": "No number plate detected."}

    data = read_data()
    now = datetime.now()

    # New vehicle
    if plate not in data:
        breakdown_item = {
            "type": "FINE",
            "amount": FINE_AMOUNT,
            "timestamp": formatted_time(),
            "image": img_b64
        }
        data[plate] = {
            "fine": FINE_AMOUNT,
            "breakdown": [breakdown_item],
            "last_update": now.isoformat()
        }
        write_data(data)
        return {"status": "added", "plate": plate, "fine": FINE_AMOUNT, "image": img_b64}

    # Existing vehicle: check buffer
    last_update = datetime.fromisoformat(data[plate]["last_update"])
    elapsed = (now - last_update).total_seconds()
    if elapsed < BUFFER_SECONDS:
        wait = BUFFER_SECONDS - int(elapsed)
        return {"status": "wait", "message": f"Please wait {wait} seconds before updating again.", "wait_time": wait}

    # Append new fine
    breakdown_item = {
        "type": "FINE",
        "amount": FINE_AMOUNT,
        "timestamp": formatted_time(),
        "image": img_b64
    }
    data[plate]["fine"] += FINE_AMOUNT
    data[plate]["breakdown"].append(breakdown_item)
    data[plate]["last_update"] = now.isoformat()
    write_data(data)

    return {"status": "updated", "plate": plate, "fine": data[plate]["fine"], "image": img_b64}

# API: pay fine
@app.post("/api/pay_fine")
def pay_fine(p: Payment):
    data = read_data()
    plate = p.number.upper().strip()
    amt = p.amount

    if plate not in data:
        return {"status": "no_record", "message": "No violation exists for this vehicle."}
    if data[plate]["fine"] == 0:
        return {"status": "no_dues", "message": "No dues to pay."}
    if amt > data[plate]["fine"]:
        return {"status": "excess", "message": f"Excess amount tried to pay ({amt} Rs). Payment unsuccessful.", "remaining_fine": data[plate]["fine"]}

    # Subtract and record payment
    data[plate]["fine"] -= amt
    payment_item = {"type": "PAYMENT", "amount": -amt, "timestamp": formatted_time()}
    data[plate]["breakdown"].append(payment_item)
    write_data(data)
    return {"status": "paid", "message": f"Payment successful. Remaining fine: {data[plate]['fine']} Rs", "remaining_fine": data[plate]["fine"]}

# API: get vehicle details
@app.get("/api/get_vehicle/{plate}")
def get_vehicle(plate: str):
    data = read_data()
    plate = plate.upper().strip()
    if plate not in data:
        return {"status": "no_record", "message": "No violation exists for this vehicle."}
    record = data[plate]
    if record["fine"] == 0:
        return {"status": "no_dues", "message": "No dues. All clear.", "record": record}
    return {"status": "found", "record": record}

# API: get all
@app.get("/api/get_all")
def get_all():
    return read_data()
