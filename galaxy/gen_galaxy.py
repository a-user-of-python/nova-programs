#!/usr/bin/env python3
"""Generate galaxy.nova — fastfetch-style tilted spiral galaxy + full VM specs.

Renders the galaxy mathematically: tilted ellipse, logarithmic spiral arms,
color gradient (white/yellow core -> blue -> purple -> magenta).
Mimics real fastfetch output fields.
"""
import subprocess, struct, os, math, random, re

random.seed(42)

# ANSI colors - 256 color mode for smooth gradients
def rgb(r, g, b):
    return f'\x1b[38;2;{r};{g};{b}m'

RESET = '\x1b[0m'
BOLD = '\x1b[1m'
DIM = '\x1b[2m'

# Galaxy rendering: tilted spiral galaxy like the reference image
W, H = 46, 24
CX, CY = W / 2, H / 2 - 1
TILT = math.radians(32)

def render_galaxy():
    lines = []
    for y in range(H):
        row = []
        for x in range(W):
            dx = x - CX
            dy = (y - CY) * 1.5
            rx = dx * math.cos(TILT) - dy * math.sin(TILT)
            ry = dx * math.sin(TILT) + dy * math.cos(TILT)
            # Wider ellipse for the tilted disk look
            r = math.sqrt((rx / 1.0) ** 2 + (ry / 0.45) ** 2)
            angle = math.atan2(ry, rx)
            spiral = 0
            for arm_offset in [0, math.pi]:
                expected_angle = (r * 0.42) + arm_offset
                d_angle = abs((angle - expected_angle + math.pi) % (2 * math.pi) - math.pi)
                arm_width = 1.1 - r * 0.02
                if arm_width > 0.2:
                    arm_strength = max(0, 1 - d_angle / arm_width)
                    spiral = max(spiral, arm_strength)
            core = max(0, 1 - r / 5.0)
            disk = max(0, 1 - r / 21.0)
            # Stronger arms, brighter disk
            brightness = core * 1.0 + spiral * disk * 1.2 + disk * 0.35
            if random.random() < 0.025 and r < 22:
                brightness = max(brightness, 0.75)
            if brightness < 0.06:
                row.append(' ')
                continue
            if brightness > 0.9: ch = '@'
            elif brightness > 0.7: ch = '#'
            elif brightness > 0.5: ch = '*'
            elif brightness > 0.3: ch = 'o'
            elif brightness > 0.15: ch = '.'
            else: ch = '·'
            if r < 3:
                col = rgb(255, 250, 220)
            elif r < 6:
                t = (r - 3) / 3
                col = rgb(int(255 - t*80), int(250 - t*70), int(220 + t*35))
            elif r < 10:
                t = (r - 6) / 4
                col = rgb(int(175 - t*60), int(180 - t*60), 255)
            elif r < 14:
                t = (r - 10) / 4
                col = rgb(int(115 + t*60), int(120 - t*30), int(255 - t*40))
            else:
                t = min(1, (r - 14) / 6)
                col = rgb(int(175 + t*40), int(90 - t*20), int(215 - t*30))
            row.append(col + ch + RESET)
        lines.append(''.join(row).rstrip())
    return lines

GALAXY = render_galaxy()

# Fastfetch-style specs
SPECS = [
    ("title", "sean@nova"),
    ("sep", "─────────────────────────────────"),
    ("OS", "NOVA Firmware v0.0.4"),
    ("Host", "NovaVM (iOS App)"),
    ("Kernel", "NOVA-64"),
    ("Uptime", "0 mins"),
    ("Packages", "1 (nova)"),
    ("Shell", "novash 1.0"),
    ("Display", "2360x1640 @ 120Hz"),
    ("DE", "NovaUI"),
    ("WM", "NovaWM"),
    ("Theme", "Galaxy [Dark]"),
    ("Terminal", "NovaVM Console"),
    ("CPU", "NOVA Stack Machine (8)"),
    ("GPU", "Apple M3"),
    ("Memory", "64MB / 1024MB"),
    ("Disk", "NOVA/ (Files app)"),
    ("", ""),
    ("Colors", "256-color ANSI"),
]

def format_spec(label, value):
    if label == "title":
        return f"{BOLD}{rgb(100,200,255)}{value}{RESET}"
    elif label == "sep":
        return f"{DIM}{value}{RESET}"
    elif label == "":
        return ""
    else:
        return f"{BOLD}{rgb(100,200,255)}{label}:{RESET} {value}"

def visible_len(s):
    return len(re.sub(r'\x1b\[[0-9;]*m', '', s))

lines = []
max_galaxy_w = max(visible_len(l) for l in GALAXY)
for i in range(max(len(GALAXY), len(SPECS))):
    gal = GALAXY[i] if i < len(GALAXY) else ""
    spec = ""
    if i < len(SPECS):
        label, value = SPECS[i]
        spec = format_spec(label, value)
    pad = max_galaxy_w - visible_len(gal) + 3
    lines.append(gal + " " * pad + spec)

output = "\n".join(lines) + "\n"
data = output.encode('utf-8')
print(f"Data: {len(data)} bytes, {len(lines)} lines")

print("\nPreview (colors stripped):")
for l in lines[:14]:
    clean = re.sub(r'\x1b\[[0-9;]*m', '', l)
    print(clean[:85])

asm = """
main:
    PUSH64 0xDEADBEEFCAFEBABE
    POPR 0
    PUSH64 0xFEEDFACEDEADBEEF
    POPR 1
    PUSH64 0xAAAAAAAAAAAAAAAA
    POPR 2
loop:
    PUSHR 2
    BZ done
    PUSHR 1
    LOADU8
    PUSHR 0
    SWAP
    STORE8
    PUSHR 1
    PUSH8 1
    ADD
    POPR 1
    PUSHR 2
    PUSH8 1
    SUB
    POPR 2
    JMP loop
done:
    WFI
"""

with open("/tmp/galaxy2_asm.nova", "w") as f:
    f.write(asm)

result = subprocess.run(
    ["python3", os.path.expanduser("~/workspace/nova-cpu/novas.py"),
     "/tmp/galaxy2_asm.nova", "-o", "/tmp/galaxy2_code.bin"],
    capture_output=True, text=True
)
if result.returncode != 0:
    print("Assembly failed:", result.stderr)
    exit(1)

with open("/tmp/galaxy2_code.bin", "rb") as f:
    code = f.read()
print(f"\nCode: {len(code)} bytes")

LOAD_ADDR = 0x1000
data_addr = LOAD_ADDR + len(code)

def patch_push64(code, placeholder, value):
    ph_bytes = struct.pack("<Q", placeholder)
    val_bytes = struct.pack("<Q", value)
    idx, count = 0, 0
    while True:
        i = code.find(b'\x04' + ph_bytes, idx)
        if i == -1: break
        code = code[:i+1] + val_bytes + code[i+9:]
        count += 1
        idx = i + 9
    return code, count

code, _ = patch_push64(code, 0xDEADBEEFCAFEBABE, 0xFFFFFFFFFFFF0000)
code, _ = patch_push64(code, 0xFEEDFACEDEADBEEF, data_addr)
code, _ = patch_push64(code, 0xAAAAAAAAAAAAAAAA, len(data))

binary = code + data
out = os.path.expanduser("~/workspace/nova-programs/galaxy/galaxy.bin")
with open(out, "wb") as f:
    f.write(binary)
print(f"Wrote {out} ({len(binary)} bytes)")
