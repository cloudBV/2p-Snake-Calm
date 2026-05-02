#!/usr/bin/env python3
# =============================================================================
# Snake — Fill the Board
#
# Modes    : 1 Player  — fill the board alone for highest score
#            2 Players — compete for food, highest score when board fills wins
# Controls : P1 — WASD      P2 — Arrow Keys
#            Space — pause (1P only)   Q / ESC — back to menu anytime
# Rules    : Edges wrap around — snakes pass through their own AND each other
#            Eating food permanently fills that cell
#            Fill all cells to WIN
# Food     : Red    circle   — 1 pt,  always present, fills 2 cells when eaten
#            Green  square   — 5 pts, cycles every 5 s, fills 1 cell
#            Blue   triangle — 5 pts, spawns at every 10 pts, speed boost
# Score    : Saved separately per board size
# =============================================================================

import asyncio
import json
import math
import os
import random

import pygame

# ── BOARD PRESETS ─────────────────────────────────────────────────────────────
# Each preset: (display label, grid columns, grid rows, save key for highscore)
# Add more rows here to add new board sizes — just follow the same format
PRESETS = [
    ("Small",  15, 12, "small"),
    ("Medium", 30, 25, "medium"),
    ("Large",  45, 35, "large"),
]
CELL   = 20    # pixel size of each grid cell — change to scale the whole game
MENU_W = CELL * 30   # menu window is always Medium size regardless of selected preset
MENU_H = CELL * 25   # WHY: so the start screen always looks correct

# These globals get updated when the game starts based on the selected preset
GRID_W   = 30
GRID_H   = 25
SCREEN_W = CELL * GRID_W
SCREEN_H = CELL * GRID_H

# ── GAME CONSTANTS ────────────────────────────────────────────────────────────
FPS_START   = 8       # starting speed — increase to make game harder from the start
FPS_MAX     = 20      # speed cap before blue boost — raise for a faster max
FPS_STEP    = 1       # speed increase per 5 points — raise for faster acceleration
BLUE_BOOST  = 1       # extra FPS per blue stack — raise to make blue more powerful
BLUE_DECAY  = 10_000  # ms before speed stack resets — lower = more punishing
GREEN_CYCLE = 5_000   # ms before green food cycles to new position — lower = harder
BLUE_SCORE  = 10      # score gap between blue food spawns — lower = more blue food

# ── COLORS ────────────────────────────────────────────────────────────────────
# Change any color here to restyle without touching the rest of the code
BLACK      = (  0,   0,   0)
WHITE      = (255, 255, 255)
GREEN      = ( 80, 220, 100)   # green food color
DARK_GREEN = (  0, 140,   0)   # P1 snake tail color
SNAKE_GRN  = (  0, 200,   0)   # P1 snake head color
RED        = (220,  50,  50)   # red food color
BLUE       = ( 80, 160, 255)   # blue food color
GOLD       = (255, 200,   0)   # highscore / best text color
GRAY       = ( 40,  40,  40)   # dim text / borders
DARK_GRAY  = ( 25,  25,  25)   # grid background
DIM        = ( 15,  15,  15)   # start screen background
WIN_GREEN  = ( 50, 255, 120)   # win screen title / progress bar color
PRESET_SEL = ( 80, 160, 255)   # selected button highlight color

# P2 snake colors — change to restyle P2
SNAKE_P2   = (255, 100,   0)   # P2 head color
DARK_P2    = (180,  60,   0)   # P2 tail color — keep darker than head

# Filled cell colors — keep these dark so food and snake are visible on top
FILLED_RED   = ( 80,  20,  20)   # cell filled by red food
FILLED_GREEN = ( 20,  80,  30)   # cell filled by green food
FILLED_BLUE  = ( 20,  40,  90)   # cell filled by blue food

SCORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snake_highscore.json")


# ── HIGH SCORE ────────────────────────────────────────────────────────────────
# Scores are stored as a dict keyed by preset save_key e.g. {"small": 90, "medium": 375}
# Each board size tracks its own best score independently

def load_highscores():
    """Load all highscores from file. Returns empty dict if file doesn't exist yet."""
    try:
        with open(SCORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_highscore(key, score):
    """Save a single highscore for the given preset key without touching the others."""
    scores = load_highscores()
    scores[key] = score
    try:
        with open(SCORE_FILE, "w", encoding="utf-8") as f:
            json.dump(scores, f)
    except Exception:
        pass   # silently skip if disk write fails — not critical


# ── SNAKE GRADIENT ────────────────────────────────────────────────────────────

def body_color(index, length, head_col, tail_col):
    """
    Interpolate between head_col and tail_col based on segment position.
    index 0 = just behind head (bright), index length-1 = tail tip (dark).
    """
    t = index / max(1, length - 1)   # 0.0 at head end, 1.0 at tail tip
    return (
        int(head_col[0] * (1 - t) + tail_col[0] * t),
        int(head_col[1] * (1 - t) + tail_col[1] * t),
        int(head_col[2] * (1 - t) + tail_col[2] * t),
    )


# ── GAME STATE ────────────────────────────────────────────────────────────────

def make_state(two_player=False):
    """
    Return a fresh game state dict. Called at game start and on restart.
    All mutable game data lives here — nothing important is stored globally.
    """
    # Starting positions — P1 quarter from left, P2 quarter from right
    # Change the divisors to adjust where each snake spawns
    p1x = GRID_W // 4
    p1y = GRID_H // 2
    p1  = [(p1x, p1y), (p1x - 1, p1y), (p1x - 2, p1y)]   # P1 faces right

    p2x = (GRID_W * 3) // 4
    p2y = GRID_H // 2
    p2  = [(p2x, p2y), (p2x + 1, p2y), (p2x + 2, p2y)]   # P2 faces left

    combined = p1 + (p2 if two_player else [])
    filled: dict = {}   # (x,y) → "red"/"green"/"blue" — cells permanently filled
    red   = _spawn(combined, filled)
    green = _spawn(combined, filled, exclude=[red])

    state = {
        "p1":          p1,
        "p1_dir":      (1, 0),    # current movement direction (dx, dy)
        "p1_next":     (1, 0),    # queued direction — applied next frame
        "p1_score":    0,
        "p1_fps":      FPS_START,
        "p1_stack":    0,          # number of blue boosts currently stacked
        "p1_decay":    0,          # ms remaining before blue stack resets
        "filled":      filled,
        "red_pos":     red,
        "green_pos":   green,
        "green_timer": GREEN_CYCLE,
        "blue_pos":    None,
        "next_blue":   BLUE_SCORE, # score threshold that spawns the next blue food
        "two_player":  two_player,
        "floats":      [],          # active FloatText pop-ups
    }

    if two_player:
        state.update({
            "p2":       p2,
            "p2_dir":   (-1, 0),
            "p2_next":  (-1, 0),
            "p2_score": 0,
            "p2_fps":   FPS_START,
            "p2_stack": 0,
            "p2_decay": 0,
        })

    return state

def _spawn(snakes, filled, exclude=None):
    """
    Return a random free grid cell.
    Free = not occupied by any snake, not already filled by food, not in exclude list.
    Returns None if every cell is taken (board is full — triggers win).
    """
    occupied = set(snakes) | set(filled.keys())
    if exclude:
        for pos in exclude:
            if pos:
                occupied.add(pos)
    free = [(x, y) for x in range(GRID_W) for y in range(GRID_H)
            if (x, y) not in occupied]
    return random.choice(free) if free else None

def all_snakes(gs):
    """Return a combined list of every body cell from all active snakes."""
    s = gs["p1"][:]
    if gs["two_player"]:
        s += gs["p2"]
    return s


# ── GRID SURFACE ──────────────────────────────────────────────────────────────

def make_grid_surface():
    """
    Pre-render the background grid lines into a surface and reuse it every frame.
    WHY: Drawing hundreds of rectangles per frame in a loop is wasteful.
    Blitting one surface is much faster.
    """
    surf = pygame.Surface((SCREEN_W, SCREEN_H))
    surf.fill(DARK_GRAY)
    for x in range(GRID_W):
        for y in range(GRID_H):
            pygame.draw.rect(surf, (35, 35, 35),
                             pygame.Rect(x * CELL, y * CELL, CELL, CELL), 1)
    return surf


# ── DRAW HELPERS ──────────────────────────────────────────────────────────────

def draw_cell(surface, color, gx, gy, edge=BLACK):
    """Draw a single filled grid cell with an edge border."""
    r = pygame.Rect(gx * CELL, gy * CELL, CELL, CELL)
    pygame.draw.rect(surface, color, r)
    pygame.draw.rect(surface, edge, r, 1)

def draw_snake_head(surface, gx, gy, direction, col):
    """Draw snake head with two eyes pointing in the movement direction."""
    draw_cell(surface, col, gx, gy)
    cx, cy = gx * CELL + CELL // 2, gy * CELL + CELL // 2
    dx, dy = direction
    # Eye positions shift based on which way the snake is moving
    if   dx ==  1: eyes = [(cx + 4, cy - 4), (cx + 4, cy + 4)]   # right
    elif dx == -1: eyes = [(cx - 4, cy - 4), (cx - 4, cy + 4)]   # left
    elif dy == -1: eyes = [(cx - 4, cy - 4), (cx + 4, cy - 4)]   # up
    else:          eyes = [(cx - 4, cy + 4), (cx + 4, cy + 4)]   # down
    for eye in eyes:
        pygame.draw.circle(surface, WHITE, eye, 3)
        pygame.draw.circle(surface, BLACK, eye, 2)   # pupil

def draw_red_food(surface, gx, gy):
    """Red food — pulsing circle. Pulse speed controlled by sin frequency (0.006)."""
    ticks = pygame.time.get_ticks()
    pulse = 0.75 + 0.25 * math.sin(ticks * 0.006)   # 0.006 = pulse speed
    size  = max(4, int(CELL * 0.7 * pulse))
    pygame.draw.circle(surface, RED,
                       (gx * CELL + CELL // 2, gy * CELL + CELL // 2), size // 2)

def draw_green_food(surface, gx, gy, timer):
    """
    Green food — pulsing square with a timer bar at the bottom.
    Square shrinks as timer runs out (ratio goes from 1.0 → 0.3).
    Timer bar drains left to right showing time remaining.
    """
    ratio  = max(0.3, timer / GREEN_CYCLE)   # 0.3 = minimum size — never invisible
    ticks  = pygame.time.get_ticks()
    pulse  = 0.85 + 0.15 * math.sin(ticks * 0.008)
    size   = max(6, int(CELL * 0.75 * ratio * pulse))
    cx     = gx * CELL + CELL // 2
    cy     = gy * CELL + CELL // 2
    pygame.draw.rect(surface, GREEN,
                     pygame.Rect(cx - size // 2, cy - size // 2, size, size))
    # Timer bar — 3px tall, sits at bottom of the cell
    bar_x  = gx * CELL + 2
    bar_y  = gy * CELL + CELL - 4
    bar_w  = CELL - 4
    filled = int(bar_w * (timer / GREEN_CYCLE))
    pygame.draw.rect(surface, (30, 80, 40), (bar_x, bar_y, bar_w, 3))    # empty bg
    pygame.draw.rect(surface, WIN_GREEN,    (bar_x, bar_y, filled, 3))   # filled portion

def draw_blue_food(surface, gx, gy):
    """Blue food — upward-pointing pulsing triangle."""
    ticks = pygame.time.get_ticks()
    pulse = 0.8 + 0.2 * math.sin(ticks * 0.007)
    size  = int(CELL * 0.7 * pulse)
    cx    = gx * CELL + CELL // 2
    cy    = gy * CELL + CELL // 2
    pygame.draw.polygon(surface, BLUE, [
        (cx,             cy - size // 2),   # tip (top)
        (cx - size // 2, cy + size // 2),   # bottom left
        (cx + size // 2, cy + size // 2),   # bottom right
    ])

def draw_centered(surface, font, text, color, y):
    """Render text horizontally centered on the screen at height y."""
    surf = font.render(text, True, color)
    surface.blit(surf, surf.get_rect(center=(SCREEN_W // 2, y)))


# ── SCORE POP-UPS ─────────────────────────────────────────────────────────────

class FloatText:
    """
    A score pop-up that appears where food was eaten, drifts upward, and fades out.
    duration  — how long it lives in ms (raise for longer popups)
    drift speed — 40 px/sec (raise the 40 in update() to float faster)
    """
    def __init__(self, text, x, y, color=WHITE, duration=700):
        self.text     = text
        self.x        = float(x)
        self.y        = float(y)
        self.color    = color
        self.duration = duration
        self.timer    = duration

    def update(self, dt):
        self.timer -= dt
        self.y     -= 40 * dt / 1000   # drift speed in px/sec — raise to float faster

    @property
    def alive(self): return self.timer > 0

    @property
    def alpha(self): return max(0, int(255 * self.timer / self.duration))


# ── SCREENS ───────────────────────────────────────────────────────────────────

def draw_start(surface, fonts, highscores, selected_preset, selected_mode):
    """
    Draw the start screen with mode selector and board size buttons.
    Returns (preset_rects, mode_rects) for click detection in handle_events.
    Y positions below — adjust if elements overlap or feel cramped.
    """
    big, small, tiny = fonts
    surface.fill(DIM)
    bob = int(4 * math.sin(pygame.time.get_ticks() * 0.003))   # title bob speed
    draw_centered(surface, big,   "SNAKE",                               SNAKE_GRN, 55 + bob)
    draw_centered(surface, small, "Eat food to fill the board — win!",   WIN_GREEN, 125)
    draw_centered(surface, tiny,  "Red circle    = 1 pt  (fills 2 cells!)", RED,    158)
    draw_centered(surface, tiny,  "Green square  = 5 pts (cycles 5s)",   GREEN,     179)
    draw_centered(surface, tiny,  "Blue triangle = 5 pts + speed boost", BLUE,      200)

    # Mode buttons
    draw_centered(surface, small, "Mode", WHITE, 228)
    mode_rects: list = []
    for i, label in enumerate(["1 Player", "2 Players"]):
        bx   = SCREEN_W // 2 - 136 + i * 144
        rect = pygame.Rect(bx, 245, 128, 38)
        mode_rects.append(rect)
        col  = PRESET_SEL if i == selected_mode else (50, 50, 70)
        brd  = WHITE if i == selected_mode else GRAY
        pygame.draw.rect(surface, col, rect, border_radius=8)
        pygame.draw.rect(surface, brd, rect, 1, border_radius=8)
        lbl  = small.render(label, True, WHITE)
        surface.blit(lbl, lbl.get_rect(center=rect.center))

    if selected_mode == 1:
        draw_centered(surface, tiny, "P1: WASD   P2: Arrow Keys", GRAY, 293)

    # Board size buttons
    draw_centered(surface, small, "Board Size", WHITE, 315)
    btn_w, btn_h = 120, 40
    total_w      = len(PRESETS) * btn_w + (len(PRESETS) - 1) * 16
    start_x      = SCREEN_W // 2 - total_w // 2
    preset_rects: list = []

    for i, (label, gw, gh, key) in enumerate(PRESETS):
        bx   = start_x + i * (btn_w + 16)
        by   = 333
        rect = pygame.Rect(bx, by, btn_w, btn_h)
        preset_rects.append(rect)
        col  = PRESET_SEL if i == selected_preset else (50, 50, 70)
        brd  = WHITE if i == selected_preset else GRAY
        pygame.draw.rect(surface, col, rect, border_radius=8)
        pygame.draw.rect(surface, brd, rect, 1, border_radius=8)
        lbl  = small.render(label, True, WHITE)
        surface.blit(lbl, lbl.get_rect(center=rect.center))
        sz   = tiny.render(f"{gw}×{gh}", True, GRAY)
        surface.blit(sz, sz.get_rect(center=(rect.centerx, rect.bottom + 10)))
        hs   = highscores.get(key, 0)
        hst  = tiny.render(f"Best: {hs}", True, GOLD if hs > 0 else (50, 50, 50))
        surface.blit(hst, hst.get_rect(center=(rect.centerx, rect.bottom + 24)))

    draw_centered(surface, small, "Press any key to start", WHITE, 430)
    return preset_rects, mode_rects

def draw_pause(surface, fonts):
    """Semi-transparent pause overlay. Shows Space to resume and Q to menu."""
    big, small, tiny = fonts
    overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 160))
    surface.blit(overlay, (0, 0))
    draw_centered(surface, big,   "PAUSED",            WHITE, SCREEN_H // 2 - 50)
    draw_centered(surface, small, "Space to continue", GRAY,  SCREEN_H // 2 + 10)
    draw_centered(surface, tiny,  "Q — Menu",          GRAY,  SCREEN_H // 2 + 45)

def draw_endscreen(surface, fonts, gs, highscore, new_best):
    """
    Win screen — handles both 1P (board filled) and 2P (score comparison).
    1P: shows score and highscore.
    2P: compares P1 vs P2 score and shows winner or draw.
    """
    big, small, tiny = fonts
    overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 170))
    surface.blit(overlay, (0, 0))

    if gs["two_player"]:
        p1s = gs["p1_score"]
        p2s = gs["p2_score"]
        if p1s > p2s:
            title, col = "P1 WINS!", SNAKE_GRN
        elif p2s > p1s:
            title, col = "P2 WINS!", SNAKE_P2
        else:
            title, col = "DRAW!", GOLD
        draw_centered(surface, big,   title,                col,   SCREEN_H // 2 - 80)
        draw_centered(surface, small, f"P1: {p1s}   P2: {p2s}", WHITE, SCREEN_H // 2 - 20)
    else:
        score = gs["p1_score"]
        draw_centered(surface, big,   "BOARD FILLED!",      WIN_GREEN, SCREEN_H // 2 - 80)
        draw_centered(surface, small, f"Score: {score}",    WHITE,     SCREEN_H // 2 - 20)
        if new_best:
            draw_centered(surface, small, "New Best!",       GOLD,     SCREEN_H // 2 + 20)
        else:
            draw_centered(surface, tiny, f"Best: {highscore}", GOLD,  SCREEN_H // 2 + 20)

    draw_centered(surface, tiny, "R — Restart     Q — Menu", GRAY, SCREEN_H // 2 + 65)


# ── EVENT HANDLING ────────────────────────────────────────────────────────────

def handle_events(state, gs, preset_rects, mode_rects):
    """
    Process all input events for this frame.
    Returns (new_state, new_preset_index or None, new_mode_index or None).
    Returns (None, None, None) to signal quit.
    """
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            return None, None, None

        # Mouse clicks on start screen buttons
        if state == "start" and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, rect in enumerate(preset_rects):
                if rect.collidepoint(event.pos):
                    return "start", i, None   # preset changed, stay on menu
            for i, rect in enumerate(mode_rects):
                if rect.collidepoint(event.pos):
                    return "start", None, i   # mode changed, stay on menu

        if event.type != pygame.KEYDOWN:
            continue

        if state == "start":
            return "playing", None, None   # any key starts the game

        if state == "playing":
            k  = event.key
            d1 = gs["p1_dir"]
            # P1 — WASD. Prevent reversing (can't go directly opposite direction)
            if   k == pygame.K_w and d1 != (0,  1): gs["p1_next"] = (0, -1)
            elif k == pygame.K_s and d1 != (0, -1): gs["p1_next"] = (0,  1)
            elif k == pygame.K_a and d1 != (1,  0): gs["p1_next"] = (-1, 0)
            elif k == pygame.K_d and d1 != (-1, 0): gs["p1_next"] = (1,  0)
            elif k == pygame.K_SPACE and not gs["two_player"]:
                return "paused", None, None
            elif k in (pygame.K_q, pygame.K_ESCAPE):
                return "start", None, None   # quit to menu mid-game

            # P2 — Arrow keys (only in 2P mode)
            if gs["two_player"]:
                d2 = gs["p2_dir"]
                if   k == pygame.K_UP    and d2 != (0,  1): gs["p2_next"] = (0, -1)
                elif k == pygame.K_DOWN  and d2 != (0, -1): gs["p2_next"] = (0,  1)
                elif k == pygame.K_LEFT  and d2 != (1,  0): gs["p2_next"] = (-1, 0)
                elif k == pygame.K_RIGHT and d2 != (-1, 0): gs["p2_next"] = (1,  0)

        elif state == "paused":
            if event.key == pygame.K_SPACE:
                return "playing", None, None
            if event.key in (pygame.K_q, pygame.K_ESCAPE):
                return "start", None, None   # Q or ESC from pause goes to menu

        elif state == "win":
            if event.key == pygame.K_r:
                return "restart", None, None
            if event.key in (pygame.K_q, pygame.K_ESCAPE):
                return "start", None, None   # Q or ESC from win goes to menu

    return state, None, None


# ── GAME UPDATE ───────────────────────────────────────────────────────────────

def move_snake(gs, player):
    """
    Move one snake one step and handle food collection.
    Snakes pass through their own body and each other — no collision death.
    When food is eaten:
      - Cell is permanently filled (added to gs["filled"])
      - Snake grows (tail not removed)
      - Float text pop-up spawned
      - Speed updated
    """
    snake  = gs[player]
    nk     = "p1" if player == "p1" else "p2"
    d      = gs[f"{nk}_dir"] = gs[f"{nk}_next"]   # apply queued direction
    hx, hy = snake[0]
    # Modulo wraps around edges instead of dying at the wall
    new_head = ((hx + d[0]) % GRID_W, (hy + d[1]) % GRID_H)
    snake.insert(0, new_head)

    ate       = False
    food_type = None

    if new_head == gs["red_pos"]:
        gs[f"{nk}_score"] += 1
        ate               = True
        food_type         = "red"
        gs["red_pos"]     = _spawn(all_snakes(gs), gs["filled"],
                                   exclude=[gs["green_pos"], gs["blue_pos"]])

    elif new_head == gs["green_pos"]:
        gs[f"{nk}_score"]  += 5
        ate                 = True
        food_type           = "green"
        gs["green_pos"]     = _spawn(all_snakes(gs), gs["filled"],
                                     exclude=[gs["red_pos"], gs["blue_pos"]])
        gs["green_timer"]   = GREEN_CYCLE   # reset timer on eat

    elif new_head == gs["blue_pos"]:
        gs[f"{nk}_score"]  += 5
        ate                 = True
        food_type           = "blue"
        gs["blue_pos"]      = None
        gs[f"{nk}_stack"]  += 1             # stack the speed boost
        gs[f"{nk}_decay"]   = BLUE_DECAY    # reset decay timer

    if ate:
        # Permanently mark the eaten cell as filled
        gs["filled"][new_head] = food_type

        if food_type == "red":
            # Red bonus — fills one extra random cell to compensate for only giving 1 pt
            # WHY: red fills 2 cells making it useful for finishing the board faster
            # Remove these 4 lines to make red food only fill its own cell
            bonus = _spawn(all_snakes(gs), gs["filled"],
                           exclude=[gs["red_pos"], gs["green_pos"], gs["blue_pos"]])
            if bonus:
                gs["filled"][bonus] = "red"

        # Spawn a floating score pop-up at the food's position
        pts   = 1 if food_type == "red" else 5
        col   = RED if food_type == "red" else (GREEN if food_type == "green" else BLUE)
        px    = new_head[0] * CELL + CELL // 2
        py    = new_head[1] * CELL
        label = f"+{pts}" if not gs["two_player"] else f"P{'1' if nk == 'p1' else '2'} +{pts}"
        gs["floats"].append(FloatText(label, px, py, col))

        # Speed scales with total score — both players contribute in 2P
        total_score     = gs["p1_score"] + (gs.get("p2_score", 0))
        base_fps        = min(FPS_MAX, FPS_START + (total_score // 5) * FPS_STEP)
        gs[f"{nk}_fps"] = min(FPS_MAX + 5, base_fps + gs[f"{nk}_stack"] * BLUE_BOOST)

        # Spawn blue food at score milestone if none currently exists
        if gs["blue_pos"] is None and total_score >= gs["next_blue"]:
            gs["blue_pos"]  = _spawn(all_snakes(gs), gs["filled"],
                                     exclude=[gs["red_pos"], gs["green_pos"]])
            gs["next_blue"] += BLUE_SCORE
    else:
        snake.pop()   # no food eaten — remove tail so snake just moves forward

    return food_type

def update(gs, dt):
    """
    Advance the entire game state by one frame (dt milliseconds).
    Returns "playing", "win".
    """
    # Blue boost decay — counts down for each player independently
    for nk in (["p1"] + (["p2"] if gs["two_player"] else [])):
        if gs[f"{nk}_stack"] > 0:
            gs[f"{nk}_decay"] -= dt
            if gs[f"{nk}_decay"] <= 0:
                # Stack expired — reset speed to base
                gs[f"{nk}_stack"] = 0
                gs[f"{nk}_decay"] = 0
                gs[f"{nk}_fps"]   = min(FPS_MAX, FPS_START + (gs[f"{nk}_score"] // 5) * FPS_STEP)

    # Green food cycle — automatically moves to a new position every GREEN_CYCLE ms
    gs["green_timer"] -= dt
    if gs["green_timer"] <= 0:
        gs["green_pos"]   = _spawn(all_snakes(gs), gs["filled"],
                                   exclude=[gs["red_pos"], gs["blue_pos"]])
        gs["green_timer"] = GREEN_CYCLE

    move_snake(gs, "p1")
    if gs["two_player"]:
        move_snake(gs, "p2")

    # Update and clean up floating score texts
    for ft in gs["floats"]:
        ft.update(dt)
    gs["floats"] = [f for f in gs["floats"] if f.alive]

    # Win — triggered when every cell has been filled by eaten food
    total_cells = GRID_W * GRID_H
    if len(gs["filled"]) >= total_cells:
        return "win"
    # Backup check: if no free cells remain AND no red food exists, board is effectively full
    free = _spawn(all_snakes(gs), gs["filled"])
    if free is None and gs["red_pos"] is None:
        return "win"

    return "playing"


# ── GAME DRAW ─────────────────────────────────────────────────────────────────

def draw_game(surface, grid_surf, gs, state, fonts, highscore, new_best):
    """Render one frame of the game. Drawing order: grid → filled → food → floats → snakes → HUD → overlay."""
    _, _, tiny = fonts
    surface.blit(grid_surf, (0, 0))   # pre-rendered background

    # Filled cells — colored by which food type filled them
    color_map = {"red": FILLED_RED, "green": FILLED_GREEN, "blue": FILLED_BLUE}
    for (fx, fy), ftype in gs["filled"].items():
        draw_cell(surface, color_map[ftype], fx, fy)

    # Food items
    if gs["red_pos"]:
        draw_red_food(surface, gs["red_pos"][0], gs["red_pos"][1])
    if gs["green_pos"]:
        draw_green_food(surface, gs["green_pos"][0], gs["green_pos"][1], gs["green_timer"])
    if gs["blue_pos"]:
        draw_blue_food(surface, gs["blue_pos"][0], gs["blue_pos"][1])

    # Floating score pop-ups — rendered before snakes so snakes appear on top
    font_small = fonts[1]
    for ft in gs["floats"]:
        s  = font_small.render(ft.text, True, ft.color)
        ts = pygame.Surface(s.get_size(), pygame.SRCALPHA)
        ts.blit(s, (0, 0))
        ts.set_alpha(ft.alpha)
        surface.blit(ts, (int(ft.x) - s.get_width() // 2, int(ft.y)))

    # P1 snake — green gradient (bright at head, dark at tail)
    body = gs["p1"][1:]
    for i, (gx, gy) in enumerate(body):
        draw_cell(surface, body_color(i, len(body), SNAKE_GRN, DARK_GREEN), gx, gy)
    draw_snake_head(surface, gs["p1"][0][0], gs["p1"][0][1], gs["p1_dir"], SNAKE_GRN)

    # P2 snake — orange gradient
    if gs["two_player"]:
        body2 = gs["p2"][1:]
        for i, (gx, gy) in enumerate(body2):
            draw_cell(surface, body_color(i, len(body2), SNAKE_P2, DARK_P2), gx, gy)
        draw_snake_head(surface, gs["p2"][0][0], gs["p2"][0][1], gs["p2_dir"], SNAKE_P2)

    # HUD — 2P shows both scores, 1P shows score + best + fill %
    total = GRID_W * GRID_H
    pct   = int(len(gs["filled"]) / total * 100)
    if gs["two_player"]:
        p1_txt  = tiny.render(f"P1: {gs['p1_score']}", True, SNAKE_GRN)
        p2_txt  = tiny.render(f"P2: {gs['p2_score']}", True, SNAKE_P2)
        pct_txt = tiny.render(f"Filled: {pct}%",       True, WHITE)
        surface.blit(p1_txt,  (8, 6))
        surface.blit(p2_txt,  (8, 22))
        surface.blit(pct_txt, (SCREEN_W - pct_txt.get_width() - 8, 6))
    else:
        hud = tiny.render(
            f"Score: {gs['p1_score']}   Best: {highscore}   Filled: {pct}%", True, WHITE)
        surface.blit(hud, (8, 6))
        if gs["p1_stack"] > 0:
            secs  = max(0, gs["p1_decay"] // 1000)
            boost = tiny.render(f"x{gs['p1_stack']} ({secs}s)", True, BLUE)
            surface.blit(boost, (SCREEN_W - boost.get_width() - 8, 6))

    # Overlay screens drawn on top of everything
    if state == "paused":
        draw_pause(surface, fonts)
    elif state == "win":
        draw_endscreen(surface, fonts, gs, highscore, new_best)


# ── MAIN ──────────────────────────────────────────────────────────────────────

async def main():
    global GRID_W, GRID_H, SCREEN_W, SCREEN_H

    pygame.init()

    selected_preset = 1   # default to Medium
    selected_mode   = 0   # 0 = 1 player, 1 = 2 players
    _, GRID_W, GRID_H, preset_key = PRESETS[selected_preset]
    SCREEN_W = CELL * GRID_W
    SCREEN_H = CELL * GRID_H

    # Start at menu size — window only resizes when game actually starts
    screen = pygame.display.set_mode((MENU_W, MENU_H))
    pygame.display.set_caption("Snake — Fill the Board")
    clock  = pygame.time.Clock()

    fonts = (
        pygame.font.SysFont("monospace", 48, bold=True),   # big   — title, win screen
        pygame.font.SysFont("monospace", 24),               # small — buttons, score labels
        pygame.font.SysFont("monospace", 18),               # tiny  — HUD, hints
    )

    grid_surf      = make_grid_surface()
    highscores     = load_highscores()
    highscore      = highscores.get(preset_key, 0)
    gs             = make_state(two_player=False)
    state          = "start"
    new_best       = False
    last_tick      = pygame.time.get_ticks()
    preset_rects: list = []
    mode_rects: list   = []

    while True:
        now       = pygame.time.get_ticks()
        dt        = now - last_tick
        last_tick = now

        new_state, new_preset, new_mode = handle_events(state, gs, preset_rects, mode_rects)

        if new_state is None:
            break   # window closed — exit loop

        # Preset button clicked on start screen — update selection, don't resize yet
        if new_preset is not None and new_preset != selected_preset:
            selected_preset = new_preset
            _, _, _, preset_key = PRESETS[selected_preset]
            highscores = load_highscores()
            highscore  = highscores.get(preset_key, 0)

        # Mode button clicked on start screen
        if new_mode is not None and new_mode != selected_mode:
            selected_mode = new_mode

        # Game starting — NOW apply the chosen preset and resize window
        if new_state == "playing" and state == "start":
            _, GRID_W, GRID_H, preset_key = PRESETS[selected_preset]
            SCREEN_W  = CELL * GRID_W
            SCREEN_H  = CELL * GRID_H
            screen    = pygame.display.set_mode((SCREEN_W, SCREEN_H))
            grid_surf = make_grid_surface()
            gs        = make_state(two_player=(selected_mode == 1))
            highscores = load_highscores()
            highscore  = highscores.get(preset_key, 0)

        # Restart — same board size and mode, fresh game state
        if new_state == "restart":
            gs        = make_state(two_player=gs["two_player"])
            new_best  = False
            new_state = "playing"

        # Returning to menu — reset state so menu shows cleanly
        if new_state == "start" and state != "start":
            gs       = make_state()
            new_best = False

        if new_state == "playing" and state in ("win",):
            new_best = False

        state = new_state

        if state == "playing":
            result = update(gs, dt)
            if result == "win":
                # Save highscore only in 1P mode
                if not gs["two_player"] and gs["p1_score"] > highscore:
                    highscore = gs["p1_score"]
                    new_best  = True
                    save_highscore(preset_key, highscore)
                    highscores[preset_key] = highscore
                state = "win"

        # Menu always renders at medium size — resize back if returning from a large game
        if state == "start":
            if screen.get_size() != (MENU_W, MENU_H):
                screen   = pygame.display.set_mode((MENU_W, MENU_H))
                SCREEN_W = MENU_W
                SCREEN_H = MENU_H
            preset_rects, mode_rects = draw_start(
                screen, fonts, highscores, selected_preset, selected_mode)
        else:
            draw_game(screen, grid_surf, gs, state, fonts, highscore, new_best)

        pygame.display.flip()
        await asyncio.sleep(0)   # required by pygbag — lets browser breathe between frames
        clock.tick(gs["p1_fps"] if state == "playing" else 30)

    pygame.quit()   # clean up pygame resources before exiting


# =============================================================================
if __name__ == "__main__":
    asyncio.run(main())