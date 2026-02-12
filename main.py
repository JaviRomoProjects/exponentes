import os
import uvicorn
import socketio
import qrcode
import asyncio
import socket
import secrets
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
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
security = HTTPBasic()

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    current_username_bytes = credentials.username.encode("utf8")
    correct_username_bytes = os.getenv("HOST_USER", "alan").encode("utf8")
    is_correct_username = secrets.compare_digest(
        current_username_bytes, correct_username_bytes
    )
    
    current_password_bytes = credentials.password.encode("utf8")
    correct_password_bytes = os.getenv("HOST_PASSWORD", "alancometacos").encode("utf8")
    is_correct_password = secrets.compare_digest(
        current_password_bytes, correct_password_bytes
    )
    
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# --- HTTP Routes ---
@app.get("/")
async def get_participant_ui(request: Request):
    return templates.TemplateResponse("participant.html", {"request": request})

@app.get("/host")
async def get_host_ui(request: Request, username: str = Depends(verify_admin)):
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
    success, message = manager.create_teams(num)
    
    if not success:
        await sio.emit('host_error', {'message': message}, room=sid)
        return
        
    await broadcast_state()

@sio.event
async def host_start_prep(sid, data):
    sec = int(data.get('seconds', 300))
    manager.start_prep(sec)
    await broadcast_state()
    asyncio.create_task(timer_monitor_loop())

async def timer_monitor_loop():
    """Monitor timer and auto-advance when it reaches zero."""
    print("[DEBUG] Timer monitor loop started")
    while True:
        await asyncio.sleep(1)  # Check every second
        
        # Exit if in phases with no timer
        if manager.phase.value in ["LOBBY", "LEADERBOARD"]:
            print(f"[DEBUG] Timer monitor exiting - phase is {manager.phase.value}")
            break
        
        # Skip timer check if paused
        if manager.timer_paused:
            await broadcast_state()
            continue
        
        # Skip if no active timer
        if not manager.timer_end:
            # In VOTING phase, wait for manual advance
            if manager.phase.value == "VOTING":
                await broadcast_state()
                continue
            else:
                print(f"[DEBUG] Timer monitor exiting - no timer_end in phase {manager.phase.value}")
                break
        
        # Check remaining time
        current_time = asyncio.get_event_loop().time()
        remaining = max(0, int(manager.timer_end - current_time))
        
        # Broadcast current state
        await broadcast_state()
        
        # Check if timer expired
        if remaining <= 0:
            print(f"[DEBUG] Timer expired in phase {manager.phase.value}, auto-advancing")
            if manager.phase.value == "PREP":
                manager.next_presentation()
                print(f"[DEBUG] Advanced to PRESENTING phase")
                await broadcast_state()
                # Continue loop to monitor presentation timer
            elif manager.phase.value == "PRESENTING":
                manager.start_voting()
                print(f"[DEBUG] Advanced to VOTING phase")
                await broadcast_state()
                # Continue loop, will wait in VOTING until manual advance

@sio.event
async def host_start_presentations(sid, data):
    manager.next_presentation()
    await broadcast_state()

@sio.event
async def host_next_step(sid, data):
    print(f"[DEBUG] Manual next step from phase {manager.phase.value}")
    if manager.phase.value == "PRESENTING":
        manager.start_voting()
    elif manager.phase.value == "VOTING":
        manager.calculate_scores()
        manager.next_presentation()
        # Timer monitor loop should already be running and will pick up new timer
    elif manager.phase.value == "PREP":
        manager.next_presentation()
        # Timer monitor loop should already be running
    await broadcast_state()

@sio.event
async def host_restart_session(sid, data):
    print(f"[DEBUG] host_restart_session called from {sid}")
    manager.reset_session()
    await sio.emit('session_restart', {}, skip_sid=sid)
    await broadcast_state()
    print(f"[DEBUG] Session reset complete")

@sio.event
async def host_pause_timer(sid, data):
    print(f"[DEBUG] Pausing timer from {sid}")
    manager.pause_timer()
    await broadcast_state()

@sio.event
async def host_resume_timer(sid, data):
    print(f"[DEBUG] Resuming timer from {sid}")
    manager.resume_timer()
    await broadcast_state()

@sio.event
async def host_adjust_timer(sid, data):
    seconds = int(data.get('seconds', 0))
    print(f"[DEBUG] Adjusting timer by {seconds} seconds from {sid}")
    manager.adjust_timer(seconds)
    await broadcast_state()

@sio.event
async def host_reset_timer(sid, data):
    print(f"[DEBUG] Resetting timer from {sid}")
    manager.reset_timer()
    await broadcast_state()

@sio.event
async def cast_vote(sid, data):
    uid = data.get('user_id')
    score = int(data.get('score'))
    vote_recorded = manager.cast_vote(uid, score)
    
    if vote_recorded:
        await broadcast_state()
        
        # Check if all votes are in
        if manager.check_all_votes_received():
            print("[DEBUG] All votes received, auto-advancing")
            await asyncio.sleep(2)  # Brief pause for users to see results
            manager.calculate_scores()
            manager.next_presentation()
            await broadcast_state()

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