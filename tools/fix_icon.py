#!/usr/bin/env python3
"""
fix_icon.py — Fix a PNG for use as a macOS template (tray) icon.

Thresholds the alpha channel so every pixel is either fully opaque (255)
or fully transparent (0). Properly reverses PNG row filters before modifying
pixels, then re-emits with filter type 0 (None). A .backup.png is saved first.

Usage:
  python3 fix_icon.py <path-to-icon.png>
"""

import shutil
import struct
import sys
import zlib


def fix_icon(path: str) -> None:
    backup = path.replace(".png", ".backup.png")
    shutil.copy(path, backup)
    print(f"Backup saved to {backup}")

    with open(path, "rb") as f:
        data = f.read()

    # Collect all IDAT chunks
    idat = b""
    i = 8
    while i < len(data):
        length = struct.unpack(">I", data[i : i + 4])[0]
        if data[i + 4 : i + 8] == b"IDAT":
            idat += data[i + 8 : i + 8 + length]
        i += 12 + length

    ihdr_start = data.index(b"IHDR") + 4
    width, height = struct.unpack(">II", data[ihdr_start : ihdr_start + 8])
    bpp = 4  # RGBA

    raw = bytearray(zlib.decompress(idat))
    row_size = 1 + width * bpp

    # Reverse PNG row filters to reconstruct actual pixel values
    pixels = []
    for row in range(height):
        base = row * row_size
        ftype = raw[base]
        scanline = list(raw[base + 1 : base + 1 + width * bpp])
        prev = pixels[row - 1] if row > 0 else [0] * width * bpp

        def left(idx):
            return scanline[idx - bpp] if idx >= bpp else 0

        def up(idx):
            return prev[idx]

        def paeth(a, b, c):
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            return a if pa <= pb and pa <= pc else (b if pb <= pc else c)

        if ftype == 1:
            for idx in range(width * bpp):
                scanline[idx] = (scanline[idx] + left(idx)) & 0xFF
        elif ftype == 2:
            for idx in range(width * bpp):
                scanline[idx] = (scanline[idx] + up(idx)) & 0xFF
        elif ftype == 3:
            for idx in range(width * bpp):
                scanline[idx] = (scanline[idx] + (left(idx) + up(idx)) // 2) & 0xFF
        elif ftype == 4:
            for idx in range(width * bpp):
                prev_left = prev[idx - bpp] if idx >= bpp else 0
                scanline[idx] = (scanline[idx] + paeth(left(idx), up(idx), prev_left)) & 0xFF

        pixels.append(scanline)

    # Threshold alpha and rebuild with filter type 0 (None) for all rows
    fixed = 0
    out_raw = bytearray()
    for row in range(height):
        out_raw.append(0)  # filter type: None
        for col in range(width):
            r, g, b, a = pixels[row][col * 4 : col * 4 + 4]
            new_a = 255 if a >= 128 else 0
            if new_a != a:
                fixed += 1
            out_raw += bytes([r, g, b, new_a])

    compressed = zlib.compress(bytes(out_raw), 9)

    def chunk(name: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(name + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + name + body + struct.pack(">I", crc)

    # Rebuild PNG keeping all non-IDAT/IEND chunks
    out = b"\x89PNG\r\n\x1a\n"
    i = 8
    while i < len(data):
        length = struct.unpack(">I", data[i : i + 4])[0]
        ctype = data[i + 4 : i + 8]
        if ctype not in (b"IDAT", b"IEND"):
            out += data[i : i + 12 + length]
        i += 12 + length

    out += chunk(b"IDAT", compressed)
    out += chunk(b"IEND", b"")

    with open(path, "wb") as f:
        f.write(out)

    print(f"Fixed {fixed} semi-transparent pixels in {path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path-to-icon.png>")
        sys.exit(1)
    fix_icon(sys.argv[1])
