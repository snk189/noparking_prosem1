# Traffic Violation Detection System

This project detects vehicle number plates from images and manages traffic fines.  
It uses OCR and image processing to read plates and keeps a record of violations and payments.

## What it does
- Detects number plates from uploaded images  
- Can fetch images automatically from ESP32-CAM  
- Allows manual entry of plate numbers  
- Tracks fines and payments  
- Shows recent violations  
- Stores images where no plate is detected  

## Tech Used
FastAPI, EasyOCR, OpenCV, HTML, CSS, JavaScript, JSON storage.

## How to Run

Install packages:
pip install fastapi uvicorn easyocr opencv-python numpy python-multipart requests


Start server:
uvicorn main:app --reload

Open `index.html` in browser.

## API
- `/api/new_violation_image` – Upload image  
- `/api/manual_violation` – Add violation manually  
- `/api/pay_fine` – Pay fine  
- `/api/get_vehicle/{plate}` – Get vehicle details  

## Notes
- Plate format supported: KA01AB1234  
- Default fine: 100 Rs  
- System ignores duplicate captures within 5 seconds  
