# The game's own particle types, emitted around whoever is looking, every tick.
#
# A measurement of vanilla's rendering needs vanilla's particles in the frame, and the harness cannot press a
# key or break a block. A world datapack's tick function is the one deterministic way to put them there: it runs
# on the server's tick whatever the client is doing, at the camera rather than at a fixed point, and it emits
# the same counts in every run of a comparison.
#
# One command per render family rather than per id, because what a particle costs depends on how it is drawn -
# a lit billboard, an unlit one, a textured quad, an item model - and a scene that only had one family would
# measure that family.
#
# **The forms of the particles that take options are the options-map ones, and that is measured rather than
# remembered**: a first version wrote `particle minecraft:dust 1.0 0.4 0.1 1.5 ...`, which this version refuses
# with "Can't parse particle options: No key scale in MapLike[{}]; No key color in MapLike[{}]" - and the
# refusal is whole-function, so the fixture staged, loaded and emitted nothing at all.
execute at @a run particle minecraft:flame ~ ~1.5 ~ 1.0 1.0 1.0 0.02 12
execute at @a run particle minecraft:soul_fire_flame ~ ~1.5 ~ 1.0 1.0 1.0 0.02 12
execute at @a run particle minecraft:smoke ~ ~1.5 ~ 1.0 1.0 1.0 0.01 12
execute at @a run particle minecraft:campfire_cosy_smoke ~ ~1.5 ~ 1.0 1.0 1.0 0.01 12
execute at @a run particle minecraft:crit ~ ~1.5 ~ 1.0 1.0 1.0 0.05 12
execute at @a run particle minecraft:enchanted_hit ~ ~1.5 ~ 1.0 1.0 1.0 0.05 12
execute at @a run particle minecraft:end_rod ~ ~1.5 ~ 1.0 1.0 1.0 0.02 12
execute at @a run particle minecraft:cloud ~ ~1.5 ~ 1.5 1.0 1.5 0.01 12
execute at @a run particle minecraft:poof ~ ~1.5 ~ 1.0 1.0 1.0 0.02 12
execute at @a run particle minecraft:heart ~ ~1.5 ~ 1.0 1.0 1.0 0.02 12
execute at @a run particle minecraft:note ~ ~1.5 ~ 1.0 1.0 1.0 0.02 12
execute at @a run particle minecraft:lava ~ ~1.5 ~ 1.0 1.0 1.0 0.01 12
execute at @a run particle minecraft:snowflake ~ ~1.5 ~ 1.0 1.0 1.0 0.02 12
execute at @a run particle minecraft:dripping_water ~ ~1.5 ~ 1.0 1.0 1.0 0.02 12
execute at @a run particle minecraft:totem_of_undying ~ ~1.5 ~ 1.0 1.0 1.0 0.02 12
execute at @a run particle minecraft:dust{color:[1.0,0.4,0.1],scale:1.5} ~ ~1.5 ~ 1.0 1.0 1.0 0.02 12
execute at @a run particle minecraft:dust_color_transition{from_color:[0.2,0.6,1.0],to_color:[1.0,0.2,0.2],scale:1.5} ~ ~1.5 ~ 1.0 1.0 1.0 0.02 12
execute at @a run particle minecraft:block{block_state:"minecraft:stone"} ~ ~1.5 ~ 1.0 1.0 1.0 0.02 12
execute at @a run particle minecraft:item{item:"minecraft:apple"} ~ ~1.5 ~ 1.0 1.0 1.0 0.02 12
execute at @a run particle minecraft:falling_dust{block_state:"minecraft:sand"} ~ ~1.5 ~ 1.0 1.0 1.0 0.02 12
