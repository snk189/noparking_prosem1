from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
import json
from pathlib import Path

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = Path("data.json")

# Initialize JSON if not exists
if not DB_FILE.exists():
    with open(DB_FILE, "w") as f:
        json.dump({"records": []}, f, indent=4)

def read_db():
    with open(DB_FILE, "r") as f:
        return json.load(f)

def write_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)

class ViolationIn(BaseModel):
    number: str

@app.post("/api/new_violation")
def new_violation(data: ViolationIn):
    db = read_db()
    now = datetime.now()
    timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
    fine = 100

    # Check last record of this vehicle
    last_record = None
    for record in reversed(db["records"]):
        if record["plate"] == data.number:
            last_record = record
            break

    if last_record:
        last_time = datetime.strptime(last_record["timestamp"], "%Y-%m-%d %H:%M:%S")
        if now - last_time < timedelta(hours=24):
            fine = last_record["fine"]  # No new fine within 24 hours
        else:
            fine = last_record["fine"] + 100  # Add 100 Rs

    entry = {
        "plate": data.number,
        "timestamp": timestamp_str,
        "violation": "Speeding",
        "fine": fine
    }
    db["records"].append(entry)
    write_db(db)
    return {"message": "Violation recorded", "plate": data.number, "fine": fine}

@app.get("/api/get_records")
def get_records():
    db = read_db()
    return db["records"][::-1]  # latest first
