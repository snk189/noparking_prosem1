from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
import json
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

DATA_FILE = "data.json"
FINE_AMOUNT = 100
BUFFER_SECONDS = 5  # 5 seconds wait

class Violation(BaseModel):
    number: str

class Payment(BaseModel):
    number: str
    amount: int

if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

def read_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def write_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def formatted_time():
    return datetime.now().strftime("%d %B %Y - %I:%M:%S %p")

@app.post("/api/new_violation")
def add_violation(v: Violation):
    data = read_data()
    plate = v.number.upper()
    now = datetime.now()

    if plate not in data:
        data[plate] = {
            "fine": FINE_AMOUNT,
            "breakdown": [{"type": "FINE", "amount": FINE_AMOUNT, "timestamp": formatted_time()}],
            "last_update": now.isoformat()
        }
        write_data(data)
        return {"message": f"Violation recorded for {plate}", "fine": FINE_AMOUNT}

    last_time = datetime.fromisoformat(data[plate]["last_update"])
    diff = (now - last_time).total_seconds()

    if diff < BUFFER_SECONDS:
        wait = BUFFER_SECONDS - int(diff)
        return {"message": f"Please wait {wait} seconds before updating again."}

    data[plate]["fine"] += FINE_AMOUNT
    data[plate]["breakdown"].append({"type": "FINE", "amount": FINE_AMOUNT, "timestamp": formatted_time()})
    data[plate]["last_update"] = now.isoformat()
    write_data(data)

    return {"message": f"Violation updated for {plate}", "fine": data[plate]["fine"]}


@app.get("/api/get_vehicle/{plate}")
def get_vehicle_violations(plate: str):
    data = read_data()
    plate = plate.upper()

    if plate not in data:
        return {"status": "no_record"}

    if data[plate]["fine"] == 0:
        return {"status": "no_dues"}

    return {"status": "found", "record": data[plate]}


@app.post("/api/pay_fine")
def pay_fine(p: Payment):
    data = read_data()
    plate = p.number.upper()
    amt = p.amount

    if plate not in data:
        return {"status": "no_record", "message": "No violation exists for this vehicle."}

    if data[plate]["fine"] == 0:
        return {"status": "no_dues", "message": "No dues to pay."}

    if amt > data[plate]["fine"]:
        return {"status": "excess", "message": "Excess amount tried to pay. Payment unsuccessful."}

    data[plate]["fine"] -= amt
    data[plate]["breakdown"].append({"type": "PAYMENT", "amount": -amt, "timestamp": formatted_time()})
    write_data(data)

    return {"status": "paid", "message": f"Payment successful. Remaining fine: {data[plate]['fine']}", "remaining": data[plate]["fine"]}
