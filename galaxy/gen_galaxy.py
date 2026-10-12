#!/usr/bin/env python3
"""Generate galaxy.nova — a fastfetch-style galaxy + VM specs program for NOVA.

Builds the binary directly: code (assembled) + data (raw bytes), with
patched addresses. The program prints a colored spiral galaxy and VM specs.
"""
import subprocess, struct, os

# ANSI colors
C = {
    'blue': '\x1b[34m', 'magenta': '\x1b[35m', 'cyan': '\x1b[36m',
    'white': '\x1b[37m', 'yellow': '\x1b[33m', 'reset': '\x1b[0m',
    'bold': '\x1b[1m', 'dim': '\x1b[2m',
}

# Galaxy art lines (35 chars wide), with color gradients
# Spiral galaxy: blue outer arms -> magenta -> pink/white core
GALAXY = [
    (C['blue'],    "              .  *  .              "),
    (C['blue'],    "           *     .     *           "),
    (C['blue'],    "        .    .  *  .    .          "),
    (C['cyan'],    "     *    .    ***    .    *       "),
    (C['cyan'],    "   .   .   **^^^^^**   .   .       "),
    (C['magenta'], "  *  .  **^         ^**  .  *      "),
    (C['magenta'], "  .  . *^             ^* .  .      "),
    (C['magenta'], "     *^               ^*          "),
    (C['yellow'],  "  . *^      @@@      ^* .         "),
    (C['yellow'],  "  * ^     @@@@@@@     ^ *         "),
    (C['white'],   "  .^     @@@@@@@@@     ^.         "),
    (C['white'],   "   ^     @@@@@@@@@     ^          "),
    (C['white'],   "  .^     @@@@@@@@@     ^.         "),
    (C['yellow'],  "  * ^     @@@@@@@     ^ *         "),
    (C['yellow'],  "  . *^      @@@      ^* .         "),
    (C['magenta'], "     *^               ^*          "),
    (C['magenta'], "  .  . *^             ^* .  .      "),
    (C['magenta'], "  *  .  **^         ^**  .  *      "),
    (C['cyan'],    "   .   .   **^^^^^**   .   .       "),
    (C['blue'],    "     *    .    ***    .    *       "),
]

SPECS = [
    ((C['bold'] + C['cyan'], "sean@nova"),),
    ((C['dim'],              "─────────────────"),),
    ((C['bold'], "OS: "),      (C['reset'], "NOVA Firmware v0.0.1")),
    ((C['bold'], "CPU: "),     (C['reset'], "NOVA Stack Machine")),
    ((C['bold'], "Arch: "),    (C['reset'], "nova64 (64-bit)")),
    ((C['bold'], "Cores: "),   (C['reset'], "8 (4P+4E)")),
    ((C['bold'], "Memory: "),  (C['reset'], "256 MB / 1024 MB")),
    ((C['bold'], "ISA: "),     (C['reset'], "Stack-based, 1-9 byte")),
    ((C['bold'], "Stacks: "),  (C['reset'], "Data, Call, Exc, Vector")),
    ((C['bold'], "Regs: "),    (C['reset'], "R0-R15 (16x64-bit)")),
    ((C['bold'], "Priv: "),    (C['reset'], "4 levels")),
    ((C['bold'], "MMU: "),     (C['reset'], "3-level paging")),
    ((C['bold'], "Crypto: "),  (C['reset'], "AES-256, SHA-256")),
    (("", ""),),
    ((C['dim'], "Built with Muse"),),
]

# Build the output text: galaxy left, specs right
lines = []
for i in range(max(len(GALAXY), len(SPECS))):
    art = ""
    if i < len(GALAXY):
        color, text = GALAXY[i]
        art = color + text + C['reset']
    spec = ""
    if i < len(SPECS):
        parts = SPECS[i]
        # Each entry is a tuple of (color, text) pairs
        spec = "".join(c + t for c, t in parts) + C['reset']
    lines.append(art + "  " + spec)

output = "\n".join(lines) + "\n"
data = output.encode('utf-8')
print(f"Data size: {len(data)} bytes, {len(lines)} lines")

# Assembly code (with placeholders for ADDR and LEN)
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

with open("/tmp/galaxy_asm.nova", "w") as f:
    f.write(asm)

# Assemble
result = subprocess.run(
    ["python3", os.path.expanduser("~/workspace/nova-cpu/novas.py"),
     "/tmp/galaxy_asm.nova", "-o", "/tmp/galaxy_code.bin"],
    capture_output=True, text=True
)
if result.returncode != 0:
    print("Assembly failed:")
    print(result.stderr)
    exit(1)

with open("/tmp/galaxy_code.bin", "rb") as f:
    code = f.read()
print(f"Code size: {len(code)} bytes")

# Program loads at 0x1000 (with firmware) — data follows code
LOAD_ADDR = 0x1000
data_addr = LOAD_ADDR + len(code)

# Patch placeholders
# PUSH64 is 0x04 + 8 bytes LE
def patch_push64(code, placeholder, value):
    ph_bytes = struct.pack("<Q", placeholder)
    val_bytes = struct.pack("<Q", value)
    # Find PUSH64 (0x04) followed by placeholder
    idx = 0
    count = 0
    while True:
        i = code.find(b'\x04' + ph_bytes, idx)
        if i == -1:
            break
        code = code[:i+1] + val_bytes + code[i+9:]
        count += 1
        idx = i + 9
    return code, count

code, c1 = patch_push64(code, 0xDEADBEEFCAFEBABE, 0xFFFFFFFFFFFF0000)  # console
code, c2 = patch_push64(code, 0xFEEDFACEDEADBEEF, data_addr)          # data addr
code, c3 = patch_push64(code, 0xAAAAAAAAAAAAAAAA, len(data))          # data len
print(f"Patched {c1+c2+c3} addresses (console, data_addr=0x{data_addr:x}, len={len(data)})")

# Final binary
binary = code + data
out_path = os.path.expanduser("~/workspace/nova-cpu/examples/galaxy.bin")
with open(out_path, "wb") as f:
    f.write(binary)
print(f"Wrote {out_path} ({len(binary)} bytes)")

# Also save the .nova source for reference
with open(os.path.expanduser("~/workspace/nova-cpu/examples/galaxy.nova"), "w") as f:
    f.write("; galaxy.nova — fastfetch-style galaxy + NOVA VM specs\n")
    f.write("; Generated by gen_galaxy.py — do not hand-edit, see generator\n")
    f.write(asm)
print("Done")
