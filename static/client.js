const socket = io();

let myUserId = localStorage.getItem('workshop_uid');
let myName = localStorage.getItem('workshop_name');
let localTimerInterval = null; // To store the countdown ID

// --- 1. WAIT FOR PAGE LOAD ---
document.addEventListener('DOMContentLoaded', () => {
    // Check if we are on participant page (slider exists)
    const slider = document.getElementById('vote-slider');
    const valDisplay = document.getElementById('vote-val');
    if (slider && valDisplay) {
        slider.addEventListener('input', (e) => {
            valDisplay.innerText = e.target.value;
        });
    }

    // Auto-join logic
    const loginView = document.getElementById('view-login');
    if (loginView && myUserId && myName) {
        joinSocket(myUserId, myName);
    }
    const joinBtn = document.getElementById('btn-join');
    if (joinBtn) joinBtn.addEventListener('click', joinSession);
});

// --- 2. CORE FUNCTIONS ---

function joinSession() {
    const nameInput = document.getElementById('username');
    if (!nameInput || !nameInput.value) return alert("Name required");
    
    if (!myUserId) {
        myUserId = uuid.v4();
        localStorage.setItem('workshop_uid', myUserId);
    }
    
    myName = nameInput.value;
    localStorage.setItem('workshop_name', myName);
    joinSocket(myUserId, myName);
}

function joinSocket(uid, name) {
    socket.emit('join_session', { user_id: uid, name: name });
    const loginView = document.getElementById('view-login');
    if(loginView) loginView.classList.add('hidden');
    const lobby = document.getElementById('view-lobby');
    if(lobby) lobby.classList.remove('hidden');
}

// --- 3. SOCKET EVENT HANDLING ---

socket.on('session_restart', () => {
    console.log('[INFO] Session restarted - clearing localStorage');
    localStorage.removeItem('workshop_uid');
    localStorage.removeItem('workshop_name');
    myUserId = null;
    myName = null;
    location.reload();
});

socket.on('state_update', (state) => {
    // HOST LOGIC HOOK
    if(document.body.classList.contains('host-theme')) {
        // Start local timer for host too
        startLocalTimer(state.timer, ['timer-display']);
        
        if (window.renderHost) {
            window.renderHost(state);
        } else {
            setTimeout(() => { if(window.renderHost) window.renderHost(state); }, 50);
        }
        return; 
    }

    // PARTICIPANT LOGIC
    renderParticipant(state);
});

function renderParticipant(state) {
    if (!document.getElementById('view-login')) {
        setTimeout(() => renderParticipant(state), 100);
        return;
    }

    hideAllViews();
    const me = state.users[myUserId];
    if(!me) {
        safeShow('view-login');
        return;
    }

    // --- PHASE ROUTING ---
    if (state.phase === "LOBBY") {
        safeShow('view-lobby');
    
    } else if (state.phase === "PREP") {
        safeShow('view-prep');
        // Start countdown on prep-timer
        startLocalTimer(state.timer, ['prep-timer']);
        
        const myTeam = state.teams[me.team_id];
        if(myTeam) {
            safeText('my-team-name', myTeam.name);
            safeText('my-context', myTeam.context);
            const list = document.getElementById('my-teammates');
            if(list) {
                list.innerHTML = '';
                myTeam.members.forEach(mid => {
                    if(state.users[mid]) {
                        const li = document.createElement('li');
                        li.innerText = state.users[mid].name;
                        list.appendChild(li);
                    }
                });
            }
        }

    } else if (state.phase === "PRESENTING") {
        const presentingId = state.presenting_team_id;
        
        if (me.team_id === presentingId) {
            safeShow('view-speaker');
            startLocalTimer(state.timer, ['speaker-timer']);
        } else {
            safeShow('view-audience');
            const pTeam = state.teams[presentingId];
            if(pTeam) {
                safeText('presenting-team', pTeam.name);
                safeText('presenting-context', pTeam.context);
            }
        }
    
    } else if (state.phase === "VOTING") {
        if (me.team_id === state.presenting_team_id) {
            safeShow('view-lobby');
            safeText('lobby-msg', "Audience is voting...");
        } else {
            safeShow('view-voting');
            // Reset slider to default
            const slider = document.getElementById('vote-slider');
            if(slider) slider.value = 5;
            safeText('vote-val', "5");
        }
    
    } else if (state.phase === "LEADERBOARD") {
        safeShow('view-leaderboard');
        const ul = document.getElementById('final-scores');
        if(ul) {
            ul.innerHTML = '';
            const sortedTeams = Object.values(state.teams).sort((a,b) => b.score - a.score);
            sortedTeams.forEach(t => {
                const li = document.createElement('li');
                li.innerText = `${t.name}: ${t.score.toFixed(1)} pts`;
                if (t.id === sortedTeams[0].id) li.style.fontWeight = "bold";
                ul.appendChild(li);
            });
        }
    }
}

function submitVote() {
    const slider = document.getElementById('vote-slider');
    const val = slider ? slider.value : 5;
    
    socket.emit('cast_vote', {user_id: myUserId, score: val});
    
    hideAllViews();
    safeShow('view-lobby');
    safeText('lobby-msg', "Vote Sent. Waiting...");
}

// --- HELPER: REAL-TIME COUNTDOWN ---
function startLocalTimer(seconds, elementIds) {
    // Clear existing timer to prevent doubles
    if (localTimerInterval) clearInterval(localTimerInterval);
    
    let remaining = seconds;
    
    // Function to update all target elements
    const updateDisplays = () => {
        const m = Math.floor(remaining / 60);
        const s = remaining % 60;
        const text = `${m}:${s < 10 ? '0' : ''}${s}`;
        
        elementIds.forEach(id => {
            const el = document.getElementById(id);
            if(el) el.innerText = text;
        });
    };

    // Initial update
    updateDisplays();

    // Loop
    localTimerInterval = setInterval(() => {
        remaining--;
        if (remaining < 0) {
            remaining = 0;
            clearInterval(localTimerInterval);
        }
        updateDisplays();
    }, 1000);
}

// --- UTILS ---
function hideAllViews() {
    const ids = ['view-login', 'view-lobby', 'view-prep', 'view-audience', 'view-speaker', 'view-voting', 'view-leaderboard'];
    ids.forEach(id => {
        const el = document.getElementById(id);
        if(el) el.classList.add('hidden');
    });
}
function safeShow(id) {
    const el = document.getElementById(id);
    if(el) el.classList.remove('hidden');
}
function safeText(id, text) {
    const el = document.getElementById(id);
    if(el) el.innerText = text;
}