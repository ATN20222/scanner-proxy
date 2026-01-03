from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import httpx
from fastapi.responses import StreamingResponse

app = FastAPI()

# Allow all frontend domains
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://192.168.1.8:5173"],  # <-- exact frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


SCANNER_URL = "http://localhost:15000"

# POST /get_images -> forward to scanner
@app.post("/get_images")
async def get_images(request: Request):
    body = await request.body()
    headers = dict(request.headers)

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(f"{SCANNER_URL}/get_images", content=body, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.ReadTimeout:
            return {"error": "Scanner service timed out. Make sure it is running on localhost:15000"}
        except Exception as e:
            return {"error": f"Failed to reach scanner: {str(e)}"}

# GET /content/... -> forward to scanner
@app.get("/content/{path:path}")
async def proxy_content(path: str):
    url = f"{SCANNER_URL}/content/{path}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return StreamingResponse(resp.aiter_bytes(), media_type=resp.headers.get("content-type"))
        except Exception as e:
            return {"error": f"Failed to fetch image from scanner: {str(e)}"}
