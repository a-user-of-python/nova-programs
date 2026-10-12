# Galaxy — NOVA fastfetch

A fastfetch-style program that displays a colored spiral galaxy made of ASCII characters alongside NOVA VM specs.

## Preview

```
              .  *  .                user@nova
           *     .     *             ─────────────────
        .    .  *  .    .            OS: NOVA Firmware v0.0.1
     *    .    ***    .    *         CPU: NOVA Stack Machine
   .   .   **^^^^^**   .   .         Arch: nova64 (64-bit)
  *  .  **^         ^**  .  *        Cores: 8 (4P+4E)
  .  . *^             ^* .  .        Memory: 256 MB / 1024 MB
     *^               ^*             ISA: Stack-based, 1-9 byte
  . *^      @@@      ^* .            Stacks: Data, Call, Exc, Vector
  * ^     @@@@@@@     ^ *            Regs: R0-R15 (16x64-bit)
  .^     @@@@@@@@@     ^.            Priv: 4 levels
   ^     @@@@@@@@@     ^             MMU: 3-level paging
  .^     @@@@@@@@@     ^.            Crypto: AES-256, SHA-256
  ...
```

(The actual output uses ANSI colors: blue → cyan → magenta → yellow → white gradient.)

## Files

- `galaxy.bin` — ready-to-run binary (load in NovaVM app)
- `galaxy.nova` — assembly source (generated, see below)
- `gen_galaxy.py` — Python generator that builds the binary

## Building

```bash
python3 gen_galaxy.py
```

This assembles the print loop, generates the colored galaxy + specs text, and patches the binary with the correct data address and length.

## How It Works

The program uses NOVA's registers and MMIO console:
1. `R0` = console address (`0xFFFF_FFFF_FFFF_0000`)
2. `R1` = pointer to the text data
3. `R2` = remaining byte count
4. Loop: load byte via `LOADU8`, `STORE8` to console, increment pointer, decrement count

---

*Built with Muse*
