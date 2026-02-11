const socket = io();

let myUserId = localStorage.getItem('workshop_uid');
let myName = localStorage.getItem('workshop_name');
let localTimerInterval = null; // To store the countdown ID
let previousPhase = null; // Track the previous phase to detect phase changes
let hasVoted = false; // Track if user has voted in current voting round

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

// Custom notification system
function showNotification(message, type = 'info', duration = 3000) {
    // Remove any existing notifications
    const existing = document.querySelector('.notification-toast');
    if (existing) existing.remove();
    
    // Create notification element
    const toast = document.createElement('div');
    toast.className = `notification-toast ${type}`;
    toast.innerText = message;
    document.body.appendChild(toast);
    
    // Trigger animation
    setTimeout(() => toast.classList.add('show'), 10);
    
    // Auto remove
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// Custom confirmation dialog
function showConfirm(message, onConfirm, onCancel) {
    // Create modal overlay
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    
    const modal = document.createElement('div');
    modal.className = 'modal-box';
    
    const messageEl = document.createElement('div');
    messageEl.className = 'modal-message';
    messageEl.innerText = message;
    
    const buttonsEl = document.createElement('div');
    buttonsEl.className = 'modal-buttons';
    
    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'btn-cancel';
    cancelBtn.innerText = 'Cancel';
    cancelBtn.onclick = () => {
        overlay.classList.remove('show');
        setTimeout(() => overlay.remove(), 300);
        if (onCancel) onCancel();
    };
    
    const confirmBtn = document.createElement('button');
    confirmBtn.innerText = 'Confirm';
    confirmBtn.onclick = () => {
        overlay.classList.remove('show');
        setTimeout(() => overlay.remove(), 300);
        if (onConfirm) onConfirm();
    };
    
    buttonsEl.appendChild(cancelBtn);
    buttonsEl.appendChild(confirmBtn);
    modal.appendChild(messageEl);
    modal.appendChild(buttonsEl);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);
    
    // Trigger animation
    setTimeout(() => overlay.classList.add('show'), 10);
}

function joinSession() {
    const nameInput = document.getElementById('username');
    if (!nameInput || !nameInput.value) {
        showNotification('Please enter your name', 'warning');
        return;
    }
    
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
    showNotification(`Welcome, ${name}!`, 'success', 2000);
}

socket.on('session_restart', () => {
    console.log('[INFO] Session restarted - clearing localStorage');
    showNotification('Session restarted. Reloading...', 'info', 2000);
    localStorage.removeItem('workshop_uid');
    localStorage.removeItem('workshop_name');
    myUserId = null;
    myName = null;
    setTimeout(() => location.reload(), 2000);
});

socket.on('state_update', (state) => {
    // HOST LOGIC HOOK
    if(document.body.classList.contains('host-theme')) {
        // Don't use local timer for host - use server state directly
        if (window.renderHost) {
            window.renderHost(state);
        } else {
            setTimeout(() => { if(window.renderHost) window.renderHost(state); }, 50);
        }
        return; 
    }

    // PARTICIPANT LOGIC
    // Start local timer for participants to reduce server load
    startLocalTimer(state.timer, ['timer-display']);
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
        previousPhase = state.phase;
        return;
    }

    if (state.phase === "LOBBY") {
        safeShow('view-lobby');
        hasVoted = false; // Reset vote flag when returning to lobby
    
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
        } else if (hasVoted) {
            // Already voted, show waiting screen
            safeShow('view-lobby');
            safeText('lobby-msg', "Vote Sent. Waiting...");
        } else {
            safeShow('view-voting');
            // Reset slider to default only on first entry to voting phase
            if (previousPhase !== "VOTING") {
                const slider = document.getElementById('vote-slider');
                if(slider) slider.value = 5;
                safeText('vote-val', "5");
                // Reset button state
                const button = document.getElementById('vote-button');
                if (button) {
                    button.disabled = false;
                    button.innerText = 'SUBMIT SCORE';
                }
            }
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
    
    // Update phase tracking at the end
    previousPhase = state.phase;
}

function submitVote() {
    const slider = document.getElementById('vote-slider');
    const button = document.getElementById('vote-button');
    const val = parseInt(slider ? slider.value : 5);
    
    // Immediate visual feedback
    if (button) {
        button.disabled = true;
        button.innerText = 'SENDING...';
    }
    
    socket.emit('cast_vote', {user_id: myUserId, score: val});
    hasVoted = true; // Mark as voted
    showNotification(`Vote submitted: ${val}/10`, 'success', 2000);
    
    // Small delay for visual feedback, then switch views
    setTimeout(() => {
        hideAllViews();
        safeShow('view-lobby');
        safeText('lobby-msg', "Vote Sent. Waiting...");
    }, 200);
}

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
