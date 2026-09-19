#!/usr/bin/env python3
"""Freeze a world so that two launches of it draw the same frame.

A performance comparison compares two launches of the game, and two launches of a live world do not draw
the same frame: the world's clock runs while a session is loaded, so the sun moves, the shadow work and
the pixels move with it, and mobs and weather come and go on their own. Restaging the save before every
run fixes the clock's starting point and nothing else - measured, the two arms of one comparison still
differed by eleven per cent in pipelines and nineteen in depth attachments, which is a different frame
rather than the switch under test.

This rewrites the world's `level.dat` so that the scene stops moving by itself:

  - `Time` is pinned, so the sun stands where it was put and a frame is lit the same way in every run;
  - the game rules that make a world change on its own are set: the daylight and weather cycles off,
    mob spawning and its patrols and traders off, random ticks off and fire spread off.

The file is gzipped NBT, and it is rewritten **losslessly**: every tag round-trips byte for byte, which
`--self-test` proves on a document carrying every tag type before anything touches a real world. Only the
values this tool means to change are changed.

Usage: freeze-world.py SAVE_DIR [--time TICKS] [--self-test]
"""
from __future__ import annotations

import gzip
import struct
import sys
from pathlib import Path

TAG_END = 0
TAG_BYTE = 1
TAG_SHORT = 2
TAG_INT = 3
TAG_LONG = 4
TAG_FLOAT = 5
TAG_DOUBLE = 6
TAG_BYTE_ARRAY = 7
TAG_STRING = 8
TAG_LIST = 9
TAG_COMPOUND = 10
TAG_INT_ARRAY = 11
TAG_LONG_ARRAY = 12

# A compound is an ordered list of entries rather than a dict, because a rewrite that reordered keys
# would still be valid NBT and would no longer be a lossless one.
Compound = list  # of (name, tag, value)


class ListTag:
    """A list, which NBT types as one item type for the whole list and an empty list as type nought."""

    def __init__(self, item_type: int, items: list) -> None:
        self.item_type = item_type
        self.items = items

    def __eq__(self, other) -> bool:
        return (isinstance(other, ListTag) and self.item_type == other.item_type
                and self.items == other.items)

    def __repr__(self) -> str:
        return f"ListTag({self.item_type}, {self.items!r})"


def read_value(data: bytes, at: int, tag: int):
    if tag == TAG_BYTE:
        return struct.unpack_from(">b", data, at)[0], at + 1
    if tag == TAG_SHORT:
        return struct.unpack_from(">h", data, at)[0], at + 2
    if tag == TAG_INT:
        return struct.unpack_from(">i", data, at)[0], at + 4
    if tag == TAG_LONG:
        return struct.unpack_from(">q", data, at)[0], at + 8
    if tag == TAG_FLOAT:
        return struct.unpack_from(">f", data, at)[0], at + 4
    if tag == TAG_DOUBLE:
        return struct.unpack_from(">d", data, at)[0], at + 8
    if tag == TAG_BYTE_ARRAY:
        length = struct.unpack_from(">i", data, at)[0]
        return bytearray(data[at + 4:at + 4 + length]), at + 4 + length
    if tag == TAG_STRING:
        length = struct.unpack_from(">H", data, at)[0]
        return data[at + 2:at + 2 + length].decode("utf-8"), at + 2 + length
    if tag == TAG_LIST:
        item_type = data[at]
        length = struct.unpack_from(">i", data, at + 1)[0]
        at += 5
        items = []
        for _ in range(length):
            item, at = read_value(data, at, item_type)
            items.append(item)
        return ListTag(item_type, items), at
    if tag == TAG_COMPOUND:
        entries: Compound = []
        while data[at] != TAG_END:
            tag_id = data[at]
            name_length = struct.unpack_from(">H", data, at + 1)[0]
            name = data[at + 3:at + 3 + name_length].decode("utf-8")
            at += 3 + name_length
            value, at = read_value(data, at, tag_id)
            entries.append((name, tag_id, value))
        return entries, at + 1
    if tag == TAG_INT_ARRAY:
        length = struct.unpack_from(">i", data, at)[0]
        return [struct.unpack_from(">i", data, at + 4 + 4 * i)[0] for i in range(length)], at + 4 + 4 * length
    if tag == TAG_LONG_ARRAY:
        length = struct.unpack_from(">i", data, at)[0]
        return [struct.unpack_from(">q", data, at + 4 + 8 * i)[0] for i in range(length)], at + 4 + 8 * length
    raise ValueError(f"unknown tag type {tag}")


def write_value(tag: int, value) -> bytes:
    if tag == TAG_BYTE:
        return struct.pack(">b", value)
    if tag == TAG_SHORT:
        return struct.pack(">h", value)
    if tag == TAG_INT:
        return struct.pack(">i", value)
    if tag == TAG_LONG:
        return struct.pack(">q", value)
    if tag == TAG_FLOAT:
        return struct.pack(">f", value)
    if tag == TAG_DOUBLE:
        return struct.pack(">d", value)
    if tag == TAG_BYTE_ARRAY:
        return struct.pack(">i", len(value)) + bytes(value)
    if tag == TAG_STRING:
        encoded = value.encode("utf-8")
        return struct.pack(">H", len(encoded)) + encoded
    if tag == TAG_LIST:
        out = bytes([value.item_type]) + struct.pack(">i", len(value.items))
        return out + b"".join(write_value(value.item_type, item) for item in value.items)
    if tag == TAG_COMPOUND:
        out = bytearray()
        for name, tag_id, entry in value:
            encoded = name.encode("utf-8")
            out += bytes([tag_id]) + struct.pack(">H", len(encoded)) + encoded + write_value(tag_id, entry)
        return bytes(out) + bytes([TAG_END])
    if tag == TAG_INT_ARRAY:
        return struct.pack(">i", len(value)) + b"".join(struct.pack(">i", item) for item in value)
    if tag == TAG_LONG_ARRAY:
        return struct.pack(">i", len(value)) + b"".join(struct.pack(">q", item) for item in value)
    raise ValueError(f"unknown tag type {tag}")


def load_level_dat(path: Path) -> Compound:
    data = gzip.decompress(path.read_bytes())
    tag = data[0]
    if tag != TAG_COMPOUND:
        raise ValueError(f"{path} does not begin with a compound")
    name_length = struct.unpack_from(">H", data, 1)[0]
    root, at = read_value(data, 3 + name_length, TAG_COMPOUND)
    if at != len(data):
        raise ValueError(f"{path} has {len(data) - at} trailing bytes")
    return root


def save_level_dat(path: Path, root: Compound) -> None:
    out = bytes([TAG_COMPOUND]) + struct.pack(">H", 0) + write_value(TAG_COMPOUND, root)
    path.write_bytes(gzip.compress(out, mtime=0))


def entry(compound: Compound, name: str):
    for name_at, tag, value in compound:
        if name_at == name:
            return tag, value
    return None, None


def set_entry(compound: Compound, name: str, tag: int, value) -> None:
    for index, (name_at, _, _) in enumerate(compound):
        if name_at == name:
            compound[index] = (name, tag, value)
            return
    compound.append((name, tag, value))


# What makes a world change on its own. Rain and thunder move the sky and the light; mob spawning puts
# entities into passes that attach depth, which is exactly the difference that was measured between two
# runs of one comparison; random ticks grow and decay blocks, and fire spreads.
GAME_RULES = {
    "doDaylightCycle": "false",
    "doWeatherCycle": "false",
    "doMobSpawning": "false",
    "doPatrolSpawning": "false",
    "doTraderSpawning": "false",
    "doInsomnia": "false",
    "doFireTick": "false",
    "doMobLoot": "false",
    "randomTickSpeed": "0",
}

# Noon, which is the time of day a screenshot is easiest to read and the one the sun stands still at.
NOON = 6000


def freeze(root: Compound, time: int) -> Compound:
    data_tag, data = entry(root, "Data")
    if data_tag != TAG_COMPOUND:
        raise ValueError("this level.dat has no Data compound")

    set_entry(data, "Time", TAG_LONG, time)

    rules_tag, rules = entry(data, "GameRules")
    if rules_tag != TAG_COMPOUND:
        rules = []
        set_entry(data, "GameRules", TAG_COMPOUND, rules)
    for name, value in GAME_RULES.items():
        set_entry(rules, name, TAG_STRING, value)

    return root


def self_test() -> None:
    """Prove the reader and the writer are inverses before either touches a world."""
    document: Compound = [
        ("byte", TAG_BYTE, -7),
        ("short", TAG_SHORT, -300),
        ("int", TAG_INT, -70000),
        ("long", TAG_LONG, -9000000000),
        ("float", TAG_FLOAT, 0.5),
        ("double", TAG_DOUBLE, -2.25),
        ("byteArray", TAG_BYTE_ARRAY, bytearray([0, 1, 255, 128])),
        ("string", TAG_STRING, "a string with an accent: e"),
        ("intArray", TAG_INT_ARRAY, [1, -2, 3]),
        ("longArray", TAG_LONG_ARRAY, [1, -2, 3]),
        ("emptyList", TAG_LIST, ListTag(TAG_END, [])),
        ("listOfCompound", TAG_LIST, ListTag(TAG_COMPOUND, [[("a", TAG_INT, 1)], [("b", TAG_INT, 2)]])),
        ("listOfString", TAG_LIST, ListTag(TAG_STRING, ["x", "y"])),
        ("nested", TAG_COMPOUND, [("deep", TAG_COMPOUND, [("deeper", TAG_INT, 5)])]),
    ]
    header = bytes([TAG_COMPOUND]) + struct.pack(">H", 4) + b"root"
    encoded = header + write_value(TAG_COMPOUND, document)
    parsed, at = read_value(encoded, len(header), TAG_COMPOUND)
    if at != len(encoded):
        raise SystemExit("self-test: the reader stopped before the document did")
    if write_value(TAG_COMPOUND, parsed) != encoded[len(header):]:
        raise SystemExit("self-test: a document does not round-trip byte for byte")
    if parsed != document:
        raise SystemExit("self-test: a document does not round-trip value for value")

    # On a document shaped like a world: the time is set, the rules this tool names are set, a rule that
    # was already there is kept, and nothing else in the compound moves.
    world: Compound = [
        ("Data", TAG_COMPOUND, [
            ("Time", TAG_LONG, 1234),
            ("LevelName", TAG_STRING, "a world"),
            ("GameRules", TAG_COMPOUND, [("keepThis", TAG_STRING, "true")]),
        ]),
    ]
    frozen_world = freeze(world, NOON)
    _, frozen_data = entry(frozen_world, "Data")
    if entry(frozen_data, "Time") != (TAG_LONG, NOON):
        raise SystemExit("self-test: the world's time was not pinned")
    kept = [(name, tag, value) for name, tag, value in frozen_data if name != "GameRules"]
    if kept != [("Time", TAG_LONG, NOON), ("LevelName", TAG_STRING, "a world")]:
        raise SystemExit("self-test: an unrelated entry was disturbed")
    _, rules = entry(frozen_data, "GameRules")
    rules_by_name = dict((name, value) for name, _, value in rules)
    if rules_by_name.get("keepThis") != "true":
        raise SystemExit("self-test: a game rule that was already set was dropped")
    for name, value in GAME_RULES.items():
        if rules_by_name.get(name) != value:
            raise SystemExit(f"self-test: {name} was not set")

    print("freeze-world self-test: PASS")


def main() -> int:
    args = sys.argv[1:]
    if "--self-test" in args:
        self_test()
        return 0
    if not args:
        print(__doc__.strip().split("Usage: ")[1], file=sys.stderr)
        return 2

    save = Path(args[0])
    time = NOON
    if "--time" in args:
        time = int(args[args.index("--time") + 1])

    level = save / "level.dat"
    if not level.is_file():
        print(f"No level.dat under {save}", file=sys.stderr)
        return 2

    root = load_level_dat(level)
    before = level.read_bytes()
    save_level_dat(level, freeze(root, time))
    after = level.read_bytes()
    if before == after:
        print(f"{save} was already frozen", file=sys.stderr)
    else:
        print(f"Froze {save}: time pinned to {time}, {len(GAME_RULES)} game rules set")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
