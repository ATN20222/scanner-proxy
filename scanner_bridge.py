import customtkinter as ctk
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import httpx
from fastapi.responses import StreamingResponse
from PIL import Image
import pystray
import threading
import asyncio
import sys
import socket
import time

# ---------------- Windows asyncio fix ----------------
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# --------------------- FastAPI Proxy ---------------------
class ScannerProxyApp:
    def __init__(self, scanner_url, frontend_url, host, port):
        self.scanner_url = scanner_url
        self.frontend_url = frontend_url
        self.host = host
        self.port = port
        self.app = FastAPI()

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=[self.frontend_url],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @self.app.post("/get_images")
        async def get_images(request: Request):
            body = await request.body()
            headers = dict(request.headers)
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.scanner_url}/get_images",
                    content=body,
                    headers=headers
                )
                return response.json()

        @self.app.get("/content/{path:path}")
        async def proxy_content(path: str):
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(f"{self.scanner_url}/content/{path}")
                return StreamingResponse(
                    resp.aiter_bytes(),
                    media_type=resp.headers.get("content-type")
                )

# --------------------- Uvicorn EXE-safe starter ---------------------
def start_uvicorn(app, host="127.0.0.1", port=8000):
    """
    EXE-safe Uvicorn starter with console logs.
    """
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",  # print logs to console
        access_log=True,
        log_config=None  # prevents isatty error in frozen EXE
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait until server is ready
    start = time.time()
    while True:
        try:
            with socket.create_connection((host, port), timeout=1):
                print(f"Server is ready on {host}:{port}")
                break
        except Exception:
            if time.time() - start > 10:  # 10 sec timeout
                print(f"ERROR: Server failed to start on {host}:{port}")
                break
            time.sleep(0.2)

    return server, thread

# --------------------- Desktop App ---------------------
class DesktopApp:
    def __init__(self):
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("Scanner Proxy Server")
        self.root.geometry("500x600")
        self.root.resizable(False, False)

        self.root.withdraw()  # Start hidden

        self.server_thread = None
        self.server_running = False
        self.server = None

        self.create_widgets()
        self.update_status()

        self.start_server()
        self.setup_tray_icon()

    def create_widgets(self):
        title = ctk.CTkLabel(self.root, text="Scanner Proxy Server",
                             font=ctk.CTkFont(size=20, weight="bold"))
        title.pack(pady=20)

        frame = ctk.CTkFrame(self.root)
        frame.pack(padx=20, fill="x")

        self.scanner_entry = self.field(frame, "Scanner URL", "http://localhost:15000")
        self.frontend_entry = self.field(frame, "Frontend URL", "http://192.168.1.8:5173")
        self.host_entry = self.field(frame, "Server Host", "127.0.0.1")
        self.port_entry = self.field(frame, "Server Port", "8000")

        self.update_btn = ctk.CTkButton(frame, text="Update Configuration",
                                        command=self.restart_server)
        self.update_btn.pack(pady=10)

        self.status_label = ctk.CTkLabel(self.root, text="Status: Stopped")
        self.status_label.pack(pady=10)

        btns = ctk.CTkFrame(self.root, fg_color="transparent")
        btns.pack()

        self.start_btn = ctk.CTkButton(btns, text="Start", command=self.start_server)
        self.stop_btn = ctk.CTkButton(btns, text="Stop", command=self.stop_server,
                                      state="disabled")

        self.start_btn.pack(side="left", padx=10)
        self.stop_btn.pack(side="right", padx=10)

    def field(self, parent, label, value):
        f = ctk.CTkFrame(parent)
        f.pack(fill="x", pady=5)
        ctk.CTkLabel(f, text=label).pack(side="left", padx=10)
        e = ctk.CTkEntry(f, width=260)
        e.pack(side="right", padx=10)
        e.insert(0, value)
        return e

    # ---------------- Server Control ----------------
    def start_server(self):
        if self.server_running:
            return

        proxy = ScannerProxyApp(
            self.scanner_entry.get(),
            self.frontend_entry.get(),
            self.host_entry.get(),
            int(self.port_entry.get())
        )

        self.server, self.server_thread = start_uvicorn(
            proxy.app,
            host=self.host_entry.get(),
            port=int(self.port_entry.get())
        )

        self.server_running = True
        self.update_status()

    def stop_server(self):
        if self.server_running:
            if self.server:
                self.server.should_exit = True
            self.server_running = False
            self.update_status()

    def restart_server(self):
        self.stop_server()
        time.sleep(0.5)
        self.start_server()

    def update_status(self):
        if self.server_running:
            self.status_label.configure(
                text=f"Status: Running on {self.host_entry.get()}:{self.port_entry.get()}"
            )
            self.start_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")
        else:
            self.status_label.configure(text="Status: Stopped")
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")

    # ---------------- Tray ----------------
    def setup_tray_icon(self):
        img = Image.new("RGB", (64, 64), "blue")
        menu = pystray.Menu(
            pystray.MenuItem("Show", self.show),
            pystray.MenuItem("Exit", self.exit)
        )
        self.tray = pystray.Icon("ScannerProxy", img, "Scanner Proxy", menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def show(self, *args):
        self.root.deiconify()
        self.root.lift()

    def exit(self, *args):
        if self.server_running and self.server:
            self.server.should_exit = True
        self.tray.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()

# --------------------- Main ---------------------
if __name__ == "__main__":
    DesktopApp().run()
