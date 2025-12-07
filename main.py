from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import json
from pathlib import Path

app = FastAPI()

# Allow HTML/JS frontend to access API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# JSON file to store data
DB_FILE = Path("data.json")

# Initialize JSON file if not exists
if not DB_FILE.exists():
    with open(DB_FILE, "w") as f:
        json.dump({"violations": [], "cases": []}, f, indent=4)

# Helper functions
def read_db():
    with open(DB_FILE, "r") as f:
        return json.load(f)

def write_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)

# Pydantic model for POST
class ViolationIn(BaseModel):
    number: str

# Endpoints
@app.post("/api/new_violation")
def new_violation(data: ViolationIn):
    db = read_db()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = {"plate": data.number, "timestamp": timestamp, "violation": "Speeding"}
    db["violations"].append(entry)
    write_db(db)
    return {"message": "Violation recorded", "plate": data.number}

@app.get("/api/get_vehicle_logs")
def get_vehicle_logs():
    db = read_db()
    return db["violations"][::-1]  # latest first

@app.get("/api/get_cases")
def get_cases():
    db = read_db()
    return db["cases"]
