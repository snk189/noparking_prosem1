from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
import json
import os

app = FastAPI()

# Allow CORS for local testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

DATA_FILE = "data.json"
FINE_AMOUNT = 100
BUFFER_SECONDS = 10  # 10-second buffer

# Pydantic model
class Violation(BaseModel):
    number: str

# Load or initialize JSON file
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

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
    
    if plate not in data:
        # First violation
        data[plate] = [{"timestamp": now.isoformat(), "fine": FINE_AMOUNT}]
        write_data(data)
        return {"message": f"Violation recorded for {plate}", "fine": FINE_AMOUNT}
    
    # Existing plate
    last_entry = datetime.fromisoformat(data[plate][-1]["timestamp"])
    diff = (now - last_entry).total_seconds()
    
    if diff < BUFFER_SECONDS:
        return {"message": f"Already added recently. Wait {BUFFER_SECONDS} seconds."}
    
    # Add fine (same entry updated if within 24h)
    last_24h = datetime.fromisoformat(data[plate][-1]["timestamp"])
    if (now - last_24h) >= timedelta(seconds=BUFFER_SECONDS):
        data[plate].append({"timestamp": now.isoformat(), "fine": FINE_AMOUNT})
    
    write_data(data)
    return {"message": f"Violation updated for {plate}", "fine": FINE_AMOUNT}

@app.get("/api/get_vehicle/{plate}")
def get_vehicle_violations(plate: str):
    data = read_data()
    plate = plate.upper()
    if plate not in data:
        return []
    return data[plate]

@app.get("/api/get_all")
def get_all_violations():
    return read_data()

