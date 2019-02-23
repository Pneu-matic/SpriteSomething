import argparse
import os

import util
from constants import *

data = None

def main():
    if not os.access("images", os.F_OK):
        os.mkdir("images")

    command_line_args = process_command_line_args()

    #main data
    global data
    data = util.Samus(rom_filename=command_line_args[ROM_FILENAME_ARG_KEY])

    pal = command_line_args[PALETTE_ARG_KEY]

    export_custom_sequences(pal)

    export_all_raw_animations(pal)

    #export_specific_pose(0x1A, -1, pal)  #as (animation_number, pose_number, palette_name)

    #export_tiles(0x1A, -1, pal)          #as (animation number, pose_number, palette_name)




def export_custom_sequences(palette_name, zoom=2):
    events = { 80:{'kick':True}, \
               200:{'kick':True}, \
               200:{'heavy_breathing':True}, \
               300:{'new_animation':0x0A}, \
               400:{'new_animation':0x10}, \
               500:{'new_animation':0x1A}}   #I'm thinking that this will eventually be JSON
    data.animation_sequence_to_gif('images/test_sequence.gif', zoom=zoom, starting_animation=0xE9, \
        events=events, palette_type=palette_name)


def export_all_raw_animations(palette_name, zoom=2):
    for animation_number in range(len(data.animations)):
        if data.animations[animation_number].used:
            try:
                data.animations[animation_number].gif(f"images/animation_raw_{hex(animation_number)[2:].zfill(2)}.gif", data.palettes[palette_name],zoom=zoom)
            except AssertionError as e:
                print(f"AssertionError on animation {hex(animation_number)}: {e.args}")


def export_specific_pose(animation_number, pose_number, palette_name, zoom=3):
    pose = data.animations[animation_number].poses[pose_number]
    img = pose.to_image(data.palettes[palette_name],zoom=zoom)
    #img.show()
    img.save(f"images/pose_{pose.ID}.png")


def export_tiles(animation_number, pose_number, palette_name, zoom=2):
    for tile in data.animations[animation_number].poses[pose_number].tiles:
        img = tile.to_image(data.palettes[palette_name],zoom=zoom)
        #img.show()
        img.save(f"images/tile_{tile.ID}.png")


def process_command_line_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom",
                        dest=ROM_FILENAME_ARG_KEY,
                        help="Location of the rom file; e.g. /my_dir/game.smc",
                        metavar="<rom_filename>",
                        default='metroid.smc')
                        #required=False)
    parser.add_argument("--palette",
                        dest=PALETTE_ARG_KEY,
                        help="Which palette to use; i.e. one of 'standard', 'varia', or 'gravity'",
                        metavar="<palette>",
                        default='standard')
                        #required=False)
    
    command_line_args = vars(parser.parse_args())

    return command_line_args


if __name__ == "__main__":
    main()