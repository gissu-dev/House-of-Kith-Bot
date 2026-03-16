from __future__ import annotations

import io
import struct
import zlib

import discord

LIKELY_SPAMMER_USER_ID = 1337437635819339877
_BANNER_CACHE: bytes | None = None

_FONT = {
    " ": (0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00000),
    "-": (0b00000, 0b00000, 0b00000, 0b11111, 0b00000, 0b00000, 0b00000),
    ".": (0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b01100, 0b01100),
    "1": (0b00100, 0b01100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110),
    "A": (0b01110, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001),
    "D": (0b11110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b11110),
    "E": (0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b11111),
    "F": (0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b10000),
    "G": (0b01110, 0b10001, 0b10000, 0b10111, 0b10001, 0b10001, 0b01110),
    "H": (0b10001, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001),
    "I": (0b01110, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110),
    "K": (0b10001, 0b10010, 0b10100, 0b11000, 0b10100, 0b10010, 0b10001),
    "L": (0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b11111),
    "M": (0b10001, 0b11011, 0b10101, 0b10101, 0b10001, 0b10001, 0b10001),
    "N": (0b10001, 0b10001, 0b11001, 0b10101, 0b10011, 0b10001, 0b10001),
    "O": (0b01110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110),
    "P": (0b11110, 0b10001, 0b10001, 0b11110, 0b10000, 0b10000, 0b10000),
    "R": (0b11110, 0b10001, 0b10001, 0b11110, 0b10100, 0b10010, 0b10001),
    "S": (0b01111, 0b10000, 0b10000, 0b01110, 0b00001, 0b00001, 0b11110),
    "T": (0b11111, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100),
    "U": (0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110),
    "W": (0b10001, 0b10001, 0b10001, 0b10101, 0b10101, 0b10101, 0b01010),
    "Y": (0b10001, 0b10001, 0b01010, 0b00100, 0b00100, 0b00100, 0b00100),
}


def make_likely_spammer_banner_file() -> discord.File:
    return discord.File(
        io.BytesIO(_banner_bytes()),
        filename="likely_spammer_banner.png",
    )


def _banner_bytes() -> bytes:
    global _BANNER_CACHE
    if _BANNER_CACHE is None:
        _BANNER_CACHE = _build_banner()
    return _BANNER_CACHE


def _build_banner() -> bytes:
    width = 433
    height = 88
    pixels = bytearray(bytes((18, 21, 57, 255)) * (width * height))

    border = (34, 39, 91, 255)
    icon = (194, 199, 235, 255)
    body_text = (224, 228, 244, 255)
    link_text = (255, 255, 255, 255)

    _fill_rect(pixels, width, height, 0, 0, width, 1, border)
    _fill_rect(pixels, width, height, 0, height - 1, width, 1, border)
    _draw_x_icon(pixels, width, height, 15, 28, 10, icon)
    _draw_text(pixels, width, height, 52, 31, "1", link_text)

    main_text = "MESSAGE HIDDEN FROM LIKELY SPAMMER."
    _draw_text(pixels, width, height, 72, 31, main_text, body_text)

    show_text = "- SHOW"
    show_x = 72 + len(main_text) * 6 + 10
    _draw_text(pixels, width, height, show_x, 31, show_text, link_text)

    return _make_png(width, height, pixels)


def _fill_rect(
    pixels: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    rect_width: int,
    rect_height: int,
    color: tuple[int, int, int, int],
) -> None:
    left = max(0, x)
    top = max(0, y)
    right = min(width, x + rect_width)
    bottom = min(height, y + rect_height)

    for draw_y in range(top, bottom):
        row_start = (draw_y * width + left) * 4
        for draw_x in range(left, right):
            index = row_start + (draw_x - left) * 4
            pixels[index] = color[0]
            pixels[index + 1] = color[1]
            pixels[index + 2] = color[2]
            pixels[index + 3] = color[3]


def _draw_x_icon(
    pixels: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    size: int,
    color: tuple[int, int, int, int],
) -> None:
    for offset in range(size):
        _fill_rect(pixels, width, height, x + offset, y + offset, 2, 2, color)
        _fill_rect(pixels, width, height, x + size - 1 - offset, y + offset, 2, 2, color)


def _draw_text(
    pixels: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    text: str,
    color: tuple[int, int, int, int],
) -> None:
    cursor_x = x
    for character in text:
        glyph = _FONT.get(character.upper(), _FONT[" "])
        for row_index, row_bits in enumerate(glyph):
            for column_index in range(5):
                if row_bits & (1 << (4 - column_index)):
                    _fill_rect(
                        pixels,
                        width,
                        height,
                        cursor_x + column_index,
                        y + row_index,
                        1,
                        1,
                        color,
                    )
        cursor_x += 6


def _make_png(width: int, height: int, pixels: bytearray) -> bytes:
    rows = bytearray()
    stride = width * 4
    for row_index in range(height):
        start = row_index * stride
        rows.append(0)
        rows.extend(pixels[start : start + stride])

    header = struct.pack("!IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", header),
            _png_chunk(b"IDAT", zlib.compress(bytes(rows), 9)),
            _png_chunk(b"IEND", b""),
        )
    )


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return struct.pack("!I", len(payload)) + chunk_type + payload + struct.pack("!I", checksum)
