"""8-BIT CRICKET — retro arcade batting with real local accounts."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import random
from dataclasses import dataclass, field

try:
    import pygame
except Exception:
    pygame = None

import auth
from pixel import blit_text, blit_text_center, dither_rect, scanlines, text_width

# NES-ish internal canvas, nearest-neighbor scaled
W, H = 320, 180
SCALE = 4
FPS = 60

NAVY = (16, 20, 56)
NAVY2 = (28, 36, 88)
SKY = (48, 72, 168)
SKY2 = (72, 108, 196)
GRASS = (40, 120, 48)
GRASS2 = (28, 92, 36)
PITCH = (196, 164, 92)
PITCH2 = (176, 140, 72)
CREAM = (248, 232, 176)
WHITE = (248, 248, 248)
RED = (200, 36, 48)
DARK_RED = (128, 16, 32)
GOLD = (248, 184, 48)
BLACK = (8, 8, 16)
WOOD = (168, 108, 40)
SKIN = (232, 176, 120)
BLUE = (48, 80, 176)
CYAN = (88, 220, 220)
PINK = (248, 120, 168)
GRAY = (72, 80, 104)

MAX_OVERS = 5
MAX_WICKETS = 3
MAX_ENERGY = 100
SHOT_ENERGY_COST = {"DEFEND": 0, "DRIVE": 8, "LOFT": 15}
REPEAT_SHOT_FATIGUE = {"DRIVE": 4, "LOFT": 6}


@dataclass
class Match:
    runs: int = 0
    wickets: int = 0
    balls: int = 0
    fours: int = 0
    sixes: int = 0
    last_result: str = "PLAY"
    combo: int = 0
    over_runs: list[str] = field(default_factory=list)
    energy: int = MAX_ENERGY
    shot_uses: dict[str, int] = field(
        default_factory=lambda: {"DRIVE": 0, "LOFT": 0}
    )
    target_runs: int = 0
    target_balls: int = MAX_OVERS * 6

    @property
    def overs_text(self) -> str:
        return f"{self.balls // 6}.{self.balls % 6}"

    @property
    def finished(self) -> bool:
        return (
            self.runs >= self.target_runs
            or self.wickets >= MAX_WICKETS
            or self.balls >= self.target_balls
        )

    @property
    def won(self) -> bool:
        return self.runs >= self.target_runs


class Chip:
    def __init__(
        self, text: str, color: tuple[int, int, int], life: int = 70, y: float = 70.0
    ) -> None:
        self.text = text
        self.color = color
        self.life = life
        self.max_life = life
        self.y = y

    def tick(self) -> None:
        self.life -= 1
        self.y -= 0.35

    @property
    def alive(self) -> bool:
        return self.life > 0


class CricketGame:
    def __init__(self) -> None:
        if pygame is None:
            raise RuntimeError("Pygame is required to run the desktop game client.")
        pygame.init()
        pygame.display.set_caption("8-BIT CRICKET")
        self.window = pygame.display.set_mode((W * SCALE, H * SCALE))
        self.canvas = pygame.Surface((W, H))
        self.clock = pygame.time.Clock()
        self.running = True

        self.state = "TITLE"
        self.user: auth.User | None = None
        self.auth_mode = "LOGIN"
        self.field = "username"
        self.username = ""
        self.password = ""
        self.flash = ""
        self.flash_timer = 0
        self.cursor_blink = 0
        self.menu_index = 0
        self.title_tick = 0

        self.match = Match()
        self.phase = "idle"
        self.phase_t = 0
        self.bowler_x = 40
        self.ball_x = 0.0
        self.ball_y = 0.0
        self.ball_z = 0.0
        self.timing = 0.0
        self.timing_dir = 1
        self.timing_speed = 0.016
        self.sweet_spot = 0.52
        self.shot = "DRIVE"
        self.shot_index = 1
        self.swung = False
        self.ball_kind = "PACE"
        self.ball_frames = 48
        self.ball_line = 0.0
        self.ball_length = 0.5
        self.land_x = 160.0
        self.land_y = 104.0
        self.bounce_t = 0.55
        self.chips: list[Chip] = []
        self.crowd = [random.choice((PINK, CYAN, GOLD, WHITE, RED)) for _ in range(180)]
        self.records: list[dict] = []
        self.board: list[tuple[str, int]] = []
        self.records_page = 0
        self.records_tab = "MATCHES"
        self.pause_index = 0
        self.result_index = 0
        self.muted = False
        self.fullscreen = False
        self.local_accounts: list[str] = []
        self.account_index = 0

        auth.init_db()
        self._beep_init()

    def _beep_init(self) -> None:
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=256)
            self.sfx_ok = self._tone(880, 80)
            self.sfx_bad = self._tone(140, 160)
            self.sfx_six = self._tone(1320, 120)
            self.sfx_bowl = self._tone(220, 60)
        except pygame.error:
            self.sfx_ok = self.sfx_bad = self.sfx_six = self.sfx_bowl = None

    def _tone(self, freq: int, ms: int) -> pygame.mixer.Sound:
        n = int(22050 * ms / 1000)
        buf = bytearray()
        for i in range(n):
            v = 80 if math.sin(2 * math.pi * freq * i / 22050) > 0 else -80
            buf += int(v).to_bytes(2, "little", signed=True)
        return pygame.mixer.Sound(buffer=bytes(buf))

    def play(self, snd: pygame.mixer.Sound | None) -> None:
        if not self.muted and snd is not None:
            snd.play()

    def set_flash(self, msg: str, frames: int = 160) -> None:
        self.flash = msg
        self.flash_timer = frames

    def run(self) -> None:
        while self.running:
            dt = self.clock.tick(FPS)
            events = pygame.event.get()
            for e in events:
                if e.type == pygame.QUIT:
                    self.running = False
                elif e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                    self._escape()
                elif e.type == pygame.KEYDOWN and self.state != "AUTH":
                    if e.key == pygame.K_m:
                        self.muted = not self.muted
                        self.set_flash("SOUND OFF" if self.muted else "SOUND ON", 90)
                    elif e.key in (pygame.K_f, pygame.K_F11):
                        self.fullscreen = not self.fullscreen
                        flags = pygame.FULLSCREEN if self.fullscreen else 0
                        self.window = pygame.display.set_mode((W * SCALE, H * SCALE), flags)
            self._update(events, dt)
            self._draw()
            scaled = pygame.transform.scale(self.canvas, (W * SCALE, H * SCALE))
            self.window.blit(scaled, (0, 0))
            pygame.display.flip()
        pygame.quit()

    def _escape(self) -> None:
        if self.state == "TITLE":
            self.running = False
        elif self.state in ("AUTH",):
            self.state = "TITLE"
        elif self.state in ("MENU", "RECORDS", "ACCOUNTS"):
            self.state = "MENU" if self.state == "RECORDS" else "AUTH"
            if self.state == "AUTH":
                self.user = None
        elif self.state == "PLAY":
            self.state = "PAUSE"
            self.pause_index = 0
            self.play(self.sfx_bowl)
        elif self.state == "PAUSE":
            self.state = "PLAY"
            self.play(self.sfx_bowl)
        elif self.state in ("TARGET", "RESULT"):
            self.state = "MENU"

    def _update(self, events: list[pygame.event.Event], dt: int) -> None:
        self.title_tick += 1
        self.cursor_blink += 1
        if self.flash_timer > 0:
            self.flash_timer -= 1
        if self.state == "TITLE":
            self._title_input(events)
        elif self.state == "AUTH":
            self._auth_input(events)
        elif self.state == "MENU":
            self._menu_input(events)
        elif self.state == "RECORDS":
            self._records_input(events)
        elif self.state == "ACCOUNTS":
            self._accounts_input(events)
        elif self.state == "TARGET":
            self._target_input(events)
        elif self.state == "PLAY":
            self._play_update(events)
        elif self.state == "PAUSE":
            self._pause_input(events)
        elif self.state == "RESULT":
            self._result_input(events)

    def _pause_input(self, events: list[pygame.event.Event]) -> None:
        items = ["RESUME", "QUIT TO MENU"]
        for e in events:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                mx, my = (coord // SCALE for coord in e.pos)
                for i in range(len(items)):
                    y = 74 + i * 22
                    if pygame.Rect(95, y, 130, 18).collidepoint(mx, my):
                        self.pause_index = i
                        self._confirm_pause_choice()
                        break
            elif e.type == pygame.KEYDOWN:
                if e.key in (pygame.K_UP, pygame.K_w):
                    self.pause_index = (self.pause_index - 1) % len(items)
                    self.play(self.sfx_bowl)
                elif e.key in (pygame.K_DOWN, pygame.K_s):
                    self.pause_index = (self.pause_index + 1) % len(items)
                    self.play(self.sfx_bowl)
                elif e.key in (pygame.K_RETURN, pygame.K_SPACE):
                    self._confirm_pause_choice()

    def _confirm_pause_choice(self) -> None:
        if self.pause_index == 0:
            self.state = "PLAY"
            self.play(self.sfx_ok)
        else:
            self.state = "MENU"
            self.play(self.sfx_bad)

    def _title_input(self, events: list[pygame.event.Event]) -> None:
        for e in events:
            if e.type == pygame.KEYDOWN and e.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.play(self.sfx_ok)
                self.state = "AUTH"
                self.auth_mode = "LOGIN"
                self.field = "username"
                self.username = ""
                self.password = ""

    def _auth_input(self, events: list[pygame.event.Event]) -> None:
        for e in events:
            if e.type != pygame.KEYDOWN:
                continue
            if e.key == pygame.K_TAB:
                self.auth_mode = "SIGNUP" if self.auth_mode == "LOGIN" else "LOGIN"
                self.play(self.sfx_bowl)
            elif e.key == pygame.K_UP:
                self.field = "username"
            elif e.key == pygame.K_DOWN:
                self.field = "password"
            elif e.key == pygame.K_RETURN:
                self._submit_auth()
            elif e.key == pygame.K_BACKSPACE:
                if self.field == "username":
                    self.username = self.username[:-1]
                else:
                    self.password = self.password[:-1]
            else:
                ch = e.unicode
                if not ch or not ch.isprintable():
                    continue
                if self.field == "username" and len(self.username) < 16:
                    if ch.isalnum() or ch in "_-":
                        self.username += ch
                elif self.field == "password" and len(self.password) < 24:
                    self.password += ch

    def _submit_auth(self) -> None:
        if self.auth_mode == "LOGIN":
            user, msg = auth.login(self.username, self.password)
        else:
            user, msg = auth.signup(self.username, self.password)
        if user is None:
            self.play(self.sfx_bad)
            self.set_flash(msg)
            return
        self.play(self.sfx_six)
        self.user = user
        self.password = ""
        self.state = "MENU"
        self.menu_index = 0
        self.set_flash(f"HI {user.username.upper()}")

    def _menu_input(self, events: list[pygame.event.Event]) -> None:
        items = ["BAT NOW", "RECORDS", "LOG OUT"]
        for e in events:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                mx, my = (coord // SCALE for coord in e.pos)
                for i, _item in enumerate(items):
                    if pygame.Rect(90, 60 + i * 22, 140, 18).collidepoint(mx, my):
                        self.menu_index = i
                        self._choose_menu_item(items[i])
                        break
                continue
            if e.type != pygame.KEYDOWN:
                continue
            if e.key in (pygame.K_UP, pygame.K_w):
                self.menu_index = (self.menu_index - 1) % len(items)
                self.play(self.sfx_bowl)
            elif e.key in (pygame.K_DOWN, pygame.K_s):
                self.menu_index = (self.menu_index + 1) % len(items)
                self.play(self.sfx_bowl)
            elif e.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._choose_menu_item(items[self.menu_index])

    def _choose_menu_item(self, choice: str) -> None:
        if choice == "BAT NOW":
            self._start_match()
        elif choice == "RECORDS":
            assert self.user is not None
            self.user = auth.get_user_by_id(self.user.id)
            self.records = auth.recent_matches(self.user.id) if self.user else []
            self.board = auth.leaderboard()
            self.records_tab = "MATCHES"
            self.records_page = 0
            self.state = "RECORDS"
            self.play(self.sfx_ok)
        else:
            self._open_account_picker()
            self.play(self.sfx_bad)

    def _open_account_picker(self) -> None:
        self.user = None
        self.local_accounts = auth.local_usernames()
        self.account_index = 0
        self.state = "ACCOUNTS"

    def _accounts_input(self, events: list[pygame.event.Event]) -> None:
        total_choices = len(self.local_accounts) + 1  # final item starts signup
        for e in events:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                mx, my = (coord // SCALE for coord in e.pos)
                visible_start = max(0, min(self.account_index - 3, max(0, len(self.local_accounts) - 7)))
                for row, _name in enumerate(self.local_accounts[visible_start : visible_start + 7]):
                    if pygame.Rect(42, 48 + row * 13, 236, 11).collidepoint(mx, my):
                        self.account_index = visible_start + row
                        self._select_account()
                        break
                if pygame.Rect(42, 142, 236, 14).collidepoint(mx, my):
                    self.account_index = len(self.local_accounts)
                    self._select_account()
            elif e.type == pygame.KEYDOWN and e.key in (pygame.K_UP, pygame.K_w):
                self.account_index = (self.account_index - 1) % total_choices
                self.play(self.sfx_bowl)
            elif e.type == pygame.KEYDOWN and e.key in (pygame.K_DOWN, pygame.K_s):
                self.account_index = (self.account_index + 1) % total_choices
                self.play(self.sfx_bowl)
            elif e.type == pygame.KEYDOWN and e.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._select_account()

    def _select_account(self) -> None:
        if self.account_index == len(self.local_accounts):
            self.auth_mode = "SIGNUP"
            self.username = ""
            self.password = ""
            self.field = "username"
        else:
            self.auth_mode = "LOGIN"
            self.username = self.local_accounts[self.account_index]
            self.password = ""
            self.field = "password"
        self.state = "AUTH"
        self.play(self.sfx_ok)

    def _records_input(self, events: list[pygame.event.Event]) -> None:
        for e in events:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                mx, my = (coord // SCALE for coord in e.pos)
                if pygame.Rect(20, 26, 130, 14).collidepoint(mx, my):
                    self.records_tab = "MATCHES"
                    self.records_page = 0
                    self.play(self.sfx_bowl)
                elif pygame.Rect(170, 26, 130, 14).collidepoint(mx, my):
                    self.records_tab = "LEADERBOARD"
                    self.records_page = 0
                    self.play(self.sfx_bowl)
                elif pygame.Rect(12, 150, 90, 18).collidepoint(mx, my):
                    self._change_records_page(-1)
                elif pygame.Rect(218, 150, 90, 18).collidepoint(mx, my):
                    self._change_records_page(1)
                elif pygame.Rect(110, 150, 100, 18).collidepoint(mx, my):
                    self.state = "MENU"
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_TAB:
                    self.records_tab = "LEADERBOARD" if self.records_tab == "MATCHES" else "MATCHES"
                    self.records_page = 0
                    self.play(self.sfx_bowl)
                elif e.key in (pygame.K_1, pygame.K_KP1):
                    self.records_tab = "MATCHES"
                    self.records_page = 0
                    self.play(self.sfx_bowl)
                elif e.key in (pygame.K_2, pygame.K_KP2):
                    self.records_tab = "LEADERBOARD"
                    self.records_page = 0
                    self.play(self.sfx_bowl)
                elif e.key in (pygame.K_LEFT, pygame.K_a):
                    self._change_records_page(-1)
                elif e.key in (pygame.K_RIGHT, pygame.K_d):
                    self._change_records_page(1)
                elif e.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_ESCAPE):
                    self.state = "MENU"

    def _change_records_page(self, direction: int) -> None:
        per_page = 7
        total_items = len(self.records) if self.records_tab == "MATCHES" else len(self.board)
        page_count = max(1, math.ceil(total_items / per_page))
        next_page = self.records_page + direction
        if 0 <= next_page < page_count:
            self.records_page = next_page
            self.play(self.sfx_bowl)

    def _result_input(self, events: list[pygame.event.Event]) -> None:
        for e in events:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                mx, my = (coord // SCALE for coord in e.pos)
                if pygame.Rect(44, 120, 110, 18).collidepoint(mx, my):
                    self.result_index = 0
                    self._confirm_result_choice()
                elif pygame.Rect(166, 120, 110, 18).collidepoint(mx, my):
                    self.result_index = 1
                    self._confirm_result_choice()
            elif e.type == pygame.KEYDOWN:
                if e.key in (pygame.K_LEFT, pygame.K_a):
                    self.result_index = 0
                    self.play(self.sfx_bowl)
                elif e.key in (pygame.K_RIGHT, pygame.K_d):
                    self.result_index = 1
                    self.play(self.sfx_bowl)
                elif e.key == pygame.K_SPACE:
                    self.result_index = 0
                    self._confirm_result_choice()
                elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self._confirm_result_choice()
                elif e.key == pygame.K_ESCAPE:
                    self.state = "MENU"

    def _confirm_result_choice(self) -> None:
        if self.result_index == 0:
            self._start_match()
        else:
            self.state = "MENU"
            self.play(self.sfx_ok)

    def _target_input(self, events: list[pygame.event.Event]) -> None:
        for e in events:
            if e.type == pygame.KEYDOWN and e.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.state = "PLAY"
                self.play(self.sfx_ok)

    def _start_match(self) -> None:
        # Keep targets around 1.1–1.5 runs per ball: challenging but realistic
        # with well-timed drives and lofted shots, without requiring perfection.
        target_balls = random.choice((18, 20, 22, 24))
        target_runs = random.randint(
            math.ceil(target_balls * 1.1), math.floor(target_balls * 1.5)
        )
        self.match = Match(target_runs=target_runs, target_balls=target_balls)
        self.phase = "idle"
        self.phase_t = 0
        self.chips.clear()
        self.shot_index = 1
        self.shot = "DRIVE"
        self.state = "TARGET"
        self.play(self.sfx_ok)

    def _play_update(self, events: list[pygame.event.Event]) -> None:
        shots = ("DEFEND", "DRIVE", "LOFT")
        for e in events:
            if e.type != pygame.KEYDOWN:
                continue
            if e.key in (pygame.K_LEFT, pygame.K_a):
                self.shot_index = (self.shot_index - 1) % 3
                self.shot = shots[self.shot_index]
            elif e.key in (pygame.K_RIGHT, pygame.K_d):
                self.shot_index = (self.shot_index + 1) % 3
                self.shot = shots[self.shot_index]
            elif e.key == pygame.K_SPACE:
                if self.phase == "idle":
                    self._start_delivery()
                elif self.phase == "ball" and not self.swung:
                    self._swing()

        if self.phase == "runup":
            self.phase_t += 1
            self.bowler_x = 28 + self.phase_t * 1.4
            if self.phase_t > 28:
                self.phase = "ball"
                self.phase_t = 0
                self.swung = False
                self.ball_x, self.ball_y, self.ball_z = 78.0, 96.0, 10.0
                self.play(self.sfx_bowl)
        elif self.phase == "ball":
            self.phase_t += 1
            t = min(1.0, self.phase_t / self.ball_frames)
            self._fly_ball(t)
            self.timing += self.timing_speed * self.timing_dir
            if self.timing > 1:
                self.timing = 1
                self.timing_dir = -1
            if self.timing < 0:
                self.timing = 0
                self.timing_dir = 1
            if t >= 1 and not self.swung:
                self._resolve_shot(missed=True)
        elif self.phase == "result":
            self.phase_t += 1
            if self.phase_t > 55:
                if self.match.finished:
                    self._end_match()
                else:
                    self.phase = "idle"
                    self.phase_t = 0
                    self.bowler_x = 40

        self.chips = [c for c in self.chips if c.alive]
        for c in self.chips:
            c.tick()

    def _start_delivery(self) -> None:
        self._roll_delivery()
        self.phase = "runup"
        self.phase_t = 0
        self.bowler_x = 28
        self.match.last_result = "..."

    def _roll_delivery(self) -> None:
        self.sweet_spot = random.uniform(0.26, 0.74)
        self.timing_speed = random.uniform(0.012, 0.024)
        self.timing_dir = random.choice((-1, 1))
        self.timing = 0.0 if self.timing_dir > 0 else 1.0
        self.ball_line = random.uniform(-1.0, 1.0)
        self.ball_length = random.uniform(0.08, 0.92)
        self.land_x = 208.0 - self.ball_length * 96.0
        self.land_y = 104.0 + self.ball_line * 10.0
        self.bounce_t = 0.34 + (1.0 - self.ball_length) * 0.38
        self.ball_frames = random.randint(42, 60)
        if self.ball_length < 0.28:
            length_name = "YORKER"
            self.ball_frames = random.randint(40, 50)
        elif self.ball_length < 0.52:
            length_name = "FULL"
        elif self.ball_length < 0.76:
            length_name = "GOOD"
        else:
            length_name = "SHORT"
            self.ball_frames = random.randint(46, 58)
        if self.ball_line < -0.33:
            line_name = "LEG"
        elif self.ball_line > 0.33:
            line_name = "OFF"
        else:
            line_name = "MID"
        self.ball_kind = f"{length_name} {line_name}"

    def _fly_ball(self, t: float) -> None:
        bounce = max(0.18, min(0.82, self.bounce_t))
        if t < bounce:
            u = t / bounce
            self.ball_x = 78.0 + u * (self.land_x - 78.0)
            self.ball_y = 96.0 + u * (self.land_y - 96.0)
            self.ball_z = 12.0 * (1.0 - u) * (1.0 - u) + 1.0
        else:
            u = (t - bounce) / max(0.01, 1.0 - bounce)
            self.ball_x = self.land_x + u * (246.0 - self.land_x)
            self.ball_y = self.land_y + math.sin(u * math.pi) * self.ball_line * 3.0
            self.ball_z = abs(math.sin(u * math.pi)) * (3.5 + self.ball_length * 7.0)

    def _swing(self) -> None:
        self.swung = True
        self._resolve_shot(missed=False)

    def _shot_energy_cost(self, shot: str) -> int:
        """Return the cost of using this attacking shot next in the innings."""
        return SHOT_ENERGY_COST[shot] + (
            self.match.shot_uses.get(shot, 0) * REPEAT_SHOT_FATIGUE.get(shot, 0)
        )

    def _resolve_shot(self, missed: bool) -> None:
        window = abs(self.timing - self.sweet_spot)
        shot = self.shot
        result = "0"
        runs = 0
        out = False

        if missed:
            roll = random.random()
            if roll < 0.35:
                out = True
                result = random.choice(("BOWLED", "LBW"))
            else:
                result = "DOT"
        elif shot == "DEFEND":
            # A defensive block is safe and free, but can never add to the score.
            result = "DEFEND"
        elif self.match.energy < self._shot_energy_cost(shot):
            # The delivery still counts; choose DEFEND to safely see it out.
            result = "TIRED"
        else:
            self.match.energy -= self._shot_energy_cost(shot)
            self.match.shot_uses[shot] += 1
            if window < 0.08:
                if shot == "LOFT":
                    if random.random() < 0.78:
                        runs, result = 6, "SIX"
                    else:
                        out, result = True, "CAUGHT"
                elif shot == "DRIVE":
                    runs, result = (4, "FOUR") if random.random() < 0.7 else (3, "3")
                else:
                    runs, result = 1, "1"
            elif window < 0.18:
                if shot == "LOFT":
                    if random.random() < 0.45:
                        runs, result = 4, "FOUR"
                    elif random.random() < 0.4:
                        out, result = True, "CAUGHT"
                    else:
                        runs, result = 2, "2"
                elif shot == "DRIVE":
                    runs, result = random.choice((1, 2, 2, 4)), "HIT"
                    if runs == 4:
                        result = "FOUR"
                    else:
                        result = str(runs)
                else:
                    runs, result = (0, "DOT") if random.random() < 0.4 else (1, "1")
            elif window < 0.32:
                if random.random() < 0.22:
                    out = True
                    result = random.choice(("EDGE", "BOWLED"))
                else:
                    runs, result = random.choice((0, 0, 1)), "SNICK"
                    if runs == 1:
                        result = "1"
                    else:
                        result = "DOT"
            else:
                if random.random() < 0.55:
                    out = True
                    result = random.choice(("BOWLED", "MISS"))
                else:
                    result = "DOT"

        self.match.balls += 1
        if out:
            self.match.wickets += 1
            self.match.combo = 0
            self.match.last_result = result
            self.match.over_runs.append("W")
            self.chips.append(Chip("WICKET!", RED, 90))
            self.play(self.sfx_bad)
        else:
            self.match.runs += runs
            self.match.combo = self.match.combo + 1 if runs else 0
            if runs == 4:
                self.match.fours += 1
            if runs == 6:
                self.match.sixes += 1
            label = (
                result
                if result in ("DEFEND", "TIRED")
                else {0: "DOT", 1: "1", 2: "2", 3: "3", 4: "FOUR!", 6: "SIX!!"}.get(runs, str(runs))
            )
            self.match.last_result = label
            self.match.over_runs.append(str(runs) if runs else ".")
            color = GOLD if runs >= 4 else (CYAN if runs else WHITE)
            self.chips.append(Chip(label, color, 80))
            if runs > 0 and self.match.combo >= 2:
                self.chips.append(
                    Chip(f"COMBO X{self.match.combo}!", PINK, 75, y=86.0)
                )
            self.play(self.sfx_six if runs == 6 else self.sfx_ok)

        if len(self.match.over_runs) > 6:
            self.match.over_runs = self.match.over_runs[-6:]

        self.phase = "result"
        self.phase_t = 0

    def _end_match(self) -> None:
        if self.user is not None:
            auth.save_match(
                self.user.id,
                self.match.runs,
                self.match.wickets,
                self.match.balls,
                self.match.fours,
                self.match.sixes,
            )
            self.user = auth.get_user_by_id(self.user.id)
        self.state = "RESULT"
        self.play(self.sfx_six)

    # --- drawing ---

    def _draw(self) -> None:
        if self.state == "TITLE":
            self._draw_title()
        elif self.state == "AUTH":
            self._draw_auth()
        elif self.state == "MENU":
            self._draw_menu()
        elif self.state == "RECORDS":
            self._draw_records()
        elif self.state == "ACCOUNTS":
            self._draw_accounts()
        elif self.state == "TARGET":
            self._draw_target()
        elif self.state == "PLAY":
            self._draw_play()
        elif self.state == "PAUSE":
            self._draw_pause()
        elif self.state == "RESULT":
            self._draw_result()
        if self.state not in ("PLAY", "PAUSE"):
            if self.muted:
                blit_text(self.canvas, "[MUTED]", W - 48, 4, PINK, 1)
            if self.flash_timer > 0 and self.state not in ("AUTH",):
                blit_text_center(self.canvas, self.flash, W // 2, 4, PINK, 1)
        scanlines(self.canvas, 28)

    def _sky_grass(self) -> None:
        self.canvas.fill(SKY)
        for i in range(40):
            pygame.draw.rect(self.canvas, SKY2, (i * 8, 0, 4, 70))
        pygame.draw.rect(self.canvas, GRASS2, (0, 70, W, H - 70))
        dither_rect(self.canvas, pygame.Rect(0, 78, W, H - 78), GRASS, GRASS2)

    def _crowd(self) -> None:
        pygame.draw.rect(self.canvas, NAVY, (0, 52, W, 20))
        for i, col in enumerate(self.crowd):
            x = (i * 7) % W
            y = 54 + (i * 3) % 14
            self.canvas.fill(col, (x, y, 2, 3))

    def _draw_title(self) -> None:
        self._sky_grass()
        self._crowd()
        self._draw_pitch(offset=0)
        self._draw_batsman(250, 108, swing=False)
        self._draw_bowler(70, 92, run=self.title_tick % 20 < 10)
        pygame.draw.rect(self.canvas, BLACK, (18, 8, 284, 42))
        pygame.draw.rect(self.canvas, GOLD, (18, 8, 284, 42), 2)
        blit_text_center(self.canvas, "8-BIT CRICKET", W // 2, 14, GOLD, 2)
        blit_text_center(self.canvas, "RETRO TEST MATCH", W // 2, 34, CREAM, 1)
        if (self.title_tick // 30) % 2 == 0:
            blit_text_center(self.canvas, "PRESS ENTER", W // 2, 154, WHITE, 1)
        blit_text_center(self.canvas, "ESC QUIT", W // 2, 168, GRAY, 1)

    def _panel(self, x: int, y: int, w: int, h: int) -> None:
        pygame.draw.rect(self.canvas, NAVY, (x, y, w, h))
        pygame.draw.rect(self.canvas, GOLD, (x, y, w, h), 2)
        pygame.draw.rect(self.canvas, WHITE, (x + 2, y + 2, w - 4, h - 4), 1)

    def _draw_auth(self) -> None:
        self.canvas.fill(NAVY)
        for y in range(0, H, 4):
            pygame.draw.rect(self.canvas, NAVY2, (0, y, W, 2))
        blit_text_center(self.canvas, "PLAYER LOGIN", W // 2, 10, GOLD, 2)

        tab_y = 36
        for i, name in enumerate(("LOGIN", "SIGNUP")):
            x = 70 + i * 90
            on = self.auth_mode == name
            col = GOLD if on else GRAY
            blit_text(self.canvas, name, x, tab_y, col, 1)
            if on:
                pygame.draw.rect(self.canvas, GOLD, (x - 4, tab_y + 10, text_width(name), 2))

        blit_text(self.canvas, "TAB TO SWITCH", 104, 50, GRAY, 1)

        def field_box(label: str, value: str, active: bool, secret: bool, fy: int) -> None:
            blit_text(self.canvas, label, 54, fy, CREAM, 1)
            pygame.draw.rect(self.canvas, BLACK, (54, fy + 10, 212, 16))
            pygame.draw.rect(self.canvas, GOLD if active else GRAY, (54, fy + 10, 212, 16), 1)
            shown = ("*" * len(value)) if secret else value
            if active and (self.cursor_blink // 20) % 2 == 0:
                shown += "_"
            blit_text(self.canvas, shown or " ", 58, fy + 13, WHITE, 1)

        field_box("USERNAME", self.username, self.field == "username", False, 66)
        field_box("PASSWORD", self.password, self.field == "password", True, 100)

        blit_text_center(self.canvas, "ENTER TO CONFIRM", W // 2, 140, WHITE, 1)
        if self.flash_timer > 0:
            blit_text_center(self.canvas, self.flash, W // 2, 156, PINK, 1)
        else:
            hint = "NEW PLAYER? TAB SIGNUP" if self.auth_mode == "LOGIN" else "MIN 6 CHAR PASSWORD"
            blit_text_center(self.canvas, hint, W // 2, 156, GRAY, 1)

    def _draw_menu(self) -> None:
        self._sky_grass()
        self._crowd()
        self._draw_pitch(0)
        name = self.user.username.upper() if self.user else "GUEST"
        high = self.user.high_score if self.user else 0
        played = self.user.matches_played if self.user else 0

        self._panel(16, 10, 288, 36)
        blit_text(self.canvas, f"BATSMAN:{name}", 24, 16, WHITE, 1)
        blit_text(self.canvas, f"BEST {high}  MATCHES {played}", 24, 28, CREAM, 1)

        items = ["BAT NOW", "RECORDS", "LOG OUT"]
        for i, item in enumerate(items):
            y = 60 + i * 22
            on = i == self.menu_index
            pygame.draw.rect(self.canvas, NAVY if on else BLACK, (90, y, 140, 18))
            pygame.draw.rect(self.canvas, GOLD if on else GRAY, (90, y, 140, 18), 1)
            label = f"> {item}" if on else f"  {item}"
            blit_text_center(self.canvas, label, W // 2, y + 5, GOLD if on else WHITE, 1)

        blit_text_center(self.canvas, "ARROWS + ENTER", W // 2, 160, WHITE, 1)

    def _draw_records(self) -> None:
        self.canvas.fill(NAVY)
        for y in range(0, H, 4):
            pygame.draw.rect(self.canvas, NAVY2, (0, y, W, 2))
        self._panel(8, 6, 304, 140)
        blit_text_center(self.canvas, "RECORDS & STATS", W // 2, 10, GOLD, 2)

        tab_y = 26
        matches_on = self.records_tab == "MATCHES"
        pygame.draw.rect(self.canvas, NAVY if matches_on else BLACK, (20, tab_y, 130, 14))
        pygame.draw.rect(self.canvas, GOLD if matches_on else GRAY, (20, tab_y, 130, 14), 1)
        blit_text_center(self.canvas, "[1] MY MATCHES", 85, tab_y + 3, GOLD if matches_on else WHITE, 1)

        board_on = self.records_tab == "LEADERBOARD"
        pygame.draw.rect(self.canvas, NAVY if board_on else BLACK, (170, tab_y, 130, 14))
        pygame.draw.rect(self.canvas, GOLD if board_on else GRAY, (170, tab_y, 130, 14), 1)
        blit_text_center(self.canvas, "[2] TOP SCORES", 235, tab_y + 3, GOLD if board_on else WHITE, 1)

        per_page = 7
        if matches_on:
            name = self.user.username.upper() if self.user else "PLAYER"
            best = self.user.high_score if self.user else 0
            blit_text(self.canvas, f"{name[:10]}  BEST:{best}", 16, 44, CREAM, 1)
            blit_text(self.canvas, "#  SCORE  OVERS  4S 6S", 16, 56, CYAN, 1)
            pygame.draw.line(self.canvas, GRAY, (16, 66), (304, 66))
            if not self.records:
                blit_text_center(self.canvas, "NO SCORES YET - GO BAT!", W // 2, 95, GRAY, 1)
            start = self.records_page * per_page
            for i, rec in enumerate(self.records[start : start + per_page]):
                match_no = len(self.records) - (start + i)
                overs = f"{rec['balls'] // 6}.{rec['balls'] % 6}"
                line = f"{match_no:<2} {rec['runs']}/{rec['wickets']:<2}  {overs:<4}  {rec['fours']:<2} {rec['sixes']:<2}"
                blit_text(self.canvas, line, 16, 72 + i * 9, WHITE, 1)
            page_count = max(1, math.ceil(len(self.records) / per_page))
        else:
            blit_text(self.canvas, "ALL-TIME LEADERBOARD", 16, 44, CREAM, 1)
            blit_text(self.canvas, "RANK  BATTER            BEST", 16, 56, CYAN, 1)
            pygame.draw.line(self.canvas, GRAY, (16, 66), (304, 66))
            if not self.board:
                blit_text_center(self.canvas, "NO SCORES RECORDED YET", W // 2, 95, GRAY, 1)
            start = self.records_page * per_page
            for i, (uname, best_runs) in enumerate(self.board[start : start + per_page]):
                rank = start + i + 1
                line = f"{rank:<4}  {uname[:16]:<16}  {best_runs:>4}"
                blit_text(self.canvas, line, 16, 72 + i * 9, WHITE, 1)
            page_count = max(1, math.ceil(len(self.board) / per_page))

        blit_text_center(
            self.canvas,
            f"PAGE {self.records_page + 1}/{page_count}  (TAB TOGGLES)",
            W // 2,
            134,
            GOLD,
            1,
        )
        self._record_button("PREV", 12, self.records_page > 0)
        self._record_button("BACK", 110, True)
        self._record_button("NEXT", 218, self.records_page + 1 < page_count)

    def _record_button(self, label: str, x: int, enabled: bool) -> None:
        color = GOLD if enabled else GRAY
        pygame.draw.rect(self.canvas, BLACK, (x, 150, 90, 18))
        pygame.draw.rect(self.canvas, color, (x, 150, 90, 18), 1)
        blit_text_center(self.canvas, label, x + 45, 155, color, 1)

    def _draw_accounts(self) -> None:
        self.canvas.fill(NAVY)
        for y in range(0, H, 4):
            pygame.draw.rect(self.canvas, NAVY2, (0, y, W, 2))
        self._panel(24, 8, 272, 154)
        blit_text_center(self.canvas, "LOCAL ACCOUNTS", W // 2, 16, GOLD, 2)
        blit_text_center(self.canvas, "CHOOSE A USERNAME", W // 2, 34, CREAM, 1)

        if not self.local_accounts:
            blit_text_center(self.canvas, "NO ACCOUNTS SAVED", W // 2, 76, GRAY, 1)
        visible_start = max(0, min(self.account_index - 3, max(0, len(self.local_accounts) - 7)))
        for row, name in enumerate(self.local_accounts[visible_start : visible_start + 7]):
            index = visible_start + row
            y = 48 + row * 13
            selected = index == self.account_index
            pygame.draw.rect(self.canvas, BLACK if selected else NAVY2, (42, y, 236, 11))
            pygame.draw.rect(self.canvas, GOLD if selected else GRAY, (42, y, 236, 11), 1)
            blit_text(self.canvas, name[:16], 52, y + 2, GOLD if selected else WHITE, 1)

        new_selected = self.account_index == len(self.local_accounts)
        pygame.draw.rect(self.canvas, BLACK if new_selected else NAVY2, (42, 142, 236, 14))
        pygame.draw.rect(self.canvas, GOLD if new_selected else GRAY, (42, 142, 236, 14), 1)
        blit_text_center(self.canvas, "NEW PLAYER", W // 2, 146, GOLD if new_selected else WHITE, 1)
        blit_text_center(self.canvas, "ENTER  PASSWORD REQUIRED", W // 2, 166, GRAY, 1)

    def _draw_pitch(self, offset: int) -> None:
        pygame.draw.rect(self.canvas, PITCH2, (70, 86, 180, 36))
        pygame.draw.rect(self.canvas, PITCH, (76, 90, 168, 28))
        pygame.draw.line(self.canvas, WHITE, (88, 90), (88, 118))
        pygame.draw.line(self.canvas, WHITE, (232, 90), (232, 118))
        # stumps
        for sx in (84, 88, 92):
            pygame.draw.rect(self.canvas, WOOD, (sx, 78, 2, 16))
        pygame.draw.rect(self.canvas, GOLD, (84, 76, 10, 2))
        for sx in (228, 232, 236):
            pygame.draw.rect(self.canvas, WOOD, (sx, 78, 2, 16))
        pygame.draw.rect(self.canvas, GOLD, (228, 76, 10, 2))

    def _draw_bowler(self, x: int, y: int, run: bool) -> None:
        pygame.draw.rect(self.canvas, RED, (x + 2, y + 6, 8, 10))  # jersey
        pygame.draw.rect(self.canvas, SKIN, (x + 3, y, 6, 6))
        pygame.draw.rect(self.canvas, BLACK, (x + 4, y + 1, 2, 2))
        pygame.draw.rect(self.canvas, WHITE, (x + 2, y + 16, 4, 8))
        pygame.draw.rect(self.canvas, WHITE, (x + 7, y + 16, 4, 8))
        arm = -6 if run else 8
        pygame.draw.rect(self.canvas, SKIN, (x + arm, y + 8, 6, 2))

    def _draw_batsman(self, x: int, y: int, swing: bool) -> None:
        pygame.draw.rect(self.canvas, BLUE, (x, y + 6, 10, 12))
        pygame.draw.rect(self.canvas, SKIN, (x + 2, y, 6, 6))
        pygame.draw.rect(self.canvas, WHITE, (x + 6, y - 2, 6, 3))  # helmet
        pygame.draw.rect(self.canvas, WHITE, (x, y + 18, 4, 8))
        pygame.draw.rect(self.canvas, WHITE, (x + 6, y + 18, 4, 8))
        if swing:
            pygame.draw.line(self.canvas, WOOD, (x + 10, y + 8), (x + 22, y - 4), 3)
        else:
            pygame.draw.line(self.canvas, WOOD, (x + 10, y + 10), (x + 16, y + 24), 3)

    def _draw_target(self) -> None:
        self._sky_grass()
        self._crowd()
        self._draw_pitch(0)
        self._draw_bowler(40, 92, False)
        self._draw_batsman(246, 100, False)
        self._panel(38, 30, 244, 112)
        m = self.match
        overs = f"{m.target_balls // 6}.{m.target_balls % 6}"
        blit_text_center(self.canvas, "CHASE TARGET", W // 2, 40, GOLD, 2)
        blit_text_center(self.canvas, f"SCORE {m.target_runs} RUNS", W // 2, 68, WHITE, 2)
        blit_text_center(self.canvas, f"IN {m.target_balls} BALLS ({overs} OVERS)", W // 2, 88, CREAM, 1)
        blit_text_center(self.canvas, "ENTER TO BAT", W // 2, 118, CYAN, 1)

    def _draw_play(self) -> None:
        self._sky_grass()
        self._crowd()
        self._draw_pitch(0)

        run = self.phase == "runup"
        self._draw_bowler(int(self.bowler_x), 92, run)
        swinging = self.phase == "result" and self.swung and self.phase_t < 20
        self._draw_batsman(246, 100, swinging)

        if self.phase in ("runup", "ball", "result"):
            mx, my = int(self.land_x), int(self.land_y)
            pygame.draw.rect(self.canvas, DARK_RED, (mx - 3, my - 1, 7, 3))
            pygame.draw.rect(self.canvas, RED, (mx - 1, my - 2, 3, 5))
        if self.phase == "ball":
            bx, by = int(self.ball_x), int(self.ball_y - self.ball_z)
            pygame.draw.rect(self.canvas, BLACK, (bx + 1, int(self.ball_y) + 6, 4, 2))
            pygame.draw.rect(self.canvas, RED, (bx, by, 4, 4))
            pygame.draw.rect(self.canvas, WHITE, (bx + 1, by + 1, 1, 1))

        # HUD
        pygame.draw.rect(self.canvas, BLACK, (0, 0, W, 22))
        m = self.match
        name = self.user.username.upper()[:8] if self.user else "PLAYER"
        blit_text(self.canvas, f"{name} {m.runs}/{m.wickets}", 4, 4, WHITE, 1)
        blit_text(self.canvas, f"TGT {m.target_runs} IN {m.target_balls - m.balls}", 126, 4, CREAM, 1)
        blit_text(self.canvas, f"4s {m.fours}  6s {m.sixes}", 230, 4, GOLD, 1)

        pygame.draw.rect(self.canvas, BLACK, (0, 158, W, 22))
        this_over = " ".join(m.over_runs[-6:] or ["-"])
        blit_text(self.canvas, f"O:{this_over}", 112, 162, WHITE, 1)
        blit_text(self.canvas, f"SHOT:{self.shot}", 196, 162, CYAN, 1)
        if self.muted:
            blit_text(self.canvas, "[MUTED]", 262, 162, PINK, 1)

        # Repeating an attacking shot builds fatigue, so changing shots matters.
        bar_x, bar_y, bar_w, bar_h = 4, 169, 70, 7
        energy_ratio = m.energy / MAX_ENERGY
        energy_color = GRASS if energy_ratio > 0.5 else (GOLD if energy_ratio > 0.25 else RED)
        blit_text(self.canvas, "ENG", bar_x, 160, CREAM, 1)
        pygame.draw.rect(self.canvas, WHITE, (bar_x, bar_y, bar_w, bar_h), 1)
        pygame.draw.rect(self.canvas, BLACK, (bar_x + 1, bar_y + 1, bar_w - 2, bar_h - 2))
        fill_width = int((bar_w - 2) * energy_ratio)
        if fill_width:
            pygame.draw.rect(self.canvas, energy_color, (bar_x + 1, bar_y + 1, fill_width, bar_h - 2))
        blit_text(self.canvas, str(m.energy), bar_x + bar_w + 4, 169, energy_color, 1)
        drive_cost = self._shot_energy_cost("DRIVE")
        loft_cost = self._shot_energy_cost("LOFT")
        blit_text(self.canvas, f"D{drive_cost} L{loft_cost}", 112, 169, CREAM, 1)

        if self.phase == "idle":
            blit_text_center(self.canvas, "SPACE TO FACE  LEFT/RIGHT SHOT", W // 2, 28, WHITE, 1)
        elif self.phase == "ball":
            # timing meter
            pygame.draw.rect(self.canvas, BLACK, (90, 26, 140, 10))
            pygame.draw.rect(self.canvas, WHITE, (90, 26, 140, 10), 1)
            gold_x = max(90, min(214, 90 + int(self.sweet_spot * 136) - 8))
            pygame.draw.rect(self.canvas, GOLD, (gold_x, 26, 16, 10))
            pygame.draw.rect(self.canvas, RED, (90 + int(self.timing * 136), 26, 4, 10))
            blit_text_center(self.canvas, "TIME YOUR SWING!", W // 2, 40, CREAM, 1)
        elif self.phase == "runup":
            blit_text_center(self.canvas, self.ball_kind, W // 2, 28, PINK, 1)

        for chip in self.chips:
            blit_text_center(self.canvas, chip.text, W // 2, int(chip.y), chip.color, 2)

    def _draw_pause(self) -> None:
        self._draw_play()
        self._panel(75, 40, 170, 95)
        blit_text_center(self.canvas, "PAUSED", W // 2, 48, GOLD, 2)
        items = ["RESUME", "QUIT TO MENU"]
        for i, item in enumerate(items):
            y = 74 + i * 22
            on = i == self.pause_index
            pygame.draw.rect(self.canvas, NAVY if on else BLACK, (95, y, 130, 18))
            pygame.draw.rect(self.canvas, GOLD if on else GRAY, (95, y, 130, 18), 1)
            label = f"> {item}" if on else f"  {item}"
            blit_text_center(self.canvas, label, W // 2, y + 5, GOLD if on else WHITE, 1)
        blit_text_center(self.canvas, "ARROWS + ENTER OR ESC", W // 2, 122, GRAY, 1)

    def _draw_result(self) -> None:
        self._sky_grass()
        self._panel(32, 16, 256, 144)
        m = self.match
        result = "TARGET CHASED!" if m.won else "INNINGS OVER"
        result_color = GOLD if m.won else RED
        blit_text_center(self.canvas, result, W // 2, 24, result_color, 2)
        blit_text_center(self.canvas, f"{m.runs} RUNS", W // 2, 46, WHITE, 2)
        blit_text_center(
            self.canvas,
            f"{m.wickets} DOWN   {m.overs_text} OVERS",
            W // 2,
            68,
            CREAM,
            1,
        )
        target_status = "TARGET MET" if m.won else f"TARGET {m.target_runs}"
        blit_text_center(self.canvas, target_status, W // 2, 82, GOLD if m.won else PINK, 1)
        blit_text_center(self.canvas, f"{m.fours} FOURS   {m.sixes} SIXES", W // 2, 94, CYAN, 1)
        if self.user:
            blit_text_center(self.canvas, f"SAVED TO {self.user.username.upper()}", W // 2, 106, PINK, 1)

        again_on = self.result_index == 0
        pygame.draw.rect(self.canvas, NAVY if again_on else BLACK, (44, 120, 110, 18))
        pygame.draw.rect(self.canvas, GOLD if again_on else GRAY, (44, 120, 110, 18), 1)
        blit_text_center(self.canvas, "PLAY AGAIN", 99, 125, GOLD if again_on else WHITE, 1)

        menu_on = self.result_index == 1
        pygame.draw.rect(self.canvas, NAVY if menu_on else BLACK, (166, 120, 110, 18))
        pygame.draw.rect(self.canvas, GOLD if menu_on else GRAY, (166, 120, 110, 18), 1)
        blit_text_center(self.canvas, "MAIN MENU", 221, 125, GOLD if menu_on else WHITE, 1)

        blit_text_center(self.canvas, "SPACE: PLAY AGAIN   ENTER: SELECT", W // 2, 144, GRAY, 1)


def main() -> None:
    CricketGame().run()


# --- Vercel / WSGI Web Application & Serverless Handler ---

WEB_INDEX_FILE = Path(__file__).resolve().parent / "web" / "index.html"


def _serve_index() -> bytes:
    if WEB_INDEX_FILE.exists():
        return WEB_INDEX_FILE.read_bytes()
    return b"<!DOCTYPE html><html><body><h1>8-Bit Cricket</h1><p>Web edition loading...</p></body></html>"


def app(environ: dict, start_response) -> list[bytes]:
    """WSGI entrypoint for Vercel and WSGI servers."""
    path = environ.get("PATH_INFO", "/") or "/"

    if path in ("/api/status", "/api/health"):
        body = json.dumps(
            {
                "status": "ok",
                "game": "8-Bit Cricket",
                "version": "1.0.0",
                "platform": "Vercel Serverless / Web",
            }
        ).encode("utf-8")
        status = "200 OK"
        headers = [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-cache"),
        ]
        start_response(status, headers)
        return [body]

    if path == "/api/leaderboard":
        try:
            scores = auth.leaderboard(10)
            data = [{"username": u, "best": s} for u, s in scores]
        except Exception:
            data = []
        body = json.dumps({"leaderboard": data}).encode("utf-8")
        status = "200 OK"
        headers = [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ]
        start_response(status, headers)
        return [body]

    # Serve the retro arcade web client for all other routes
    content = _serve_index()
    status = "200 OK"
    headers = [
        ("Content-Type", "text/html; charset=utf-8"),
        ("Content-Length", str(len(content))),
        ("Cache-Control", "public, max-age=3600"),
    ]
    start_response(status, headers)
    return [content]


# Export top-level application and handler aliases required by Vercel
application = app
handler = app


if __name__ == "__main__":
    try:
        main()
    except Exception:
        if pygame is not None:
            pygame.quit()
        raise
