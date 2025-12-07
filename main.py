from fastapi import FastAPI
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

class Violation(BaseModel):
    number: str

# Initialize JSON if not exists
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({"records": []}, f)

def read_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def write_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

@app.post("/api/new_violation")
def add_violation(v: Violation):
    data = read_data()
    plate = v.number.upper()
    now = datetime.now()

    # Check last entry for buffer
    last_entry = None
    for record in reversed(data["records"]):
        if record["number"] == plate:
            last_entry = datetime.fromisoformat(record["timestamp"])
            break

    if last_entry and (now - last_entry).total_seconds() < BUFFER_SECONDS:
        return {"message": f"Already added recently. Wait {BUFFER_SECONDS} seconds."}

    # Add new record always
    new_record = {
        "number": plate,
        "timestamp": now.isoformat(),
        "fine": FINE_AMOUNT
    }
    data["records"].append(new_record)
    write_data(data)

    return {"message": f"Violation recorded for {plate}", "fine": FINE_AMOUNT}

@app.get("/api/get_vehicle/{plate}")
def get_vehicle_violations(plate: str):
    data = read_data()
    plate = plate.upper()
    records = [r for r in data["records"] if r["number"] == plate]
    return records

@app.get("/api/get_all")
def get_all_violations():
    return read_data()
