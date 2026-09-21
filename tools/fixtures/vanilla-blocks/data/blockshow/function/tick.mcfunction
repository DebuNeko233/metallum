# Block entities of several render families, in front of the camera, placed through a marker.
#
# The entity fixture covers what an *entity* draws. Vanilla's own frame also draws what a block's own renderer
# draws - a chest's model, a bell, a banner's cloth, a shulker box, an enchanting table's book - and those are
# neither blocks in the terrain nor entities in the entity stores, so no scene this harness had measured before
# contained one.
#
# **How these are placed is three measurements old, and the first two ways did not work.** The first version
# guarded its placements on `unless block <position>` and every one of them was silently skipped: the fixture's
# own liveness line shows the function ran 1138 times in a sixty-frame arm and not one placement fired. A
# four-way diagnostic then separated the parts - `if block ~ ~ ~ minecraft:air` never matches (not at the
# server's position and not at the player's), while `if block <position> minecraft:chest` matches as soon as
# something has *placed* a block there. What a block predicate reads is a position that a command has made
# real, so this fixture places first and proves afterwards, and it proves with an entity:
#
#   a marker entity is summoned once, with a tag        (the `unless entity` guard the entity fixture uses)
#   the say fires when that marker is absent            (so it is one line per type per session)
#   the block is placed at the marker, every tick       (`setblock ~ ~ ~` at an entity's own position, which
#                                                        is idempotent and cannot be skipped)
#
# The block states are the defaults and the NBT is empty, so nothing here can differ between two launches but
# the tick a screenshot lands on - and a chest, a bell, a banner and a shulker box do not change with it.
say showcase: the block fixture ran
execute unless entity @e[type=minecraft:marker,tag=showcase_chest] run say showcase: placed the chest
execute at @a unless entity @e[type=minecraft:marker,tag=showcase_chest] run summon minecraft:marker ^1 ^1 ^4 {Tags:["showcase_chest"]}
execute at @e[type=minecraft:marker,tag=showcase_chest] run setblock ~ ~ ~ minecraft:chest replace
execute unless entity @e[type=minecraft:marker,tag=showcase_bell] run say showcase: placed the bell
execute at @a unless entity @e[type=minecraft:marker,tag=showcase_bell] run summon minecraft:marker ^-1 ^1 ^4 {Tags:["showcase_bell"]}
execute at @e[type=minecraft:marker,tag=showcase_bell] run setblock ~ ~ ~ minecraft:bell replace
execute unless entity @e[type=minecraft:marker,tag=showcase_banner] run say showcase: placed the banner
execute at @a unless entity @e[type=minecraft:marker,tag=showcase_banner] run summon minecraft:marker ^0 ^1 ^6 {Tags:["showcase_banner"]}
execute at @e[type=minecraft:marker,tag=showcase_banner] run setblock ~ ~ ~ minecraft:white_banner replace
execute unless entity @e[type=minecraft:marker,tag=showcase_shulker] run say showcase: placed the shulker_box
execute at @a unless entity @e[type=minecraft:marker,tag=showcase_shulker] run summon minecraft:marker ^2 ^1 ^4 {Tags:["showcase_shulker"]}
execute at @e[type=minecraft:marker,tag=showcase_shulker] run setblock ~ ~ ~ minecraft:shulker_box replace
execute unless entity @e[type=minecraft:marker,tag=showcase_enchant] run say showcase: placed the enchanting_table
execute at @a unless entity @e[type=minecraft:marker,tag=showcase_enchant] run summon minecraft:marker ^-2 ^1 ^4 {Tags:["showcase_enchant"]}
execute at @e[type=minecraft:marker,tag=showcase_enchant] run setblock ~ ~ ~ minecraft:enchanting_table replace
