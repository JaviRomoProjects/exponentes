import os
import uvicorn
import socketio
import qrcode
import asyncio
import socket
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from session_manager import SessionManager

# --- Setup ---
app = FastAPI()
# Allow all origins to prevent CORS issues on local network
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
socket_app = socketio.ASGIApp(sio, app)

# Mount Static & Templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Initialize Logic
manager = SessionManager()

# --- HTTP Routes ---
@app.get("/")
async def get_participant_ui(request: Request):
    return templates.TemplateResponse("participant.html", {"request": request})

@app.get("/host")
async def get_host_ui(request: Request):
    return templates.TemplateResponse("host.html", {"request": request})

# --- Socket.IO Events ---

async def broadcast_state():
    state = manager.get_state()
    await sio.emit('state_update', state)

@sio.event
async def connect(sid, environ):
    print(f"Client connected: {sid}")

@sio.event
async def disconnect(sid):
    manager.disconnect_user(sid)
    await broadcast_state()

@sio.event
async def join_session(sid, data):
    user_id = data.get('user_id')
    name = data.get('name')
    user = manager.add_user(user_id, name, sid)
    await sio.emit('identity_confirmed', {'user_id': user_id, 'name': name}, room=sid)
    await broadcast_state()

# --- Host Controls ---

@sio.event
async def host_create_teams(sid, data):
    num = int(data.get('num_teams', 2))
    manager.create_teams(num)
    await broadcast_state()

@sio.event
async def host_start_prep(sid, data):
    sec = int(data.get('seconds', 300))
    manager.start_prep(sec)
    await broadcast_state()
    asyncio.create_task(timer_loop(sec))

async def timer_loop(seconds):
    await asyncio.sleep(seconds)
    # Timer finishes silently; state remains in PREP until host clicks 'Next'
    # or you could broadcast a "time's up" message here.

@sio.event
async def host_start_presentations(sid, data):
    manager.next_presentation()
    await broadcast_state()

@sio.event
async def host_next_step(sid, data):
    if manager.phase.value == "PRESENTING":
        manager.start_voting()
    elif manager.phase.value == "VOTING":
        manager.calculate_scores()
        manager.next_presentation()
    elif manager.phase.value == "PREP":
        manager.next_presentation()
    await broadcast_state()

@sio.event
async def cast_vote(sid, data):
    uid = data.get('user_id')
    score = int(data.get('score'))
    manager.cast_vote(uid, score)

# --- Execution ---
if __name__ == "__main__":
    # --- FIXED CONNECTION LOGIC START ---
    def get_local_ip():
        """
        Connects to a public DNS server (Google's 8.8.8.8) to determine
        which local network interface is being used for internet traffic.
        This effectively finds your machine's LAN IP (e.g., 192.168.1.5).
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # This doesn't actually send data, just checks routing
            s.connect(('8.8.8.8', 80))
            IP = s.getsockname()[0]
        except Exception:
            IP = '127.0.0.1'
        finally:
            s.close()
        return IP

    port = int(os.getenv("PORT", "8000"))
    external_url = os.getenv("RENDER_EXTERNAL_URL")
    is_cloud = bool(os.getenv("RENDER")) or external_url is not None or os.getenv("PORT") is not None

    if is_cloud:
        url = external_url or f"http://localhost:{port}"
        print("\n" + "="*40)
        print(" WORKSHOP TOOL STARTED (CLOUD)")
        print("="*40)
        print(f" -> HOST PANEL:    {url}/host")
        print(f" -> PARTICIPANTS:  {url}")
        print("="*40 + "\n")
    else:
        local_ip = get_local_ip()
        url = f"http://{local_ip}:{port}"
        
        print("\n" + "="*40)
        print(f" WORKSHOP TOOL STARTED")
        print(f" Host Machine IP: {local_ip}")
        print("="*40)
        print(f" -> HOST PANEL:    {url}/host")
        print(f" -> PARTICIPANTS:  {url}")
        print("="*40 + "\n")

        # Generate QR Code for the valid LAN URL
        qr = qrcode.QRCode()
        qr.add_data(url)
        qr.print_ascii()

    # Host='0.0.0.0' is crucial: it allows external connections
    uvicorn.run(socket_app, host="0.0.0.0", port=port)
    # --- FIXED CONNECTION LOGIC END ---