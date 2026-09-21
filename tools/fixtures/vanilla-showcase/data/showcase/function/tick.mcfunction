# The game's own particle types, in a grid in front of whoever is looking, every tick.
#
# A measurement of vanilla's rendering needs vanilla's particles in the frame - and it needs them *still*,
# because a picture verdict compares two launches and this harness photographs one frame of each. The first
# version of this function emitted each type with a spread and a speed, which is what a player sees and what a
# cross-launch comparison cannot read: with rain and these particles in the frame, two arms of the *reference
# implementation* differed in 68% of pixels and said nothing about the path.
#
# So every particle here is emitted with `0 0 0 0 1` after its position: no spread box, no speed, one particle.
# Its position is exact, its velocity is zero, and the field of them is the same in every run - the pixel
# difference between two arms is then the renderer's and not the animation's.
#
# The positions are local coordinates (`^left ^up ^forward`), so the grid is in front of the camera rather than
# at the world's spawn, and each of the game's particle render families has a cell of its own: lit billboards,
# unlit ones, textured quads, item and block models, and the option-carrying forms in their current
# options-map spelling (the positional spelling is refused whole-function by this version, which is how the
# first version of this file came to emit nothing at all while every log line said it had been staged).
execute at @a run particle minecraft:flame ^-2 ^0 ^3 0 0 0 0 1
execute at @a run particle minecraft:soul_fire_flame ^-1 ^0 ^3 0 0 0 0 1
execute at @a run particle minecraft:smoke ^0 ^0 ^3 0 0 0 0 1
execute at @a run particle minecraft:campfire_cosy_smoke ^1 ^0 ^3 0 0 0 0 1
execute at @a run particle minecraft:campfire_signal_smoke ^2 ^0 ^3 0 0 0 0 1
execute at @a run particle minecraft:crit ^-2 ^1 ^3 0 0 0 0 1
execute at @a run particle minecraft:enchanted_hit ^-1 ^1 ^3 0 0 0 0 1
execute at @a run particle minecraft:end_rod ^0 ^1 ^3 0 0 0 0 1
execute at @a run particle minecraft:cloud ^1 ^1 ^3 0 0 0 0 1
execute at @a run particle minecraft:poof ^2 ^1 ^3 0 0 0 0 1
execute at @a run particle minecraft:heart ^-2 ^2 ^3 0 0 0 0 1
execute at @a run particle minecraft:note ^-1 ^2 ^3 0 0 0 0 1
execute at @a run particle minecraft:lava ^0 ^2 ^3 0 0 0 0 1
execute at @a run particle minecraft:snowflake ^1 ^2 ^3 0 0 0 0 1
execute at @a run particle minecraft:dripping_water ^2 ^2 ^3 0 0 0 0 1
execute at @a run particle minecraft:totem_of_undying ^-2 ^3 ^3 0 0 0 0 1
execute at @a run particle minecraft:dust{color:[1.0,0.4,0.1],scale:1.5} ^-1 ^3 ^3 0 0 0 0 1
execute at @a run particle minecraft:dust_color_transition{from_color:[0.2,0.6,1.0],to_color:[1.0,0.2,0.2],scale:1.5} ^0 ^3 ^3 0 0 0 0 1
execute at @a run particle minecraft:block{block_state:"minecraft:stone"} ^1 ^3 ^3 0 0 0 0 1
execute at @a run particle minecraft:item{item:"minecraft:apple"} ^2 ^3 ^3 0 0 0 0 1
execute at @a run particle minecraft:falling_dust{block_state:"minecraft:sand"} ^3 ^3 ^3 0 0 0 0 1
