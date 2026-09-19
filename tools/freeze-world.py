#!/usr/bin/env python3
"""Freeze a world so that two launches of it draw the same frame.

A performance comparison compares two launches of the game, and two launches of a live world do not draw
the same frame: the world's clock runs while a session is loaded, so the sun moves, the shadow work and
the pixels move with it, and mobs and weather come and go on their own. Restaging the save before every
run fixes the clock's starting point and nothing else - measured, the two arms of one comparison still
differed by eleven per cent in pipelines and nineteen in depth attachments, which is a different frame
rather than the switch under test.

This rewrites the world's `level.dat` so that the scene stops moving by itself:

  - the dimension's clock is pinned, in `data/minecraft/world_clocks.dat`, so every run starts from
    the same point of the day and the sun does not move while one is counted - and it is pinned away
    from the boundaries vanilla changes what it draws at;
  - the game rules that make a world change on its own are set, in
    `data/minecraft/game_rules.dat`: the daylight and weather cycles off, mob spawning and its patrols
    and traders and phantoms off, random ticks off and fire spread off - and under `--still-life`, the
    entities the world already holds are taken out of it;
  - under `--spectator`, the player is put into spectator mode, which is the last thing that moves: a
    player draws their own entity and their hand, and the packs draw both, so two runs of one
    configuration still differ in what is inside the frame's passes even when the pass set repeats.

The parts of a world this rewrites are not all in `level.dat` any more, and that is worth stating
because writing only `level.dat` looks like it works and does nothing. Measured on a save this game
wrote itself: the day-time clock is `data/minecraft/world_clocks.dat`'s `minecraft:overworld.total_ticks`,
the weather is `data/minecraft/weather.dat`, and the rules are `data/minecraft/game_rules.dat` under
names a command never says - `doDaylightCycle` is `minecraft:advance_time`, `doMobSpawning` is
`minecraft:spawn_mobs` - so a run that wrote the command names into `level.dat` froze nothing: both
spellings were absent from the save the client left behind and the clock had advanced 562 ticks across a
single run. `level.dat`'s own `Time` is the world's age rather than its time of day, and the writes there
are kept for an older schema's benefit and say so when the three files are missing. The entity store is the part a rule cannot
reach - `doMobSpawning` stops new mobs and does nothing about the ones standing there, and a single extra
entity draws a family's pass (measured: `cutout_cull entity` drawn in one run of one configuration and
not the other, which moves the depth attachments by a tenth and the counted bytes by six per cent).

The file is gzipped NBT, and it is rewritten **losslessly**: every tag round-trips byte for byte, which
`--self-test` proves on a document carrying every tag type before anything touches a real world. Only the
values this tool means to change are changed.

Usage: freeze-world.py SAVE_DIR [--time TICKS] [--still-life] [--spectator]
                             [--at X,Y,Z] [--yaw DEG] [--pitch DEG] [--self-test]
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
# The rules that let a world move on its own, under the names *this* schema keeps them in. They are
# not the names a command uses and not the names an older save holds: game rules moved out of
# `level.dat` into `data/minecraft/game_rules.dat` and were renamed with a namespace, so what a
# command calls `doDaylightCycle` is `minecraft:advance_time` here and `doMobSpawning` is
# `minecraft:spawn_mobs`. Writing the old names costs nothing and does nothing - the game drops a
# compound it does not recognise, measured: both spellings were absent from the save the client left
# behind, and the world's clock had advanced 562 ticks across one run.
FROZEN_RULES = {
    "minecraft:advance_time": (TAG_BYTE, 0),
    "minecraft:advance_weather": (TAG_BYTE, 0),
    "minecraft:spawn_mobs": (TAG_BYTE, 0),
    "minecraft:spawn_monsters": (TAG_BYTE, 0),
    "minecraft:spawn_patrols": (TAG_BYTE, 0),
    "minecraft:spawn_wandering_traders": (TAG_BYTE, 0),
    "minecraft:spawn_phantoms": (TAG_BYTE, 0),
    "minecraft:random_tick_speed": (TAG_INT, 0),
    "minecraft:fire_spread_radius_around_player": (TAG_INT, 0),
}

# Where the game keeps the parts of a world that are not in `level.dat`: the day-time clock, the
# weather it was left holding, and the rules.
WORLD_DATA = ("data", "minecraft")

# The clock a run starts from, per dimension. The overworld's is the one a scene is lit by; the end's
# is left alone because nothing this tool measures is drawn there.
OVERWORLD_CLOCK = "minecraft:overworld"

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

# Mid-morning, and deliberately not noon: noon is exactly the boundary vanilla switches the sunrise band
# off and the sunset band on at. A comparison whose two runs straddled
# that boundary drew a different number of sky passes, measured: 21 passes against 20, and eleven
# per cent in pipelines. Four thousand ticks leaves a whole minute of world time on either side of any
# day-phase boundary a run could cross.
FROZEN_TIME = 4000

# Spectator, which is what a player who is only watching a scene should be: no hand, no body, and
# therefore nothing drawn inside a frame that varies between two launches of one configuration.
SPECTATOR = 3
NOON = FROZEN_TIME


def freeze(root: Compound, time: int) -> Compound:
    data_tag, data = entry(root, "Data")
    if data_tag != TAG_COMPOUND:
        raise ValueError("this level.dat has no Data compound")

    set_entry(data, "Time", TAG_LONG, time)

    # Under both spellings. The schema this save was written with is mixed - `difficulty_settings` is
    # snake_case where most of the compound is not - and a run of this tool checks which key the game
    # keeps by reading the save the client leaves behind. Writing a compound the game ignores costs
    # nothing; writing only the wrong one costs the whole fixture.
    quiet_weather(root)

    for key in ("GameRules", "game_rules"):
        rules_tag, rules = entry(data, key)
        if rules_tag != TAG_COMPOUND:
            rules = []
            set_entry(data, key, TAG_COMPOUND, rules)
        for name, value in GAME_RULES.items():
            set_entry(rules, name, TAG_STRING, value)

    return root


def entity_stores(save: Path) -> list:
    """The entity region directories of every dimension under a save, which is where the mobs live.

    The player is not among them: a player's data is `players/`, beside the dimensions rather than inside
    one, which is why taking these out leaves a world that can still be joined and played in.
    """
    dimensions = save / "dimensions"
    if not dimensions.is_dir():
        return []
    return sorted(path for path in dimensions.glob("*/*/entities") if path.is_dir())


def still_life(save: Path, dry_run: bool = False) -> list:
    """Take the world's entities out of the copy, so that a run has nothing that moves on its own.

    Refuses any path that is not inside the save it was handed, which is the one thing this must never
    get wrong: it deletes directories, and the save is a copy the harness made for a measurement. What
    it returns is the stores' paths relative to the save, so that a caller can print them and a test can
    compare them without either having to know how a temporary directory is spelled on this platform.
    """
    import shutil

    inside = save.resolve()
    removed = []
    for store in entity_stores(save):
        if inside not in store.resolve().parents:
            raise SystemExit(f"refusing to remove {store}: it is not inside {save}")
        removed.append(str(store.relative_to(save)))
        if not dry_run:
            shutil.rmtree(store)
    return removed


def player_files(save: Path) -> list:
    """The player records of a save, which is where a player's own game type is written."""
    players = save / "players" / "data"
    if not players.is_dir():
        return []
    return sorted(players.glob("*.dat"))


def spectate_world(root: Compound) -> bool:
    """Sets the world's default game type, answering whether there was a world to set."""
    data_tag, data = entry(root, "Data")
    if data_tag != TAG_COMPOUND:
        return False

    set_entry(data, "GameType", TAG_INT, SPECTATOR)
    return True


def spectate_player(root: Compound) -> None:
    """Sets one player record's own game type, which is the one that decides what they are."""
    set_entry(root, "playerGameType", TAG_INT, SPECTATOR)


def spectator(save: Path) -> int:
    """Puts the world and every player of it into spectator mode, and answers how many it changed.

    A player's game type is stored twice: once as the world's default and once in the player's own
    record, and it is the second that decides what a player is when a world is opened. Both are written,
    because a world set to spectator that hands back a creative player is a hand in every frame.
    """
    changed = 0
    level = save / "level.dat"
    if level.is_file():
        root = load_level_dat(level)
        if spectate_world(root):
            save_level_dat(level, root)
            changed += 1

    for record in player_files(save):
        root = load_level_dat(record)
        spectate_player(root)
        save_level_dat(record, root)
        changed += 1

    return changed


def place_player(root: Compound, position, yaw, pitch) -> bool:
    """Puts one player record where and how a comparison should look from.

    A frame repeats only if it is drawn from the same place at the same angle, and a player record
    says wherever that player happened to stand when the world was saved. Aiming is therefore part of
    freezing a scene rather than a separate trick: the same world holds a nether portal's animated
    texture from one angle and open sky from another, and a comparison that means to judge pixels has
    to be able to choose.
    """
    changed = False
    if position is not None:
        set_entry(root, "Pos", TAG_LIST, ListTag(TAG_DOUBLE, [float(axis) for axis in position]))
        changed = True

    rotation_tag, rotation = entry(root, "Rotation")
    current = list(rotation.items) if rotation_tag == TAG_LIST else [0.0, 0.0]
    if yaw is not None:
        current[0] = float(yaw)
        changed = True
    if pitch is not None:
        current[1] = float(pitch)
        changed = True
    if changed:
        set_entry(root, "Rotation", TAG_LIST, ListTag(TAG_FLOAT, current))

    return changed


def aim(save: Path, position, yaw, pitch) -> int:
    """Places every player record of a save, and answers how many it changed."""
    changed = 0
    for record in player_files(save):
        root = load_level_dat(record)
        if place_player(root, position, yaw, pitch):
            save_level_dat(record, root)
            changed += 1

    return changed


def world_data_file(save: Path, name: str) -> Path:
    """One of the per-world data files this schema keeps beside `level.dat`."""
    return save.joinpath(*WORLD_DATA, f"{name}.dat")


def freeze_rules(path: Path) -> int:
    """Sets the rules that let a world move on its own, and answers how many it wrote."""
    if not path.is_file():
        return 0

    root = load_level_dat(path)
    tag, data = entry(root, "data")
    if tag != TAG_COMPOUND:
        data = []
        set_entry(root, "data", TAG_COMPOUND, data)

    for name, (rule_tag, value) in FROZEN_RULES.items():
        set_entry(data, name, rule_tag, value)
    save_level_dat(path, root)

    return len(FROZEN_RULES)


def freeze_clock(path: Path, time: int) -> bool:
    """Pins the dimension's own clock, which is what a scene is lit by."""
    if not path.is_file():
        return False

    root = load_level_dat(path)
    tag, data = entry(root, "data")
    if tag != TAG_COMPOUND:
        return False
    clock_tag, clock = entry(data, OVERWORLD_CLOCK)
    if clock_tag != TAG_COMPOUND:
        return False

    set_entry(clock, "total_ticks", TAG_LONG, time)
    save_level_dat(path, root)

    return True


def freeze_weather_file(path: Path) -> bool:
    """Stops the rain and the thunder the save was left holding, in the file this schema keeps."""
    if not path.is_file():
        return False

    root = load_level_dat(path)
    tag, data = entry(root, "data")
    if tag != TAG_COMPOUND:
        return False

    for key in ("raining", "thundering"):
        set_entry(data, key, TAG_BYTE, 0)
    save_level_dat(path, root)

    return True


def freeze_world_data(save: Path, time: int) -> tuple:
    """Freezes the clock, the weather and the rules where this schema actually keeps them.

    The three answers are worth separating: a save written by an older schema has none of these
    files, and a fixture that silently froze nothing is worse than one that says so.
    """
    return (freeze_clock(world_data_file(save, "world_clocks"), time),
            freeze_weather_file(world_data_file(save, "weather")),
            freeze_rules(world_data_file(save, "game_rules")))


def quiet_weather(root: Compound) -> bool:
    """Stops the rain and the thunder a save was left holding.

    The rule that stops the weather cycle stops it *changing* and does nothing about what it already
    is, so a world saved in a storm keeps raining for the whole of a measurement, and rain is drawn
    and animated in every frame of one.
    """
    data_tag, data = entry(root, "Data")
    if data_tag != TAG_COMPOUND:
        return False

    for key in ("raining", "thundering"):
        set_entry(data, key, TAG_BYTE, 0)
    return True


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
            ("raining", TAG_BYTE, 1),
            ("thundering", TAG_BYTE, 1),
            ("GameRules", TAG_COMPOUND, [("keepThis", TAG_STRING, "true")]),
        ]),
    ]
    frozen_world = freeze(world, NOON)
    _, frozen_data = entry(frozen_world, "Data")
    if entry(frozen_data, "Time") != (TAG_LONG, NOON):
        raise SystemExit("self-test: the world's time was not pinned")
    kept = [(name, tag, value) for name, tag, value in frozen_data
            if name not in ("GameRules", "game_rules", "raining", "thundering")]
    if kept != [("Time", TAG_LONG, NOON), ("LevelName", TAG_STRING, "a world")]:
        raise SystemExit("self-test: an unrelated entry was disturbed")
    for key in ("raining", "thundering"):
        if entry(frozen_data, key) != (TAG_BYTE, 0):
            raise SystemExit(f"self-test: a storm the save was holding was left in it: {key}")

    player: Compound = [
        ("Pos", TAG_LIST, ListTag(TAG_DOUBLE, [1.0, 2.0, 3.0])),
        ("Rotation", TAG_LIST, ListTag(TAG_FLOAT, [10.0, 20.0])),
        ("playerGameType", TAG_INT, 1),
    ]
    if not place_player(player, (4.0, 5.0, 6.0), 90.0, -30.0):
        raise SystemExit("self-test: placing a player reported no change")
    if entry(player, "Pos") != (TAG_LIST, ListTag(TAG_DOUBLE, [4.0, 5.0, 6.0])):
        raise SystemExit("self-test: the player's position was not written")
    if entry(player, "Rotation") != (TAG_LIST, ListTag(TAG_FLOAT, [90.0, -30.0])):
        raise SystemExit("self-test: the player's angle was not written")
    if place_player([("Nothing", TAG_INT, 1)], None, None, None):
        raise SystemExit("self-test: placing a player changed something it was not asked to")
    for key in ("GameRules", "game_rules"):
        tag, rules = entry(frozen_data, key)
        if tag != TAG_COMPOUND:
            raise SystemExit(f"self-test: {key} was not written")
        rules_by_name = dict((name, value) for name, _, value in rules)
        # The document the tool was handed had one rule under GameRules and nothing under game_rules,
        # and neither may lose what was there.
        if key == "GameRules" and rules_by_name.get("keepThis") != "true":
            raise SystemExit("self-test: a game rule that was already set was dropped")
        for name, value in GAME_RULES.items():
            if rules_by_name.get(name) != value:
                raise SystemExit(f"self-test: {name} was not set in {key}")

    # Spectator mode is written in two places, and a world set without its player set is a hand in every
    # frame: the check is that both moved and that nothing else did.
    world_with_type: Compound = [("Data", TAG_COMPOUND, [("LevelName", TAG_STRING, "a world")])]
    if not spectate_world(world_with_type):
        raise SystemExit("self-test: a world with no data compound was reported as set")
    _, data = entry(world_with_type, "Data")
    if entry(data, "GameType") != (TAG_INT, SPECTATOR):
        raise SystemExit("self-test: the world's own game type was not set")
    if entry(data, "LevelName") != (TAG_STRING, "a world"):
        raise SystemExit("self-test: setting the world's game type disturbed the rest of it")

    player: Compound = [("playerGameType", TAG_INT, 1), ("Health", TAG_FLOAT, 20.0),
                        ("abilities", TAG_COMPOUND, [("flying", TAG_BYTE, 1)])]
    spectate_player(player)
    if entry(player, "playerGameType") != (TAG_INT, SPECTATOR):
        raise SystemExit("self-test: a player's game type was not set")
    if entry(player, "Health") != (TAG_FLOAT, 20.0) or entry(player, "abilities") is None:
        raise SystemExit("self-test: setting a game type disturbed the rest of the player record")

    # The still-life step removes directories, so what it would remove is computed and checked rather
    # than trusted: a path outside the save it was handed is refused, and the shape it looks for is the
    # one this version of the game writes.
    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        save = Path(scratch) / "a world"
        (save / "dimensions/minecraft/overworld/entities").mkdir(parents=True)
        (save / "dimensions/minecraft/the_nether/entities").mkdir(parents=True)
        (save / "players/data").mkdir(parents=True)
        (save / "level.dat").write_bytes(b"not a real save")
        found = [str(path.relative_to(save)) for path in entity_stores(save)]
        if found != ["dimensions/minecraft/overworld/entities",
                     "dimensions/minecraft/the_nether/entities"]:
            raise SystemExit(f"self-test: the entity stores are not found where they live: {found}")
        if still_life(save, dry_run=True) != found:
            raise SystemExit(f"self-test: the dry run does not name the stores it would remove: {found}")
        if not (save / "players/data").is_dir():
            raise SystemExit("self-test: the player's own data was taken for an entity store")

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
    still = "--still-life" in args
    spectate = "--spectator" in args
    position = None
    if "--at" in args:
        position = [float(axis) for axis in args[args.index("--at") + 1].split(",")]
        if len(position) != 3:
            print("--at wants three numbers, X,Y,Z", file=sys.stderr)
            return 2
    yaw = float(args[args.index("--yaw") + 1]) if "--yaw" in args else None
    pitch = float(args[args.index("--pitch") + 1]) if "--pitch" in args else None

    level = save / "level.dat"
    if not level.is_file():
        print(f"No level.dat under {save}", file=sys.stderr)
        return 2

    root = load_level_dat(level)
    before = level.read_bytes()
    save_level_dat(level, freeze(root, time))
    after = level.read_bytes()
    clock, weather, rules = freeze_world_data(save, time)
    if before == after and clock and weather:
        print(f"{save} was already frozen", file=sys.stderr)
    else:
        print(f"Froze {save}: the overworld clock pinned to {time}"
              + (", the rules set" if rules else ", and no rules file to set"))

    absent = [name for name, present in (("clock", clock), ("weather", weather), ("rules", rules))
              if not present]
    if absent:
        print(f"  no {' or '.join(absent)} under data/minecraft, so this save is an older schema and "
              "only level.dat was written", file=sys.stderr)

    if still:
        removed = still_life(save)
        print(f"Took the entities out of {save}: {len(removed)} store(s)"
              + (f" - {', '.join(removed)}" if removed else ""))

    if spectate:
        print(f"Put {spectator(save)} record(s) of {save} into spectator mode")

    if position is not None or yaw is not None or pitch is not None:
        placed = aim(save, position, yaw, pitch)
        where = "nowhere" if position is None else ",".join(f"{axis:g}" for axis in position)
        print(f"Aimed {placed} record(s) of {save} at {where} yaw {yaw} pitch {pitch}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
