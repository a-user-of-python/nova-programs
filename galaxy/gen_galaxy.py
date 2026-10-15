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
    ("title", "user@nova"),
    ("sep", "─────────────────────────────────"),
    ("OS", "NOVA Firmware v0.0.4"),
    ("Host", "NovaVM (iOS App)"),
    ("Kernel", "NOVA-64"),
    ("Uptime", "__DYN_UPTIME__"),
    ("Date", "__DYN_DATE__"),
    ("Packages", "1 (nova)"),
    ("Shell", "novash 1.0"),
    ("Display", "2360x1640 @ 120Hz"),
    ("DE", "NovaUI"),
    ("WM", "NovaWM"),
    ("Theme", "Galaxy [Dark]"),
    ("Terminal", "NovaVM Console"),
    ("CPU", "Nova-1 (8)"),
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
    elif value.startswith("__DYN_"):
        return f"{BOLD}{rgb(100,200,255)}{label}:{RESET}"
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

# Split into 3 parts around the dynamic Uptime/Date lines.
# part1 ends after the "Uptime:" label (no newline); code prints " N seconds\n".
# part2 spans from the next line through the "Date:" label; code prints " <datetime>\n".
# part3 is the remainder.
idx_u = next(i for i, (l, v) in enumerate(SPECS) if v == "__DYN_UPTIME__")
idx_d = next(i for i, (l, v) in enumerate(SPECS) if v == "__DYN_DATE__")
part1 = "\n".join(lines[:idx_u+1])
part2 = "\n" + "\n".join(lines[idx_u+1:idx_d+1])
part3 = "\n" + "\n".join(lines[idx_d+1:]) + "\n"
data1 = part1.encode('utf-8')
data2 = part2.encode('utf-8')
data3 = part3.encode('utf-8')
data = data1 + data2 + data3
print(f"Data: {len(data)} bytes ({len(data1)}+{len(data2)}+{len(data3)}), {len(lines)} lines")

print("\nPreview (colors stripped):")
for l in lines[:14]:
    clean = re.sub(r'\x1b\[[0-9;]*m', '', l)
    print(clean[:85])

import json as _json
with open(os.path.expanduser("~/workspace/nova-programs/novashell/firmware_addrs.json")) as _jf:
    _addrs = _json.load(_jf)
_UPTIME_ADDR = _addrs["UPTIME"]
_DATETIME_ADDR = _addrs["DATETIME"]
print(f"Firmware addrs: UPTIME={_UPTIME_ADDR} DATETIME={_DATETIME_ADDR}")

asm = f"""
main:
    ; R15 = load address (firmware sets it). Data parts follow the code.
    PUSH64 0xDEADBEEFCAFEBABE
    POPR 0                      ; R0 = console MMIO
    ; ---- memcpy part1 ----
    PUSHR 15
    PUSH64 0xFEEDFACEDEADBEEF
    ADD
    POPR 1                      ; R1 = src
    PUSH64 0xAAAAAAAAAAAAAAAA
    POPR 2                      ; R2 = len
    CALL memcpy
    ; ---- print " <uptime_secs> seconds" ----
    PUSH8 32
    PUSHR 0
    STORE8
    PUSH64 {_UPTIME_ADDR}
    LOAD64
    PUSH8 10
    DIVU
    CALL print_u64
    PUSHR 0
    POPR 3                      ; R3 = console (print_str clobbers R0? no, keep simple)
    PUSH8 32
    PUSHR 0
    STORE8
    ; "seconds"
    PUSH8 115
    PUSHR 0
    STORE8
    PUSH8 101
    PUSHR 0
    STORE8
    PUSH8 99
    PUSHR 0
    STORE8
    PUSH8 111
    PUSHR 0
    STORE8
    PUSH8 110
    PUSHR 0
    STORE8
    PUSH8 100
    PUSHR 0
    STORE8
    PUSH8 115
    PUSHR 0
    STORE8
    PUSH8 10
    PUSHR 0
    STORE8
    ; ---- memcpy part2 ----
    PUSHR 15
    PUSH64 0xBBBBBBBBBBBBBBBB
    ADD
    POPR 1
    PUSH64 0xCCCCCCCCCCCCCCCC
    POPR 2
    CALL memcpy
    ; ---- print " <datetime>" ----
    PUSH8 32
    PUSHR 0
    STORE8
    PUSH64 {_DATETIME_ADDR}
    POPR 1                      ; R1 = datetime str
pr_date:
    PUSHR 1
    LOADU8
    DUP
    BZ pr_date_done
    PUSHR 0
    STORE8
    PUSHR 1
    PUSH8 1
    ADD
    POPR 1
    JMP pr_date
pr_date_done:
    POP
    PUSH8 10
    PUSHR 0
    STORE8
    ; ---- memcpy part3 ----
    PUSHR 15
    PUSH64 0xDDDDDDDDDDDDDDDD
    ADD
    POPR 1
    PUSH64 0xEEEEEEEEEEEEEEEE
    POPR 2
    CALL memcpy
done:
    ECALL

; memcpy: R0=console, R1=src, R2=len
memcpy:
    PUSHR 2
    BZ memcpy_done
mc_loop:
    PUSHR 2
    BZ memcpy_done
    PUSHR 1
    LOADU8
    PUSHR 0
    STORE8
    PUSHR 1
    PUSH8 1
    ADD
    POPR 1
    PUSHR 2
    PUSH8 1
    SUB
    POPR 2
    JMP mc_loop
memcpy_done:
    RET

; print_u64: u64 on stack -> decimal to console (R0)
print_u64:
    POPR 11                     ; R11 = value
    PUSH8 0
    POPR 12                     ; R12 = digit count
    PUSHR 11
    PUSH8 0
    EQ
    BZ pu_digits
    PUSH8 48                    ; '0'
    PUSH8 1
    POPR 12
    JMP pu_print
pu_digits:
    PUSHR 11
    PUSH8 0
    EQ
    BNZ pu_print
    PUSHR 11
    PUSH8 10
    REMU
    PUSH8 48
    ADD
    PUSHR 11
    PUSH8 10
    DIVU
    POPR 11
    PUSHR 12
    PUSH8 1
    ADD
    POPR 12
    JMP pu_digits
pu_print:
    PUSHR 12
    BZ pu_done
    POPR 11
    PUSHR 11
    PUSHR 0
    STORE8
    PUSHR 12
    PUSH8 1
    SUB
    POPR 12
    JMP pu_print
pu_done:
    RET
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

LOAD_ADDR = 0x10000
code_len = len(code)
d1_addr = LOAD_ADDR + code_len
d2_addr = d1_addr + len(data1)
d3_addr = d2_addr + len(data2)

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
code, _ = patch_push64(code, 0xFEEDFACEDEADBEEF, code_len)       # part1 offset
code, _ = patch_push64(code, 0xAAAAAAAAAAAAAAAA, len(data1))
code, _ = patch_push64(code, 0xBBBBBBBBBBBBBBBB, code_len + len(data1))  # part2 offset
code, _ = patch_push64(code, 0xCCCCCCCCCCCCCCCC, len(data2))
code, _ = patch_push64(code, 0xDDDDDDDDDDDDDDDD, code_len + len(data1) + len(data2))  # part3
code, _ = patch_push64(code, 0xEEEEEEEEEEEEEEEE, len(data3))

binary = code + data1 + data2 + data3
out = os.path.expanduser("~/workspace/nova-programs/galaxy/galaxy.bin")
with open(out, "wb") as f:
    f.write(binary)
print(f"Wrote {out} ({len(binary)} bytes)")
