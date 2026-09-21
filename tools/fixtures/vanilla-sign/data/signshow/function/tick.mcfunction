# A sign with text in front of the camera, because a sign's glyphs are the game's own depth-biased pipeline.
#
# The depth-bias call is the one place this path's own reading is thin: `MTL4Probe.canApplyDepthBias` proves the
# device honours `setDepthBias:slopeScale:clamp:` - the biased draw wins a compare the unbiased control fails -
# but no measured frame had ever *asked* for a bias (`depthBias=0` in every window), so cross-generation parity
# of a biased frame was vacuous. Vanilla does ask: `RenderPipelines.TEXT_POLYGON_OFFSET` is built with
# `new DepthStencilState(CompareOp.GREATER_THAN_OR_EQUAL, true, 1.0f, 10.0f)` and `AbstractSignRenderer` submits a
# sign's text with `Font.DisplayMode.POLYGON_OFFSET`, which selects it. A sign is therefore the smallest live
# workload that reaches the call, and this fixture is that sign: placed once, in front of the camera, with text
# on both faces so whichever way the game turns the board there is glyph work in the frame.
#
# **The text's shape cost two runs, and the game named the fault both times.** `SignText` decodes `front_text`
# as a map whose `messages` field is a list of *exactly four* components - `['a']` and `['a','b']` are both
# refused ("Input is not a list of 4 elements") and a bare four-string list is refused as well ("Not a map") -
# so the two failed versions placed a blank sign, drew no glyph, and left the census reading `depthBias=0`: the
# switch, the datapack and the placement were all right and the *text* was not, which is the one failure mode
# this fixture exists to avoid.
#
# The placement pattern is the block fixture's: a marker entity at a camera-relative offset (`^` is local, so
# the sign lands where the camera is looking and not at a fixed world coordinate we would have to guess), and
# the `setblock` at the marker's own position. `unless entity` places it once, so the scene does not depend on
# how long a session runs.
execute unless entity @e[type=minecraft:marker,tag=signshow_sign] run say showcase: placed the sign
execute at @a unless entity @e[type=minecraft:marker,tag=signshow_sign] run summon minecraft:marker ^0 ^1 ^5 {Tags:["signshow_sign"]}
execute at @e[type=minecraft:marker,tag=signshow_sign] run setblock ~ ~ ~ minecraft:oak_sign{front_text:{messages:['depth bias','slope 1 const 10','','']},back_text:{messages:['metal 4','','','']}} replace
