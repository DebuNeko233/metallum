# Entities of several render families, in front of the camera, and they stay exactly where they are put.
#
# Vanilla's own frame is not only terrain, clouds and particles: it is also what a mob, an item and an armour
# stand draw, and the world this harness stages has no entities of its own to draw (measured: with
# `--keep-entities` the frame's passes a frame, pipeline identities and depth attachments are the still-life
# scene's to the digit, so nothing was there). A world with no entities cannot answer "does this path draw one".
#
# **They are placed once, and each of the four tags is one of the ways a placement can stop being one.** The
# guard is `unless entity`, which places them on the first tick a session runs and does nothing after - and the
# first version of this fixture was measured logging "placed the pig" and "placed the cow" *every four to five
# seconds*, so a session held a number of entities that depended on how long it ran:
#
#   NoAI                 stops the mob's own movement and its look control, so its pose is the same every launch
#   NoGravity            stops it falling to the ground - the summons are at the camera's own height, which is
#                        not necessarily above the terrain, and a mob that falls is a mob that moved
#   Invulnerable         stops it dying. This is the one that was missing: a mob summoned inside a block takes
#                        suffocation damage every tick, so the guard found no pig a few seconds later and
#                        placed another one - which is exactly the 4-5 second rhythm the log showed
#   PersistenceRequired  stops it despawning when it is out of a player's range
#
# The families are chosen to be different *renderers* and not different mobs: a living entity with a cutout
# model, an armour stand with no AI at all, a dropped item that draws an item model in the world, and an
# experience orb, which is an unlit billboard from a texture atlas of its own.
#
# Every placement says so first, and the harness refuses an arm whose log does not carry the line - or carries
# it twice, because one placement per type is what makes two arms the same scene.
execute unless entity @e[type=minecraft:pig] run say showcase: placed the pig
execute at @a unless entity @e[type=minecraft:pig] run summon minecraft:pig ^1 ^1 ^4 {NoAI:1b,NoGravity:1b,Invulnerable:1b,Silent:1b,PersistenceRequired:1b}
execute unless entity @e[type=minecraft:cow] run say showcase: placed the cow
execute at @a unless entity @e[type=minecraft:cow] run summon minecraft:cow ^-1 ^1 ^4 {NoAI:1b,NoGravity:1b,Invulnerable:1b,Silent:1b,PersistenceRequired:1b}
execute unless entity @e[type=minecraft:armor_stand] run say showcase: placed the armor_stand
execute at @a unless entity @e[type=minecraft:armor_stand] run summon minecraft:armor_stand ^1 ^1 ^5.5 {NoGravity:1b,Invulnerable:1b,ShowArms:1b,Silent:1b}
execute unless entity @e[type=minecraft:item] run say showcase: placed the item
execute at @a unless entity @e[type=minecraft:item] run summon minecraft:item ^-1 ^2 ^5.5 {NoGravity:1b,Invulnerable:1b,PickupDelay:32767s,Item:{id:"minecraft:apple",count:1}}
execute unless entity @e[type=minecraft:experience_orb] run say showcase: placed the experience_orb
execute at @a unless entity @e[type=minecraft:experience_orb] run summon minecraft:experience_orb ^0 ^3 ^5.5 {NoGravity:1b,Invulnerable:1b,Age:-32768s,Value:7s}
