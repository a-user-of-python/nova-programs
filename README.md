# NOVA Programs

Programs for the **NOVA** custom CPU architecture. Each program lives in its own folder with source, binary, and generator (if any).

## Programs

| Program | Description |
|---------|-------------|
| [galaxy](galaxy/) | fastfetch-style spiral galaxy + VM specs in colored ASCII art |

## Running

Assemble with the NOVA assembler:
```bash
python3 /path/to/nova-cpu/novas.py program.nova -o program.bin
```

Or use the pre-built `.bin` files directly in the NovaVM iOS app.

## Adding Programs

Each program folder should contain:
- `*.nova` — assembly source
- `*.bin` — assembled binary (ready to run)
- `gen_*.py` — generator script (if the program was generated)

---

*Built with Muse*
