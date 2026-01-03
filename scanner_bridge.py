import customtkinter as ctk
import threading
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import httpx
from fastapi.responses import StreamingResponse
from PIL import Image, ImageDraw
import pystray

# --------------------- FastAPI Proxy ---------------------
class ScannerProxyApp:
    def __init__(self):
        self.app = FastAPI()
        self.scanner_url = "http://localhost:15000"
        self.frontend_url = "http://192.168.1.8:5173"
        self.server_thread = None
        self.server_running = False
        self.host = "0.0.0.0"
        self.port = 8000

        self.setup_fastapi()

    def setup_fastapi(self):
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
                try:
                    response = await client.post(f"{self.scanner_url}/get_images", content=body, headers=headers)
                    response.raise_for_status()
                    return response.json()
                except httpx.ReadTimeout:
                    return {"error": f"Scanner service timed out. Make sure it is running on {self.scanner_url}"}
                except Exception as e:
                    return {"error": f"Failed to reach scanner: {str(e)}"}

        @self.app.get("/content/{path:path}")
        async def proxy_content(path: str):
            url = f"{self.scanner_url}/content/{path}"
            async with httpx.AsyncClient(timeout=60.0) as client:
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    return StreamingResponse(resp.aiter_bytes(), media_type=resp.headers.get("content-type"))
                except Exception as e:
                    return {"error": f"Failed to fetch image from scanner: {str(e)}"}

    def update_config(self, scanner_url, frontend_url, host, port):
        self.scanner_url = scanner_url
        self.frontend_url = frontend_url
        self.host = host
        self.port = int(port)
        self.app = FastAPI()
        self.setup_fastapi()

    def run_server(self):
        try:
            uvicorn.run(self.app, host=self.host, port=self.port, log_level="info")
        except Exception as e:
            print(f"Server error: {e}")

# --------------------- Desktop App ---------------------
class DesktopApp:
    def __init__(self):
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("Scanner Proxy Server")
        self.root.geometry("500x600")
        self.root.resizable(False, False)

        # Hide from taskbar and minimize
        self.root.overrideredirect(True)  # removes window frame
        self.root.withdraw()  # hide at startup

        self.proxy_app = ScannerProxyApp()
        self.server_thread = None

        self.create_widgets()
        self.update_status()

        # Start server automatically
        self.start_server()

        # Setup system tray icon
        self.setup_tray_icon()

    # -------------------- GUI --------------------
    def create_widgets(self):
        # Title
        title_label = ctk.CTkLabel(self.root, text="Scanner Proxy Server", font=ctk.CTkFont(size=20, weight="bold"))
        title_label.pack(pady=20)

        # Configuration Frame
        config_frame = ctk.CTkFrame(self.root)
        config_frame.pack(pady=10, padx=20, fill="x")

        config_title = ctk.CTkLabel(config_frame, text="Configuration", font=ctk.CTkFont(weight="bold"))
        config_title.pack(pady=10)

        # Scanner URL
        scanner_frame = ctk.CTkFrame(config_frame)
        scanner_frame.pack(pady=5, padx=10, fill="x")
        ctk.CTkLabel(scanner_frame, text="Scanner URL:").pack(side="left", padx=10)
        self.scanner_entry = ctk.CTkEntry(scanner_frame, width=250)
        self.scanner_entry.pack(side="right", padx=10)
        self.scanner_entry.insert(0, "http://localhost:15000")

        # Frontend URL
        frontend_frame = ctk.CTkFrame(config_frame)
        frontend_frame.pack(pady=5, padx=10, fill="x")
        ctk.CTkLabel(frontend_frame, text="Frontend URL:").pack(side="left", padx=10)
        self.frontend_entry = ctk.CTkEntry(frontend_frame, width=250)
        self.frontend_entry.pack(side="right", padx=10)
        self.frontend_entry.insert(0, "http://192.168.1.8:5173")

        # Server Host
        host_frame = ctk.CTkFrame(config_frame)
        host_frame.pack(pady=5, padx=10, fill="x")
        ctk.CTkLabel(host_frame, text="Server Host:").pack(side="left", padx=10)
        self.host_entry = ctk.CTkEntry(host_frame, width=250)
        self.host_entry.pack(side="right", padx=10)
        self.host_entry.insert(0, "0.0.0.0")

        # Server Port
        port_frame = ctk.CTkFrame(config_frame)
        port_frame.pack(pady=5, padx=10, fill="x")
        ctk.CTkLabel(port_frame, text="Server Port:").pack(side="left", padx=10)
        self.port_entry = ctk.CTkEntry(port_frame, width=250)
        self.port_entry.pack(side="right", padx=10)
        self.port_entry.insert(0, "8000")

        # Update Config Button
        self.update_btn = ctk.CTkButton(config_frame, text="Update Configuration", command=self.update_configuration)
        self.update_btn.pack(pady=15)

        # Control Frame
        control_frame = ctk.CTkFrame(self.root)
        control_frame.pack(pady=20, padx=20, fill="x")

        # Status Label
        self.status_label = ctk.CTkLabel(control_frame, text="Status: Stopped", font=ctk.CTkFont(size=14))
        self.status_label.pack(pady=10)

        # Buttons Frame
        buttons_frame = ctk.CTkFrame(control_frame, fg_color="transparent")
        buttons_frame.pack(pady=10)

        # Start Button
        self.start_btn = ctk.CTkButton(buttons_frame, text="Start Server", command=self.start_server,
                                      fg_color="green", hover_color="dark green")
        self.start_btn.pack(side="left", padx=10)

        # Stop Button
        self.stop_btn = ctk.CTkButton(buttons_frame, text="Stop Server", command=self.stop_server,
                                     fg_color="red", hover_color="dark red", state="disabled")
        self.stop_btn.pack(side="right", padx=10)

        # Info Frame
        info_frame = ctk.CTkFrame(self.root)
        info_frame.pack(pady=10, padx=20, fill="x")

        info_text = """
This application acts as a proxy server between your frontend
and the scanner service. Configure the URLs above and click
'Update Configuration' before starting the server.

The server will forward requests from your frontend to the
scanner service and handle CORS automatically.
        """
        info_label = ctk.CTkLabel(info_frame, text=info_text, wraplength=450, justify="left")
        info_label.pack(pady=10, padx=10)

    # -------------------- Server Control --------------------
    def update_configuration(self):
        try:
            scanner_url = self.scanner_entry.get().strip()
            frontend_url = self.frontend_entry.get().strip()
            host = self.host_entry.get().strip()
            port = self.port_entry.get().strip()

            if not scanner_url or not frontend_url or not host or not port:
                return

            if not port.isdigit() or not (1 <= int(port) <= 65535):
                return

            self.proxy_app.update_config(scanner_url, frontend_url, host, port)

        except Exception as e:
            print(f"Failed to update configuration: {e}")

    def start_server(self):
        if self.proxy_app.server_running:
            return

        try:
            self.server_thread = threading.Thread(target=self.run_server_thread, daemon=True)
            self.server_thread.start()
            self.proxy_app.server_running = True
            self.update_status()
        except Exception as e:
            print(f"Failed to start server: {e}")

    def stop_server(self):
        if not self.proxy_app.server_running:
            return
        self.proxy_app.server_running = False
        self.update_status()

    def run_server_thread(self):
        try:
            self.proxy_app.run_server()
        except Exception as e:
            print(f"Server thread error: {e}")
        finally:
            self.proxy_app.server_running = False
            self.root.after(0, self.update_status)

    def update_status(self):
        if self.proxy_app.server_running:
            self.status_label.configure(text=f"Status: Running on {self.proxy_app.host}:{self.proxy_app.port}")
            self.start_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")
            self.update_btn.configure(state="disabled")
        else:
            self.status_label.configure(text="Status: Stopped")
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            self.update_btn.configure(state="normal")

    # -------------------- System Tray --------------------
    def setup_tray_icon(self):
        image = Image.new("RGB", (64, 64), color="blue")
        d = ImageDraw.Draw(image)
        d.rectangle([0, 0, 64, 64], fill="blue")

        menu = pystray.Menu(
            pystray.MenuItem("Show", self.show_window),
            pystray.MenuItem("Exit", self.exit_app)
        )

        self.tray_icon = pystray.Icon("ScannerProxy", image, "Scanner Proxy", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def show_window(self, icon=None, item=None):
        self.root.deiconify()
        self.root.overrideredirect(False)
        self.root.lift()  # bring to front

    def exit_app(self, icon=None, item=None):
        self.tray_icon.stop()
        self.stop_server()
        self.root.destroy()

    def run(self):
        self.root.mainloop()

# --------------------- Main ---------------------
if __name__ == "__main__":
    app = DesktopApp()
    app.run()
