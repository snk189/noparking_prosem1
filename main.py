from fastapi import FastAPI, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import json, os, base64, easyocr, cv2, numpy as np, re

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

DATA_FILE = "data.json"
FINE_AMOUNT = 100
BUFFER_SECONDS = 5
ocr = easyocr.Reader(['en'])
PLATE_REGEX = r"[A-Z]{2}[0-9]{1,2}[A-Z]{1,2}[0-9]{1,4}"

if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f: json.dump({}, f)

class Payment(BaseModel):
    number: str
    amount: int

def load(): return json.load(open(DATA_FILE))
def save(d): json.dump(d, open(DATA_FILE,"w"), indent=4)
def time(): return datetime.now().strftime("%d %B %Y - %I:%M:%S %p")

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
    return None,None

@app.post("/api/new_violation_image")
async def new(file: UploadFile=File(...)):
    img = await file.read()
    plate,imgb64 = detect(img)
    if not plate: return {"status":"error","message":"Plate not detected"}

    data = load()
    now = datetime.now()
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

    # Sort newest first
    record["break"] = sorted(record["break"], key=lambda x: datetime.strptime(x["time"], "%d %B %Y - %I:%M:%S %p"), reverse=True)

    # Filter by start date/time if provided
    if start:
        # default start_time if not provided
        if not start_time:
            start_time = "00:00:00"
        # Add seconds if only HH:MM
        if len(start_time)==5: start_time+=":00"
        start_dt = datetime.strptime(start + " " + start_time, "%Y-%m-%d %H:%M:%S")
        record["break"] = [b for b in record["break"] if datetime.strptime(b["time"], "%d %B %Y - %I:%M:%S %p") >= start_dt]

    return {"status":"found","record":record}
