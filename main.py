from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json, time, os
from datetime import datetime

app = FastAPI()
BUFFER_SECONDS = 10
DB_FILE = "violations.json"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if not os.path.exists(DB_FILE):
    with open(DB_FILE, "w") as f:
        json.dump({}, f)

class Violation(BaseModel):
    number: str

def load_db():
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)

@app.post("/api/new_violation")
def new_violation(v: Violation):
    db = load_db()
    plate = v.number.upper()
    current_time = time.time()
    
    if plate in db:
        last_entry = db[plate][-1]["timestamp"]
        diff = current_time - last_entry
        if diff < BUFFER_SECONDS:
            return {"message": f"Already added recently. Wait {int(BUFFER_SECONDS - diff)} secs."}
        # Add 100 Rs to the last entry
        db[plate][-1]["fine"] += 100
        db[plate][-1]["timestamp"] = current_time
    else:
        db[plate] = [{"timestamp": current_time, "fine": 100}]
    
    save_db(db)
    return {"message": "Violation recorded", "plate": plate}

@app.get("/api/get_vehicle/{plate}")
def get_vehicle(plate: str):
    db = load_db()
    plate = plate.upper()
    if plate not in db:
        return {"message": "No record found"}
    result = []
    total_fine = 0
    for entry in db[plate]:
        ts = datetime.fromtimestamp(entry["timestamp"])
        result.append({
            "date": ts.strftime("%d %B, %Y"),
            "time": ts.strftime("%H:%M:%S"),
            "fine": entry["fine"]
        })
        total_fine += entry["fine"]
    return {"plate": plate, "entries": result, "total_fine": total_fine}
