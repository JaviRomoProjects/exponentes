import random
import uuid
import asyncio
from enum import Enum
from contexts import TEAM_CONTEXTS

class Phase(Enum):
    LOBBY = "LOBBY"
    PREP = "PREP"
    PRESENTING = "PRESENTING"
    VOTING = "VOTING"
    LEADERBOARD = "LEADERBOARD"

class SessionManager:
    def __init__(self):
        self.users = {}
        self.teams = {}
        self.phase = Phase.LOBBY
        self.timer_end = None 
        self.presenting_team_id = None
        self.presented_teams = set()
        self.votes = {}

    def add_user(self, user_id, name, socket_id):
        if user_id not in self.users:
            self.users[user_id] = {
                "name": name, 
                "team_id": None, 
                "id": user_id,
                "connected": True
            }
        self.users[user_id]["socket_id"] = socket_id
        self.users[user_id]["connected"] = True
        return self.users[user_id]

    def remove_user(self, user_id):
        if user_id in self.users:
            del self.users[user_id]
            for t_id in self.teams:
                if user_id in self.teams[t_id]["members"]:
                    self.teams[t_id]["members"].remove(user_id)

    def disconnect_user(self, socket_id):
        for uid, user in self.users.items():
            if user["socket_id"] == socket_id:
                user["connected"] = False
                break

    def create_teams(self, num_teams):
        self.teams = {}
        self.presented_teams = set()
        active_users = [u for u in self.users.values()]
        random.shuffle(active_users)
        selected_contexts = random.sample(TEAM_CONTEXTS, min(num_teams, len(TEAM_CONTEXTS)))
        
        for i in range(num_teams):
            t_id = str(uuid.uuid4())
            self.teams[t_id] = {
                "id": t_id,
                "name": f"Team {i+1}",
                "members": [],
                "context": selected_contexts[i % len(selected_contexts)],
                "score": 0,
                "votes_current_round": [] 
            }
        
        team_ids = list(self.teams.keys())
        for i, user in enumerate(active_users):
            assigned_team = team_ids[i % num_teams]
            self.teams[assigned_team]["members"].append(user["id"])
            self.users[user["id"]]["team_id"] = assigned_team

    def start_prep(self, duration_seconds):
        self.phase = Phase.PREP
        self.timer_end = asyncio.get_event_loop().time() + duration_seconds

    def next_presentation(self):
        available = [t_id for t_id in self.teams if t_id not in self.presented_teams]
        
        if not available:
            self.phase = Phase.LEADERBOARD
            self.presenting_team_id = None
            self.timer_end = None # No timer for leaderboard
            return False

        next_team = random.choice(available)
        self.presenting_team_id = next_team
        self.presented_teams.add(next_team)
        self.phase = Phase.PRESENTING
        
        # --- NEW: Set 3 Minute Timer for Presentation ---
        self.timer_end = asyncio.get_event_loop().time() + 180 
        return True

    def start_voting(self):
        self.phase = Phase.VOTING
        self.timer_end = None # Hide timer during voting

    def cast_vote(self, user_id, score):
        if self.phase != Phase.VOTING or not self.presenting_team_id:
            return False
        presenting_members = self.teams[self.presenting_team_id]["members"]
        if user_id in presenting_members:
            return False
        self.teams[self.presenting_team_id]["votes_current_round"].append(score)
        return True

    def calculate_scores(self):
        if self.presenting_team_id:
            votes = self.teams[self.presenting_team_id]["votes_current_round"]
            if votes:
                avg = sum(votes) / len(votes)
                self.teams[self.presenting_team_id]["score"] += avg
            self.teams[self.presenting_team_id]["votes_current_round"] = []

    def reset_session(self):
        """Reset the session to lobby state, clearing teams and votes but keeping users."""
        self.teams = {}
        self.phase = Phase.LOBBY
        self.timer_end = None
        self.presenting_team_id = None
        self.presented_teams = set()
        self.votes = {}
        # Keep users but clear their team assignments
        for user in self.users.values():
            user["team_id"] = None

    def get_state(self):
        current_time = asyncio.get_event_loop().time()
        remaining = 0
        if self.timer_end:
            remaining = max(0, int(self.timer_end - current_time))

        return {
            "phase": self.phase.value,
            "timer": remaining,
            "users": self.users,
            "teams": self.teams,
            "presenting_team_id": self.presenting_team_id,
            "presented_teams": list(self.presented_teams)
        }