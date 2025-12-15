from fastapi import FastAPI, UploadFile, File, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import json, os, base64, easyocr, cv2, numpy as np, re
import requests
import asyncio
from typing import Optional
import hashlib

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

DATA_FILE = "data.json"
NO_PLATE_FILE = "no_plate.json"
FINE_AMOUNT = 100
BUFFER_SECONDS = 5
ocr = easyocr.Reader(['en'])
PLATE_REGEX = r"[A-Z]{2}[0-9]{1,2}[A-Z]{1,2}[0-9]{1,4}"

# ESP32-CAM configuration
ESP32_CAM_URL = "https://images.drivespark.com/img/2018/04/vehicles-will-soon-come-fitted-with-number-plates8-1522648047.jpg"  # Change this to your ESP32-CAM IP
FETCH_INTERVAL = 5  # seconds
LAST_IMAGE_HASH = None  # To prevent duplicates
IMAGE_HISTORY = set()  # Store recent image hashes to prevent duplicates

if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f: json.dump({}, f)
if not os.path.exists(NO_PLATE_FILE):
    with open(NO_PLATE_FILE, "w") as f: json.dump([], f)

class Payment(BaseModel):
    number: str
    amount: int

def load(): return json.load(open(DATA_FILE))
def save(d): json.dump(d, open(DATA_FILE,"w"), indent=4)
def load_noplate(): return json.load(open(NO_PLATE_FILE))
def save_noplate(d): json.dump(d, open(NO_PLATE_FILE,"w"), indent=4)
def time(): return datetime.now().strftime("%d %B %Y - %I:%M:%S %p")

def get_image_hash(image_bytes):
    """Generate hash for image to detect duplicates"""
    return hashlib.md5(image_bytes).hexdigest()

def is_duplicate_image(image_bytes):
    """Check if image is similar to recent ones"""
    current_hash = get_image_hash(image_bytes)
    
    # Check against recent history
    if current_hash in IMAGE_HISTORY:
        return True
    
    # Keep only last 10 image hashes in history
    if len(IMAGE_HISTORY) >= 10:
        IMAGE_HISTORY.pop()
    
    IMAGE_HISTORY.add(current_hash)
    return False

def detect(img):
    arr = np.frombuffer(img, np.uint8)
    im = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    res = ocr.readtext(im)
    for box, txt, _ in res:
        clean = txt.replace(" ","").upper()
        if re.fullmatch(PLATE_REGEX, clean):
            tl,_,br,_ = map(lambda p: tuple(map(int,p)), box)
            cv2.rectangle(im, tl, br, (0,255,0), 2)
            cv2.putText(im, clean, (tl[0], tl[1]-10),
                        cv2.FONT_HERSHEY_SIMPLEX,1,(0,255,0),2)
            _, buf = cv2.imencode(".jpg", im)
            return clean, base64.b64encode(buf).decode()
    _, buf = cv2.imencode(".jpg", im)
    return None, base64.b64encode(buf).decode()

async def fetch_esp32_cam_image():
    """Fetch image from ESP32-CAM server"""
    global LAST_IMAGE_HASH
    
    try:
        # Fetch image from ESP32-CAM
        response = requests.get(ESP32_CAM_URL, timeout=5)
        
        if response.status_code == 200:
            image_bytes = response.content
            
            # Skip if image is too small (likely empty)
            if len(image_bytes) < 1000:
                return None
            
            # Check for duplicates
            if is_duplicate_image(image_bytes):
                return None
            
            # Process the image
            plate, imgb64 = detect(image_bytes)
            now = datetime.now()
            
            if not plate:
                # No plate detected
                no_plate_data = load_noplate()
                no_plate_data.append({"time": time(), "img": imgb64})
                save_noplate(no_plate_data)
                print(f"[{time()}] ESP32-CAM: No plate detected")
                return
            
            # Plate detected, process violation
            data = load()
            
            if plate not in data:
                data[plate] = {
                    "fine": FINE_AMOUNT,
                    "last": now.isoformat(),
                    "break": [{"type": "FINE", "amount": FINE_AMOUNT, "time": time(), "img": imgb64}]
                }
                save(data)
                print(f"[{time()}] ESP32-CAM: New violation added - {plate} | Fine: {FINE_AMOUNT}")
                return
            
            elapsed = (now - datetime.fromisoformat(data[plate]["last"])).total_seconds()
            if elapsed < BUFFER_SECONDS:
                wait = BUFFER_SECONDS - int(elapsed)
                print(f"[{time()}] ESP32-CAM: Skipping {plate} - Please wait {wait} seconds")
                return
            
            data[plate]["fine"] += FINE_AMOUNT
            data[plate]["last"] = now.isoformat()
            data[plate]["break"].append({"type": "FINE", "amount": FINE_AMOUNT, "time": time(), "img": imgb64})
            save(data)
            print(f"[{time()}] ESP32-CAM: Violation updated - {plate} | Fine: {data[plate]['fine']}")
            
    except requests.exceptions.RequestException as e:
        # Silently handle connection errors (ESP32-CAM might be offline)
        pass
    except Exception as e:
        # Log other errors but don't crash
        print(f"[{time()}] ESP32-CAM Error: {str(e)}")

async def background_esp32_fetcher():
    """Background task to continuously fetch images from ESP32-CAM"""
    while True:
        await fetch_esp32_cam_image()
        await asyncio.sleep(FETCH_INTERVAL)

@app.on_event("startup")
async def startup_event():
    """Start background task when FastAPI starts"""
    asyncio.create_task(background_esp32_fetcher())

@app.post("/api/new_violation_image")
async def new(file: UploadFile=File(...)):
    img = await file.read()
    plate,imgb64 = detect(img)
    now = datetime.now()
    if not plate:
        no_plate_data = load_noplate()
        no_plate_data.append({"time": time(), "img": imgb64})
        save_noplate(no_plate_data)
        return {"status":"noplate","message":"No plate detected", "img": imgb64, "time": time()}

    data = load()
    if plate not in data:
        data[plate] = {
            "fine":FINE_AMOUNT,
            "last":now.isoformat(),
            "break":[{"type":"FINE","amount":FINE_AMOUNT,"time":time(),"img":imgb64}]
        }
        save(data)
        return {"status":"added","plate":plate,"fine":FINE_AMOUNT}

    elapsed = (now - datetime.fromisoformat(data[plate]["last"])).total_seconds()
    if elapsed < BUFFER_SECONDS:
        wait = BUFFER_SECONDS - int(elapsed)
        return {"status":"wait","message":f"Please wait {wait} seconds before adding again.", "wait_time": wait}

    data[plate]["fine"] += FINE_AMOUNT
    data[plate]["last"] = now.isoformat()
    data[plate]["break"].append({"type":"FINE","amount":FINE_AMOUNT,"time":time(),"img":imgb64})
    save(data)
    return {"status":"updated","plate":plate,"fine":data[plate]["fine"]}

@app.post("/api/pay_fine")
def pay(p: Payment):
    data = load()
    n = p.number.upper()
    if n not in data: return {"status":"no_record","message":"No violation exists for this vehicle."}
    if p.amount > data[n]["fine"]:
        return {"status":"excess","message":f"Excess payment tried ({p.amount} Rs). Remaining fine: {data[n]['fine']} Rs"}

    data[n]["fine"] -= p.amount
    data[n]["break"].append({"type":"PAY","amount":-p.amount,"time":time(),"img":None})
    save(data)
    return {"status":"paid","message":f"Payment successful. Remaining fine: {data[n]['fine']} Rs", "remaining": data[n]["fine"]}

@app.get("/api/get_vehicle/{p}")
def get_v(p:str, start: str = Query(None), start_time: str = Query(None)):
    data = load()
    key = p.upper()
    if key not in data: return {"status":"no_record","message":"No record found"}
    record = data[key]

    record["break"] = sorted(record["break"], key=lambda x: datetime.strptime(x["time"], "%d %B %Y - %I:%M:%S %p"), reverse=True)

    if start:
        if not start_time: start_time = "00:00:00"
        if len(start_time)==5: start_time+=":00"
        start_dt = datetime.strptime(start + " " + start_time, "%Y-%m-%d %H:%M:%S")
        record["break"] = [b for b in record["break"] if datetime.strptime(b["time"], "%d %B %Y - %I:%M:%S %p") >= start_dt]

    return {"status":"found","record":record}

@app.get("/api/recent_violations")
def recent():
    data = load()
    all_violations = []
    for plate, rec in data.items():
        total_fine = sum(b["amount"] for b in rec["break"] if b["type"]=="FINE")
        total_paid = sum(-b["amount"] for b in rec["break"] if b["type"]=="PAY")
        remaining = rec["fine"]
        latest = max([b for b in rec["break"] if b["type"]=="FINE"], 
                     key=lambda x: datetime.strptime(x["time"], "%d %B %Y - %I:%M:%S %p"), default=None)
        if latest:
            all_violations.append({
                "plate": plate,
                "time": latest["time"],
                "img": latest["img"],
                "total_fine": total_fine,
                "total_paid": total_paid,
                "remaining": remaining
            })

    all_violations = sorted(all_violations, key=lambda x: datetime.strptime(x["time"], "%d %B %Y - %I:%M:%S %p"), reverse=True)
    return {"recent": all_violations[:5]}

@app.get("/api/no_plate")
def get_noplate():
    return {"noplate": load_noplate()}

# API to manually check ESP32-CAM status
@app.get("/api/esp32_status")
def esp32_status():
    """Check if ESP32-CAM is accessible"""
    try:
        response = requests.get(ESP32_CAM_URL, timeout=3)
        return {
            "status": "online" if response.status_code == 200 else "offline",
            "status_code": response.status_code,
            "message": "ESP32-CAM is responding" if response.status_code == 200 else "ESP32-CAM not responding"
        }
    except:
        return {"status": "offline", "message": "Cannot connect to ESP32-CAM"}
