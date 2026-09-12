# 8-Bit Cricket: Your Favourite Game — in Retro!

An authentic 8-bit retro arcade cricket game built with Pygame. Bat against varying bowling lengths and lines, time your shots to perfection, manage your batter stamina, and climb the all-time leaderboard!

---

## Game Features

- **Dynamic Chase Targets:** Chase balanced, realistic targets generated every match before losing 3 wickets.
- **Timing & Ball Physics:** Read the bowler's length (Yorker, Full, Good, Short) and line (Off, Mid, Leg), then time the swing meter to connect with the sweet spot.
- **Shot Variety & Energy Management:**
  - **DEFEND:** Free defensive block that costs 0 energy (scores 0 runs, but protects your wicket).
  - **DRIVE:** Ground shot with lower risk, starting at 8 energy.
  - **LOFT:** Aerial power shot capable of clearing the ropes for SIX, starting at 15 energy.
  - **Shot Fatigue:** Repeatedly using attacking shots progressively escalates energy costs (tracked by `D` and `L` beside the stamina bar).
- **Active Combo System:** String together consecutive scoring deliveries to rack up combo badges (`COMBO X2!`, `COMBO X3!`).
- **Scorecards & Leaderboard:**
  - **My Matches:** Complete scorecard history tracking runs, wickets, overs, fours, and sixes.
  - **Top Scores:** All-time Hall of Fame leaderboard ranking players across local accounts.
- **Secure Local Accounts:** Salted PBKDF2 password hashes stored in SQLite with resilient user-directory fallback support.
- **In-Match Pause & Rematch Flow:** Safe pause menu prevents accidental match quits, and direct rematch buttons keep you in the action.

---

## Controls

| Key | Action |
| :--- | :--- |
| **Space** | Start delivery / Swing bat when needle enters gold zone / Quick "Play Again" rematch |
| **Left / Right** or **A / D** | Select shot (`DEFEND`, `DRIVE`, `LOFT`) / Navigate records pages |
| **Up / Down** or **W / S** | Navigate menus and fields |
| **Enter / Return** | Confirm selection |
| **Tab** | Switch between Login / Signup and My Matches / Top Scores Leaderboard |
| **Esc** | Pause match (Resume or Quit to Menu) / Go back |
| **M** | Toggle sound effects Mute / Unmute |
| **F** or **F11** | Toggle Fullscreen |

---

## Getting Started

### Prerequisites
- Python 3.9+
- Pygame $\ge$ 2.5.0

### Installation & Run

```bash
# Clone the repository
git clone https://github.com/Golden-Moon-SK/cricket-game.git
cd cricket-game

# Set up virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the game
python3 main.py
```

---

## Packaging & Deployment

### Web Browser (HTML5 via Pygbag)
To compile and bundle for web / itch.io / GitHub Pages:
```bash
pip install pygbag
pygbag --build .
```

### Standalone Executable (PyInstaller)
To package into a standalone desktop executable:
```bash
pip install pyinstaller
pyinstaller --name "8BitCricket" --windowed --onefile --add-data "schema.sql:." main.py
```

