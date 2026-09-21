# Entities of several render families, in front of the camera and not moving.
#
# Vanilla's own frame is not only terrain, clouds and particles: it is also what a mob, an item and an armour
# stand draw, and the world this harness stages has no entities of its own to draw (measured: with
# `--keep-entities` the frame's passes a frame, pipeline identities and depth attachments are the still-life
# scene's to the digit, so nothing was there). A world with no entities cannot answer "does this path draw one".
#
# So they are summoned here, once each - the guard is `unless entity`, which means the first tick of a session
# places them and every later tick does nothing - and each one is still:
#
#   NoAI        stops the mob's own movement *and* its look control, so its pose is the same in every launch
#   Silent      nothing to hear, which is nothing to the frame either way
#   NoGravity   on the armour stand and the item, so neither drifts
#   PickupDelay on the item, so the player cannot take it and so it never despawns
#
# The families are chosen to be different *renderers* and not different mobs: a living entity with a cutout
# model, an armour stand with no AI at all, a dropped item that draws an item model in the world, and an
# experience orb, which is an unlit billboard from a texture atlas of its own.
execute unless entity @e[type=minecraft:pig] run say showcase: placed the pig
execute at @a unless entity @e[type=minecraft:pig] run summon minecraft:pig ^1 ^0 ^4 {NoAI:1b,Silent:1b,PersistenceRequired:1b}
execute unless entity @e[type=minecraft:cow] run say showcase: placed the cow
execute at @a unless entity @e[type=minecraft:cow] run summon minecraft:cow ^-1 ^0 ^4 {NoAI:1b,Silent:1b,PersistenceRequired:1b}
execute unless entity @e[type=minecraft:armor_stand] run say showcase: placed the armor_stand
execute at @a unless entity @e[type=minecraft:armor_stand] run summon minecraft:armor_stand ^1 ^0 ^5.5 {NoGravity:1b,ShowArms:1b,Silent:1b}
execute unless entity @e[type=minecraft:item] run say showcase: placed the item
execute at @a unless entity @e[type=minecraft:item] run summon minecraft:item ^-1 ^1 ^5.5 {NoGravity:1b,PickupDelay:32767s,Item:{id:"minecraft:apple",count:1}}
execute unless entity @e[type=minecraft:experience_orb] run say showcase: placed the experience_orb
execute at @a unless entity @e[type=minecraft:experience_orb] run summon minecraft:experience_orb ^0 ^2 ^5.5 {NoGravity:1b,Age:-32768s,Value:7s}
