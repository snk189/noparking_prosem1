from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
import json
import os

app = FastAPI()

# Allow CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

DATA_FILE = "data.json"
FINE_AMOUNT = 100
BUFFER_SECONDS = 5  # 5-second buffer

# Pydantic models
class Violation(BaseModel):
    number: str

class Payment(BaseModel):
    number: str
    amount: int

# Load or initialize JSON
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({"records": []}, f, indent=4)

def read_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def write_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def find_record(data, plate):
    for rec in data["records"]:
        if rec["plate"] == plate:
            return rec
    return None

@app.post("/api/new_violation")
def add_violation(v: Violation):
    data = read_data()
    plate = v.number.upper()
    now = datetime.now()
    
    rec = find_record(data, plate)
    
    if not rec:
        # New vehicle
        data["records"].append({
            "plate": plate,
            "fine": FINE_AMOUNT,
            "breakdown": [{"type": "violation", "timestamp": now.strftime("%d-%B-%Y %H:%M:%S"), "amount": FINE_AMOUNT}]
        })
        write_data(data)
        return {"message": f"Violation recorded for {plate}", "fine": FINE_AMOUNT}
    
    # Existing plate, check buffer
    last_ts = datetime.strptime(rec["breakdown"][-1]["timestamp"], "%d-%B-%Y %H:%M:%S")
    diff = (now - last_ts).total_seconds()
    
    if diff < BUFFER_SECONDS:
        return {"message": f"Already added recently. Wait {BUFFER_SECONDS} seconds.", "wait_time": int(BUFFER_SECONDS - diff)}
    
    # Add violation
    rec["fine"] += FINE_AMOUNT
    rec["breakdown"].append({"type": "violation", "timestamp": now.strftime("%d-%B-%Y %H:%M:%S"), "amount": FINE_AMOUNT})
    write_data(data)
    return {"message": f"Violation updated for {plate}", "fine": rec["fine"]}

@app.post("/api/pay_fine")
def pay_fine(p: Payment):
    data = read_data()
    plate = p.number.upper()
    rec = find_record(data, plate)
    
    if not rec:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    
    if p.amount > rec["fine"]:
        return {"message": f"Payment unsuccessful. Tried to pay {p.amount} Rs but only {rec['fine']} Rs is due.", "remaining_fine": rec["fine"]}
    
    rec["fine"] -= p.amount
    now = datetime.now()
    rec["breakdown"].append({"type": "payment", "timestamp": now.strftime("%d-%B-%Y %H:%M:%S"), "amount": p.amount})
    write_data(data)
    return {"message": f"Payment of {p.amount} Rs successful.", "remaining_fine": rec["fine"]}

@app.get("/api/get_vehicle/{plate}")
def get_vehicle_violations(plate: str):
    data = read_data()
    plate = plate.upper()
    rec = find_record(data, plate)
    if not rec:
        return []
    return [rec]

@app.get("/api/get_all")
def get_all_violations():
    return read_data()
