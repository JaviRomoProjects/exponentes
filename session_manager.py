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
        self.timer_paused = False
        self.paused_time_remaining = 0
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
        active_users = [u for u in self.users.values() if u.get("connected", False)]
        
        # Validation: prevent creating more teams than users
        if num_teams > len(active_users):
            print(f"[DEBUG] create_teams failed: {num_teams} teams requested but only {len(active_users)} users connected")
            return False, f"Not enough users. Connected: {len(active_users)}, Requested Teams: {num_teams}"
            
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
                "votes_current_round": [],
                "voters_this_round": set()
            }
        
        team_ids = list(self.teams.keys())
        for i, user in enumerate(active_users):
            assigned_team = team_ids[i % num_teams]
            self.teams[assigned_team]["members"].append(user["id"])
            self.users[user["id"]]["team_id"] = assigned_team
            
        return True, f"Successfully created {num_teams} teams"

    def start_prep(self, duration_seconds):
        self.phase = Phase.PREP
        self.timer_end = asyncio.get_event_loop().time() + duration_seconds
        self.timer_paused = False
        self.paused_time_remaining = 0

    def next_presentation(self):
        available = [t_id for t_id in self.teams if t_id not in self.presented_teams]
        
        if not available:
            self.phase = Phase.LEADERBOARD
            self.presenting_team_id = None
            self.timer_end = None
            self.timer_paused = False
            self.paused_time_remaining = 0
            return False

        next_team = random.choice(available)
        self.presenting_team_id = next_team
        self.presented_teams.add(next_team)
        self.phase = Phase.PRESENTING
        
        # Set 3 Minute Timer for Presentation
        self.timer_end = asyncio.get_event_loop().time() + 180
        self.timer_paused = False
        self.paused_time_remaining = 0
        return True

    def start_voting(self):
        self.phase = Phase.VOTING
        self.timer_end = None
        self.timer_paused = False
        self.paused_time_remaining = 0
        # Track who has voted for this round
        if self.presenting_team_id:
            self.teams[self.presenting_team_id]["voters_this_round"] = set()

    def cast_vote(self, user_id, score):
        if self.phase != Phase.VOTING or not self.presenting_team_id:
            return False
        presenting_members = self.teams[self.presenting_team_id]["members"]
        if user_id in presenting_members:
            return False
        
        # Check if user already voted
        voters_set = self.teams[self.presenting_team_id].get("voters_this_round", set())
        if user_id in voters_set:
            print(f"[DEBUG] User {user_id} already voted, ignoring duplicate")
            return False
        
        # Record vote
        self.teams[self.presenting_team_id]["votes_current_round"].append(score)
        voters_set.add(user_id)
        self.teams[self.presenting_team_id]["voters_this_round"] = voters_set
        
        print(f"[DEBUG] Vote recorded. {len(voters_set)} votes received")
        return True

    def check_all_votes_received(self):
        """Check if all eligible voters have voted."""
        if not self.presenting_team_id or self.phase != Phase.VOTING:
            return False
        
        # Count eligible voters (all connected users minus presenting team)
        presenting_members = set(self.teams[self.presenting_team_id]["members"])
        eligible_voters = [uid for uid, user in self.users.items() 
                          if user.get("connected", True) and uid not in presenting_members]
        
        votes_received = len(self.teams[self.presenting_team_id].get("voters_this_round", set()))
        total_eligible = len(eligible_voters)
        
        print(f"[DEBUG] Votes: {votes_received}/{total_eligible} eligible voters")
        return votes_received >= total_eligible and total_eligible > 0

    def calculate_scores(self):
        if self.presenting_team_id:
            votes = self.teams[self.presenting_team_id]["votes_current_round"]
            if votes:
                avg = sum(votes) / len(votes)
                self.teams[self.presenting_team_id]["score"] += avg
            self.teams[self.presenting_team_id]["votes_current_round"] = []
            self.teams[self.presenting_team_id]["voters_this_round"] = set()

    def reset_session(self):
        """Reset the session to lobby state, clearing everything including users."""
        self.users = {}
        self.teams = {}
        self.phase = Phase.LOBBY
        self.timer_end = None
        self.timer_paused = False
        self.paused_time_remaining = 0
        self.presenting_team_id = None
        self.presented_teams = set()
        self.votes = {}

    def pause_timer(self):
        """Pause the current timer."""
        if self.timer_end and not self.timer_paused:
            current_time = asyncio.get_event_loop().time()
            self.paused_time_remaining = max(0, int(self.timer_end - current_time))
            self.timer_paused = True
            self.timer_end = None
            print(f"[DEBUG] Timer paused. Remaining: {self.paused_time_remaining}s")

    def resume_timer(self):
        """Resume the paused timer."""
        if self.timer_paused:
            current_time = asyncio.get_event_loop().time()
            self.timer_end = current_time + self.paused_time_remaining
            self.timer_paused = False
            self.paused_time_remaining = 0
            print(f"[DEBUG] Timer resumed. New end time: {self.timer_end}")

    def adjust_timer(self, seconds):
        """Add or subtract seconds from the timer."""
        if self.timer_paused:
            self.paused_time_remaining = max(0, self.paused_time_remaining + seconds)
            print(f"[DEBUG] Adjusted paused timer. New remaining: {self.paused_time_remaining}s")
        elif self.timer_end:
            self.timer_end += seconds
            print(f"[DEBUG] Adjusted running timer by {seconds}s")

    def reset_timer(self):
        """Reset timer based on current phase."""
        current_time = asyncio.get_event_loop().time()
        if self.phase == Phase.PREP:
            self.timer_end = current_time + 1200  # 20 minutes
        elif self.phase == Phase.PRESENTING:
            self.timer_end = current_time + 180  # 3 minutes
        else:
            self.timer_end = None
        self.timer_paused = False
        self.paused_time_remaining = 0
        print(f"[DEBUG] Timer reset for phase {self.phase.value}")

    def get_state(self):
        current_time = asyncio.get_event_loop().time()
        remaining = 0
        if self.timer_paused:
            remaining = self.paused_time_remaining
        elif self.timer_end:
            remaining = max(0, int(self.timer_end - current_time))

        # Convert teams for JSON serialization (handle sets)
        teams_serializable = {}
        for team_id, team_data in self.teams.items():
            team_copy = team_data.copy()
            if "voters_this_round" in team_copy:
                team_copy["voters_this_round"] = list(team_copy["voters_this_round"])
            teams_serializable[team_id] = team_copy

        return {
            "phase": self.phase.value,
            "timer": remaining,
            "timer_paused": self.timer_paused,
            "users": self.users,
            "teams": teams_serializable,
            "presenting_team_id": self.presenting_team_id,
            "presented_teams": list(self.presented_teams)
        }