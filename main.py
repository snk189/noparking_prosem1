from fastapi import FastAPI, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import json, os, base64, easyocr, cv2, numpy as np, re
import requests
import asyncio
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
ESP32_CAM_URL = "https://raw.githubusercontent.com/snk189/project/main/car1.jpg"
FETCH_INTERVAL = 5  # seconds
LAST_IMAGE_HASH = None
IMAGE_HISTORY = set()

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
    return hashlib.md5(image_bytes).hexdigest()

def is_duplicate_image(image_bytes):
    current_hash = get_image_hash(image_bytes)
    if current_hash in IMAGE_HISTORY:
        return True
    if len(IMAGE_HISTORY) >= 10:
        IMAGE_HISTORY.pop()
    IMAGE_HISTORY.add(current_hash)
    return False

def detect_plates_advanced(img):
    """Main detection function that handles BOTH types of plates"""
    arr = np.frombuffer(img, np.uint8)
    im = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    
    # Store original for drawing
    original = im.copy()
    
    # Try multiple approaches
    approaches = [
        ("Standard_Plate", lambda x: detect_standard_plate(x)),
        ("InnerText_Plate", lambda x: detect_innertext_plate(x)),
        ("Enhanced_Contrast", lambda x: detect_enhanced_contrast(x)),
        ("Blue_Channel", lambda x: detect_blue_channel(x))
    ]
    
    all_detections = []
    
    for approach_name, approach_func in approaches:
        try:
            plate, processed_img = approach_func(original.copy())
            if plate:
                all_detections.append({
                    "plate": plate,
                    "approach": approach_name,
                    "image": processed_img,
                    "confidence": 1.0  # Simplified
                })
                print(f"✓ {approach_name} detected: {plate}")
        except Exception as e:
            print(f"✗ {approach_name} failed: {e}")
            continue
    
    # Choose the best detection
    if all_detections:
        # Prioritize plates matching regex exactly
        valid_detections = [d for d in all_detections if re.fullmatch(PLATE_REGEX, d["plate"])]
        if valid_detections:
            best = valid_detections[0]  # Take first valid
        else:
            best = all_detections[0]  # Fallback to any detection
        
        # Draw on original image
        cv2.putText(im, best["plate"], (50, 50), 
                   cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 0), 3)
        _, buf = cv2.imencode(".jpg", im)
        return best["plate"], base64.b64encode(buf).decode()
    
    # No plate found
    _, buf = cv2.imencode(".jpg", im)
    return None, base64.b64encode(buf).decode()

def detect_standard_plate(img):
    """Method 1: For normal plates without inner text"""
    # Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Basic threshold
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # Denoise
    denoised = cv2.medianBlur(thresh, 3)
    
    # OCR
    res = ocr.readtext(denoised)
    
    for box, txt, _ in res:
        clean = txt.replace(" ", "").upper().replace("O", "0").replace("I", "1").replace("Z", "2")
        if re.fullmatch(PLATE_REGEX, clean):
            return clean, thresh
    
    return None, thresh

def detect_innertext_plate(img):
    """Method 2: For plates with 'IND' text inside characters"""
    # Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # CLAHE for contrast
    clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    
    # Invert (make dark text white)
    inverted = cv2.bitwise_not(enhanced)
    
    # Morphological operations to remove small artifacts
    kernel = np.ones((2, 2), np.uint8)
    morphed = cv2.morphologyEx(inverted, cv2.MORPH_CLOSE, kernel)
    
    # Larger dilation to connect characters with inner text
    kernel2 = np.ones((3, 3), np.uint8)
    dilated = cv2.dilate(morphed, kernel2, iterations=1)
    
    # Threshold to make binary
    _, binary = cv2.threshold(dilated, 150, 255, cv2.THRESH_BINARY)
    
    # OCR with character whitelist
    custom_ocr = easyocr.Reader(['en'])
    res = custom_ocr.readtext(binary, allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
    
    # Try to extract plate from results
    plate_candidates = []
    for box, txt, conf in res:
        clean = txt.replace(" ", "").upper()
        # Remove obvious wrong characters
        clean = clean.replace("IND", "").replace("TIN", "").replace("INDIA", "")
        
        if len(clean) >= 6:  # Minimum plate length
            plate_candidates.append((clean, conf))
    
    # Try combinations of candidates
    for candidate, conf in sorted(plate_candidates, key=lambda x: x[1], reverse=True):
        # Check if it matches plate format
        if re.fullmatch(PLATE_REGEX, candidate):
            return candidate, binary
        
        # Try to extract plate from longer text
        # Look for patterns like XX##XXX### or similar
        for i in range(len(candidate) - 5):
            substring = candidate[i:i+10]
            if re.fullmatch(PLATE_REGEX, substring):
                return substring, binary
    
    return None, binary

def detect_enhanced_contrast(img):
    """Method 3: High contrast approach"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Extreme contrast
    clahe = cv2.createCLAHE(clipLimit=5.0, tileGridSize=(4, 4))
    enhanced = clahe.apply(gray)
    
    # Adaptive threshold
    adaptive = cv2.adaptiveThreshold(enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY, 21, 5)
    
    res = ocr.readtext(adaptive)
    for box, txt, _ in res:
        clean = txt.replace(" ", "").upper()
        if re.fullmatch(PLATE_REGEX, clean):
            return clean, adaptive
    
    return None, adaptive

def detect_blue_channel(img):
    """Method 4: Blue channel extraction (for blue plates)"""
    # Split channels
    b, g, r = cv2.split(img)
    
    # Blue channel often has best contrast for blue plates
    blue_enhanced = cv2.equalizeHist(b)
    
    # Threshold blue channel
    _, blue_thresh = cv2.threshold(blue_enhanced, 50, 255, cv2.THRESH_BINARY)
    
    res = ocr.readtext(blue_thresh)
    for box, txt, _ in res:
        clean = txt.replace(" ", "").upper()
        if re.fullmatch(PLATE_REGEX, clean):
            return clean, blue_thresh
    
    return None, blue_thresh

def detect(img):
    """Wrapper function - uses advanced detection"""
    return detect_plates_advanced(img)

async def fetch_esp32_cam_image():
    """Fetch image from ESP32-CAM server"""
    global LAST_IMAGE_HASH
    
    try:
        response = requests.get(ESP32_CAM_URL, timeout=5)
        
        if response.status_code == 200:
            image_bytes = response.content
            
            if len(image_bytes) < 1000:
                return None
            
            if is_duplicate_image(image_bytes):
                print(f"[{time()}] ESP32-CAM: Duplicate image, skipping")
                return None
            
            plate, imgb64 = detect(image_bytes)
            now = datetime.now()
            
            if not plate:
                no_plate_data = load_noplate()
                no_plate_data.append({"time": time(), "img": imgb64})
                save_noplate(no_plate_data)
                print(f"[{time()}] ESP32-CAM: No plate detected")
                return None
            
            data = load()
            
            if plate not in data:
                data[plate] = {
                    "fine": FINE_AMOUNT,
                    "last": now.isoformat(),
                    "break": [{"type": "FINE", "amount": FINE_AMOUNT, "time": time(), "img": imgb64}]
                }
                save(data)
                print(f"[{time()}] ESP32-CAM: New violation added - {plate} | Fine: {FINE_AMOUNT}")
                return plate
            
            elapsed = (now - datetime.fromisoformat(data[plate]["last"])).total_seconds()
            if elapsed < BUFFER_SECONDS:
                wait = BUFFER_SECONDS - int(elapsed)
                print(f"[{time()}] ESP32-CAM: Skipping {plate} - Please wait {wait} seconds")
                return None
            
            data[plate]["fine"] += FINE_AMOUNT
            data[plate]["last"] = now.isoformat()
            data[plate]["break"].append({"type": "FINE", "amount": FINE_AMOUNT, "time": time(), "img": imgb64})
            save(data)
            print(f"[{time()}] ESP32-CAM: Violation updated - {plate} | Fine: {data[plate]['fine']}")
            return plate
            
    except requests.exceptions.RequestException:
        return None
    except Exception as e:
        print(f"[{time()}] ESP32-CAM Error: {str(e)}")
        return None

async def background_esp32_fetcher():
    """Background task to continuously fetch images"""
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

@app.get("/api/esp32_status")
def esp32_status():
    try:
        response = requests.get(ESP32_CAM_URL, timeout=3)
        return {
            "status": "online" if response.status_code == 200 else "offline",
            "status_code": response.status_code,
            "message": "ESP32-CAM is responding" if response.status_code == 200 else "ESP32-CAM not responding"
        }
    except:
        return {"status": "offline", "message": "Cannot connect to ESP32-CAM"}

@app.get("/")
def root():
    return {"message": "Traffic Violation System API", "status": "running"}

# Debug endpoint to test different detection methods
@app.post("/api/test_detection")
async def test_detection(file: UploadFile = File(...)):
    """Test all detection methods on an uploaded image"""
    img = await file.read()
    arr = np.frombuffer(img, np.uint8)
    im = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    
    results = {}
    
    # Test all methods
    methods = [
        ("Standard_Plate", detect_standard_plate),
        ("InnerText_Plate", detect_innertext_plate),
        ("Enhanced_Contrast", detect_enhanced_contrast),
        ("Blue_Channel", detect_blue_channel)
    ]
    
    for method_name, method_func in methods:
        try:
            plate, processed_img = method_func(im.copy())
            _, buf = cv2.imencode(".jpg", processed_img)
            img_b64 = base64.b64encode(buf).decode()
            
            results[method_name] = {
                "plate": plate if plate else "Not detected",
                "image": img_b64,
                "status": "success" if plate else "failed"
            }
        except Exception as e:
            results[method_name] = {
                "plate": f"Error: {str(e)}",
                "image": "",
                "status": "error"
            }
    
    # Try main detection
    main_plate, main_img = detect_plates_advanced(im.copy())
    
    return {
        "main_detection": main_plate if main_plate else "Not detected",
        "main_image": main_img,
        "methods": results
    }
