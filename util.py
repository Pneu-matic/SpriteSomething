#Written by Artheau
#over several days in Feb. 2019
#while looking out the window and dreaming of being outside in the sunshine


#TODO: Extract palettes from ROM directly
#TODO: Get palettes for the all the crazy stuff like charge attacks and fast running
#TODO: Change large tiles to supertiles
#TODO: Try to merge supertiles when they are iff located correctly, and align


'''
ROADMAP:

Samus:
    animations = list of Animations
    animation_sequence_to_gif(self, filename, many_optional_args): save a GIF of an animation sequence

Animation:
    ID = unique identifying string
    index = actual value for the animation in-game
    used = True if the animation is used
    description = string with info about the animation
    poses = list of Poses
    gif(filename,palette): save a GIF of this animation

Pose:
    ID = unique identifying string
    duration = how long to hold this pose (in frames)
    VRAM = a 0x20 length list specifying the memory address of tiles loaded into VRAM during this pose
    upper_tiles = list of upper body Tiles
    lower_tiles = list of lower body Tiles
    tiles = list of all Tiles
    to_image(palette): retrieve an image of this pose

Tile:
    large = True if 16x16
    addresses = list of ROM addresses that this tile references
    x_offset = x offset
    y_offset = y offset
    auto_flag = ???
    v_flip = True if v flip
    h_flip = True if h flip
    priority = True if priority flag set
    palette = Palette
    draw_on(dict): inject raw pixel data into this dict
'''

import struct
import csv
import math
from PIL import Image

import romload

#There is a bug in Pillow version 5.4.1 that does not display GIF transparency correctly
#It is because of Line 443 in GifImagePlugin.py not taking into account the disposal method
#Please help fix this
#https://github.com/python-pillow/Pillow/issues/3665
import PIL
if int(PIL.PILLOW_VERSION.split('.')[0]) <= 5:
    TRANSPARENCY = 255
    DISPOSAL = 0
else:
    TRANSPARENCY = 0
    DISPOSAL = 2

rom = None

TILESIZE = 0x20
TILE_DIMENSION = int(math.sqrt(2 * TILESIZE))           #4 bits per pixel => 2 pixels per byte
BACKGROUND_COLOR = '#36393f'

class Samus:
    def __init__(self, rom_filename, animation_data_filename="animations.csv"):
        global rom
        rom = romload.load_rom_contents(rom_filename)
        self.animations = self.load_animations(animation_data_filename)
        self.palettes = self.load_palettes()

    def animation_sequence_to_gif(self, filename, zoom=1, starting_animation=0x00, events={}, full_duration=600, \
        palette_type='standard', jump_type=0, springball=False, heavy_breathing=False, in_air=False, exhausted=False):
        animation = self.animations[starting_animation]
        kicked = False
        elapsed_frames = 0
        pose_number = 0
        control_offset = 0
        canvases = []
        image_durations = []

        while(elapsed_frames < full_duration):
            frame_delta = animation.duration_list[pose_number+control_offset]
            if frame_delta & 0x80 != 0:     #not a duration, actually a control code
                if frame_delta == 0xF6:     #the heavy breathing check
                    if heavy_breathing:        #just continue
                        control_offset += 1
                    else:                      #reset animation
                        pose_number = 0
                        control_offset = 0
                elif frame_delta == 0xF7:   #the exhausted check
                    if exhausted:
                        pose_number += 1       #skip over the pose that you would be stuck at if not exhausted
                        control_offset += 3    #go over the next conditional loop ($FE $??)
                    else:
                        control_offset += 1    #skip over the command and its argument (always $01)
                elif frame_delta in [0xF8,0xFD]:    #jump to new animation
                    new_animation_number = animation.duration_list[pose_number+control_offset+1]
                    animation = self.animations[new_animation_number]
                    pose_number = 0
                    control_offset = 0
                elif frame_delta == 0xF9:   #springball conditional
                    index_to_ref = (1 if in_air else 0) + 2 * (1 if springball else 0)
                    new_animation_number = animation.duration_list[pose_number+control_offset+3+index_to_ref]   #add 3 to bypass $F9 and also the next argument (always $0002)
                    animation = self.animations[new_animation_number]
                    pose_number = 0
                    control_offset = 0
                elif frame_delta == 0xFB:   #jump type conditional
                    if jump_type == 0:
                        control_offset += 1
                    elif jump_type == 1:
                        control_offset += 11
                    elif jump_type == 2:
                        control_offset += 21
                    else:
                        raise AssertionError(f"while processing animation sequence, encounter jump_type {jump_type}, not recognized")
                elif frame_delta == 0xFE:    #go back a number of frames
                    if kicked:
                        kicked = False
                        control_offset += 2
                    else:
                        pose_number -= animation.duration_list[pose_number+control_offset+1]
                elif frame_delta == 0xFF:    #reset animation
                    if kicked:
                        kicked = False
                        control_offset += 1
                    else:
                        pose_number = 0
                        control_offset = 0
                else:
                    print(f"Unimplemented control code {hex(frame_delta)} encountered in animation_sequence_to_gif()")
                    control_offset += 1
            else:                        #not a control code, so process the duration normally
                current_canvas = animation.poses[pose_number].to_canvas()
                pose_number += 1
                for i in range(elapsed_frames+1,elapsed_frames+1+frame_delta):  #iterate over the interval
                    if i in events:                                             #likely no events at this time
                        for event_name in events[i]:                            #but if there are, parse each one
                            if event_name == 'exhausted':
                                exhausted = events[i][event_name]
                            elif event_name == 'heavy_breathing':
                                heavy_breathing = events[i][event_name]
                            elif event_name == 'kick':
                                kicked = True
                            elif event_name == 'new_animation':
                                frame_delta = max(1,i-elapsed_frames)
                                animation = self.animations[events[i][event_name]]
                                pose_number = 0
                                control_offset = 0
                            else:
                                raise AssertionError(f"Unimplemented event of type {event_name}")

                if current_canvas.keys():       #not an empty canvas
                    elapsed_frames += frame_delta
                    image_durations.append(frame_delta)
                    canvases.append(current_canvas)
                else:
                    print(f"empty canvas in animation_sequence_to_gif(): {animation.ID}")
                

        convert_canvas_to_gif(filename, canvases, image_durations, self.palettes[palette_type], zoom)






    def load_animations(self, animation_data_filename):
        #generated this csv data from community disassembly data (thank you to all contributors)
        #format: [ANIMATION_ID, NUM_KICKS, USED, DESCRIPTION]
        animations = []
        with open(animation_data_filename, 'r') as csvfile:
            spamreader = csv.reader(csvfile, delimiter=';')
            for row in spamreader:
                index = int(row[0],0)    #the second argument specifies to determine if it is hex or not automatically
                num_kicks = int(row[1])
                used = row[2].lower() in ['true','t','y']
                description = row[3]
                animations.append(Animation(index, num_kicks, used, description))
        return animations

    def load_palettes(self):
        palettes = {}

        palettes['power'] = self.get_palette_at(0x9B9400)
        palettes['varia'] = self.get_palette_at(0x9B9520)
        palettes['gravity'] = self.get_palette_at(0x9B9800)

        palettes['standard'] = palettes['power']
        

        #append the fixed palettes...these are just guesses at present because it's not clear that white and black palettes
        # are the correct palettes to use here
        for palette in palettes.keys():
            samus_palette = palettes[palette]

            white_palette_blueprint = [(0xFF,0xFF,0xFF),(0xEF,0xEF,0xEF),(0xD6,0xD6,0xD6),(0xC6,0xC6,0xC6)]
            white_palette = [(0x00,0x00,0xFF)] + 3*white_palette_blueprint + white_palette_blueprint[:-1]

            # chroma_palette =  [
            #                     (0x00,0x00,0xFF),
            #                     (0xEF,0x84,0x00),(0xAD,0x00,0x00),(0x42,0x00,0x00),(0x18,0x00,0x00),
            #                     (0xEF,0x29,0x00),(0x9C,0x00,0x00),(0x73,0x00,0x00),(0x5A,0x00,0x00),
            #                     (0xD6,0xD6,0xFF),(0x00,0xB5,0xFF),(0x00,0x7B,0xDE),(0x00,0x39,0xAD),
            #                     (0xFF,0x00,0x00),(0xAD,0x00,0x00),(0x52,0x00,0x00)
            #                   ]

            # yellow_and_friends_palette = [
            #                                 (0x00,0x00,0xFF),
            #                                 (0xFF,0xFF,0x5A),(0xBD,0xBD,0x31),(0x52,0x52,0x00),(0x18,0x18,0x00),
            #                                 (0xD6,0xD6,0x4A),(0xAD,0xAD,0x18),(0x84,0x84,0x00),(0x73,0x73,0x00),
            #                                 (0x00,0xFF,0x00),(0x00,0xBD,0x00),(0x00,0x84,0x00),(0x00,0x42,0x00),
            #                                 (0x00,0xC6,0xFF),(0x00,0x7B,0xDE),(0x00,0x39,0xAD)
            #                              ]

            # purple_palette = [
            #                     (0x00,0x00,0xFF),
            #                     (0xD6,0xD6,0xFF),(0xDE,0xCE,0x00),(0xB5,0x84,0x00),
            #                     (0x9C,0x42,0x00),(0xEF,0x00,0xFF),(0xA5,0x00,0xB5),
            #                     (0x52,0x00,0x63),(0x00,0xFF,0x73),(0x00,0x63,0x29),
            #                     (0xA5,0xA5,0xA5),(0x73,0x73,0x73),(0x42,0x42,0x42),
            #                     (0x21,0x21,0x4A),(0x42,0x42,0xFF)
            #                  ]

            black_palette = [(0,0,0)]*16

            #palette comments given as (in tilemap, in game)
            palettes[palette] = [   None,                        #0b000
                                    None,                        #0b001
                                    samus_palette,               #0b010  (Samus)  <-- definitely Samus.  definitely.
                                    black_palette,               #0b011  <-- not sure if this should be all black...it is the shadow inside the crystal flash
                                    None,                        #0b100
                                    None,                        #0b101
                                    None,                        #0b110
                                    white_palette                #0b111  <-- I'm not really sure about this, because of palette effects applied during crystal_flash
                                ]
        return palettes

    def get_palette_at(self, addr):
        raw_palette = get_indexed_values(addr,0,0x02,'2'*0x10)   #retrieve 0x10 2-byte colors in BGR 555 format
        palette = []
        for color in raw_palette:
            palette.append(convert_from_555(color))
        return palette

class Animation:
    def __init__(self, index, num_kicks, used, description):
        self.ID = hex(index)
        self.index = index
        self.used = used
        self.description = description
        self.duration_list, self.pose_mask = self.get_transition_data(num_kicks)
        self.poses = self.load_poses(num_kicks) if self.used else []

    def gif(self, filename, palette,zoom=1):
        duration_codes = [pose.duration for pose in self.poses]
        canvases = [pose.to_canvas() for pose in self.poses]

        convert_canvas_to_gif(filename, canvases,duration_codes, palette, zoom)





    def load_poses(self,num_kicks):
        num_poses = len(self.duration_list)-1   #the last pose in the duration_list is always a control code with no pose present

        [upper_offset] = get_indexed_values(0x929263,self.index,0x02,'2')
        [lower_offset] = get_indexed_values(0x92945D,self.index,0x02,'2')

        upper_tilemap_offsets = get_indexed_values(0x92808D,upper_offset,0x02,'2'*num_poses)
        lower_tilemap_offsets = get_indexed_values(0x92808D,lower_offset,0x02,'2'*num_poses)

        poses = []
        for pose_number in range(num_poses):
            if self.pose_mask[pose_number]:         #don't process the pose if it is just a control code
                upper_tilemap = get_tilemap(upper_tilemap_offsets[pose_number])
                lower_tilemap = get_tilemap(lower_tilemap_offsets[pose_number])
                
                poses.append( Pose(f"{self.ID},P{pose_number}", \
                              self.get_VRAM_data(pose_number), \
                              self.duration_list[pose_number],
                              upper_tilemap, \
                              lower_tilemap)
                            )

        return poses

    def get_VRAM_data(self, pose_number):
        [DMA_table_info_location] = get_indexed_values(0x92D94E,self.index,0x02,'2')
        DMA_table_info_location += 0x920000

        [upper_table_location,upper_index,lower_table_location,lower_index] = get_indexed_values(DMA_table_info_location,pose_number,0x04,'1111')

        [upper_DMA_table] = get_indexed_values(0x92D91E,upper_table_location,0x02,'2')
        [lower_DMA_table] = get_indexed_values(0x92D938,lower_table_location,0x02,'2')
        upper_DMA_table += 0x920000
        lower_DMA_table += 0x920000


        upper_graphics_data = get_indexed_values(upper_DMA_table,upper_index,0x07,'322')  
        lower_graphics_data = get_indexed_values(lower_DMA_table,lower_index,0x07,'322')  

        VRAM = load_virtual_VRAM(upper_graphics_data,lower_graphics_data)

        return VRAM

    def get_transition_data(self, num_kicks):
        #anyone who reads this code is going to ask me what a "kick" is.  By this I mean the number of times
        # the animation can be manually pushed into the next phase by a storyline event
        # e.g. 2 kicks in crystal flash.  One to kick into the animated silhouette phase, and another to kick out of the orb phase.
        [duration_list_location] = get_indexed_values(0x91B010,self.index,0x02,'2')
        duration_list_location += 0x910000

        duration_list = []
        pose_mask = []
        MAX_INSTRUCTIONS = 0x100
        for _ in range(MAX_INSTRUCTIONS):
            [duration] = get_indexed_values(duration_list_location,len(duration_list),0x01,'1')
            duration_list.append(duration)

            if (duration & 0x80) == 0:   #not a control code
                pose_mask.append(True)   #process normally
            else:        #control code
                pose_mask.append(False)
                if duration == 0xF6:
                    num_kicks += 1           #pass over this to get the "heavy breathing" frames
                elif duration == 0xF7:
                    num_kicks += 2           #this command branches past a controlled loop, so we need to kick past $F7 AND that loop
                elif duration == 0xF8 or duration == 0xFD:
                    duration_list.extend(get_indexed_values(duration_list_location,len(duration_list),0x01,'1'))  #get animation to jump to
                    pose_mask.append(False)
                elif duration == 0xF9:
                    duration_list.extend(get_indexed_values(duration_list_location,len(duration_list),0x01,'21111'))  #get springball jump data
                    pose_mask.extend(5*[False])
                elif duration == 0xFB:
                    num_kicks += 3           #kick through this jump branch, and also kick over the next two (different types of jumps)
                elif duration == 0xFC:
                    duration_list.extend(get_indexed_values(duration_list_location,len(duration_list),0x01,'211'))  #not present in used animations    
                    pose_mask.extend(3*[False])
                elif duration == 0xFE:
                    duration_list.extend(get_indexed_values(duration_list_location,len(duration_list),0x01,'1'))  #get number of frames to go back
                    pose_mask.append(False)
                elif duration == 0xFF:
                    pass                       #nothing to do in this case, it is just the end of the line (loop to beginning)
                else:
                    raise AssertionError(f"In {self.ID}, reached duration code {hex(duration)} which is not implemented.")
                
                if num_kicks > 0:
                    num_kicks -= 1
                else:
                    break                     #out of infinite loop


        else:      #we never broke out of the loop, just ran out MAX_INSTRUCTIONS
            raise AssertionError(f"Error in get_transition_data(), did not break out of loop")

        return duration_list, pose_mask



class Pose:
    def __init__(self, ID, VRAM, duration, upper_tilemap, lower_tilemap):
        self.ID = ID
        self.duration = duration
        self.VRAM = VRAM
        self.upper_tiles = self.get_tiles(upper_tilemap)
        self.lower_tiles = self.get_tiles(lower_tilemap)

    @property
    def tiles(self):
        return self.upper_tiles + self.lower_tiles


    def to_canvas(self):
        canvas = {}
        for tile in self.tiles[::-1]:
            canvas = tile.draw_on(canvas)
        return canvas

    def get_tiles(self, raw_tilemap):
        tiles = []
        for i,raw_tile in enumerate(raw_tilemap):
            tiles.append(Tile(f"{self.ID},T{i}",self.VRAM, raw_tile))
        return tiles

    def to_image(self,palette,zoom=1):
        return to_image(self,palette,zoom=zoom)


class Tile:
    def __init__(self, ID, VRAM, raw_tile):
        self.large = raw_tile[1] & 0x80 != 0x00    #what do bits 1 and 6 of raw_tile[1] do?
        self.ID = ID
        if self.large:
            self.addresses = [VRAM[raw_tile[3] + offset] for offset in [0x00,0x01,0x10,0x11]]
        else:
            self.addresses = [VRAM[raw_tile[3]]]
        if None in self.addresses:
            raise AssertionError(f"referenced stale VRAM using tile {self.ID}")
        self.auto_flag = raw_tile[1] & 0x01 != 0x00
        self.x_offset = convert_int_to_signed_int(raw_tile[0])# - (1 if self.auto_flag else 0)
        self.y_offset = convert_int_to_signed_int(raw_tile[2])
        self.h_flip = raw_tile[4] & 0x40 != 0x00
        self.v_flip = raw_tile[4] & 0x80 != 0x00
        self.priority = raw_tile[4] & 0x20 != 0x00
        if not self.priority:
            raise AssertionError(f"priority bit unset, tile {self.ID}")   #only matters for animations $82 and $1C which are just typos
        self.palette = (raw_tile[4] >> 2) & 0b111
        if self.palette not in [0b010,0b011,0b111]:
            raise AssertionError(f"Tile {self.ID} uses palette {self.palette}.  raw_tile = {[hex(raw) for raw in raw_tile]}")  #only matters for animations $81,82,$1B, and $1C which are just typos

    def to_image(self,palette,zoom=1):
        return to_image(self,palette,zoom=zoom)

    def draw_on(self,canvas):
        for tile_no,addr in enumerate(self.addresses):
            chunk_offsets = [(0,0),(TILE_DIMENSION,0),(0,TILE_DIMENSION),(TILE_DIMENSION,TILE_DIMENSION)]
            pixels = self.retrieve_tile(addr)


            if self.h_flip:
                pixels = pixels[::-1]
                if self.large:
                    chunk_offsets = [(TILE_DIMENSION-x,y) for (x,y) in chunk_offsets]
            if self.v_flip:
                pixels = [row[::-1] for row in pixels]
                if self.large:
                    chunk_offsets = [(x,TILE_DIMENSION-y) for (x,y) in chunk_offsets]

            chunk_offset = chunk_offsets[tile_no]


            for i in range(TILE_DIMENSION):
                for j in range(TILE_DIMENSION):
                    if pixels[i][j] != 0:             #if not transparent_pixel
                        canvas[(i+self.x_offset+chunk_offset[0],j+self.y_offset+chunk_offset[1])] = (pixels[i][j], self.palette)
        return canvas

    def to_canvas(self):
        return self.draw_on({})

    def retrieve_tile(self, addr):
        raw_tile = rom[addr:addr+TILESIZE]
        pixels = [[0 for _ in range(TILE_DIMENSION)] for _ in range(TILE_DIMENSION)]
        for i in range(TILE_DIMENSION):
            for j in range(TILE_DIMENSION):
                for bit in range(2):            #bitplanes 1 and 2
                    index = i*2 + bit
                    amt_to_inc = (get_bit(raw_tile[index],TILE_DIMENSION-j-1)) * (0x01 << bit)
                    pixels[j][i] += amt_to_inc
                for bit in range(2):            #bitplanes 3 and 4
                    index = i*2 + bit + 2*TILE_DIMENSION
                    amt_to_inc = (get_bit(raw_tile[index],TILE_DIMENSION-j-1)) * (0x01 << (bit+2))
                    pixels[j][i] += amt_to_inc
              #notes in comments here are from https://mrclick.zophar.net/TilEd/download/consolegfx.txt
              # [r0, bp1], [r0, bp2], [r1, bp1], [r1, bp2], [r2, bp1], [r2, bp2], [r3, bp1], [r3, bp2]
              # [r4, bp1], [r4, bp2], [r5, bp1], [r5, bp2], [r6, bp1], [r6, bp2], [r7, bp1], [r7, bp2]
              # [r0, bp3], [r0, bp4], [r1, bp3], [r1, bp4], [r2, bp3], [r2, bp4], [r3, bp3], [r3, bp4]
              # [r4, bp3], [r4, bp4], [r5, bp3], [r5, bp4], [r6, bp3], [r6, bp4], [r7, bp3], [r7, bp4]
        return pixels











#######################################













def get_indexed_values(base,index,entry_size,encoding):
    #returns an unpacked list of the values specified by the enconding at base[index], assuming array entries are entry_size long
    beginning_of_entry = convert_to_rom_address(base+index*entry_size)
    returnvalue = []
    for code in encoding:
        bytes_to_get = int(code)

        extracted_bytes = rom[beginning_of_entry:beginning_of_entry+bytes_to_get]


        if bytes_to_get == 1:
            unpack_code = 'B'
        elif bytes_to_get == 2:
            unpack_code = 'H'
        elif bytes_to_get == 3:
            unpack_code = 'L'
            extracted_bytes += b'\x00'    #no native 3-byte unpacking format in Python; this is a workaround to pad the 4th byte
        else:
            raise AssertionError(f"get_indexed_values() called with encoding {encoding}, contains invalid code {code}.")

        extracted_value = struct.unpack('<'+unpack_code,extracted_bytes)[0]           #the '<' forces it to read as little-endian
        returnvalue.append(extracted_value)
        beginning_of_entry += bytes_to_get
    return returnvalue

def get_bit(byteval,idx):
    #https://stackoverflow.com/questions/2591483/getting-a-specific-bit-value-in-a-byte-string
    return ((byteval&(1<<idx))!=0)


def convert_to_rom_address(snes_addr):
    #convert from memory address to ROM address (lorom 0x80)
    bank = snes_addr // 0x10000 - 0x80
    offset = (snes_addr % 0x10000) - 0x8000

    if offset < 0x0000 or bank < 0x00:
        raise AssertionError(f"Function convert_to_rom_address() called on {hex(snes_addr)}, but this is not a valid SNES address.")
    
    new_address = bank*0x8000 + offset

    return new_address

def convert_int_to_signed_int(byte):
    if byte > 127:
        return (256-byte) * (-1)
    else:
        return byte

def convert_from_555(color):
    red = 8*(color & 0b11111)
    green = 8*((color >> 5) & 0b11111)
    blue = 8*((color >> 10) & 0b11111)
    return (red,green,blue)


def load_virtual_VRAM(upper_graphics_data,lower_graphics_data):
    [upper_graphics_ptr,upper_top_row_amt,upper_bottom_row_amt] = upper_graphics_data
    [lower_graphics_ptr,lower_top_row_amt,lower_bottom_row_amt] = lower_graphics_data

    VRAM = [None] * 0x20    #initialize

    for i in range(upper_top_row_amt//TILESIZE):
        VRAM[i] = convert_to_rom_address(upper_graphics_ptr + i * TILESIZE)

    for i in range(lower_top_row_amt//TILESIZE):
        VRAM[0x08 + i] = convert_to_rom_address(lower_graphics_ptr + i * TILESIZE)

    for i in range(upper_bottom_row_amt//TILESIZE):
        VRAM[0x10 + i] = convert_to_rom_address(upper_graphics_ptr + upper_top_row_amt + i * TILESIZE)

    for i in range(lower_bottom_row_amt//TILESIZE):
        VRAM[0x18 + i] = convert_to_rom_address(lower_graphics_ptr + lower_top_row_amt + i * TILESIZE)

    return VRAM


def get_tilemap(offset):
    tilemap = []

    if offset != 0x00:             #offset can be zero for empty tilemaps (no tiles in this half of Samus body)
        tilemap_location = 0x920000+offset

        [tilemap_size] = get_indexed_values(tilemap_location,0,0x01,'2')

        for tile_number in range(tilemap_size):
            raw_tile = get_indexed_values(tilemap_location+(0x02+tile_number*0x05),0,0x01,'11111')
            tilemap.append(raw_tile)

    return tilemap


def to_image(object,palette,zoom=1):
    canvas = object.to_canvas()

    width = 1+max([abs(x) for (x,y) in canvas.keys()])
    height = 1+max([abs(y) for (x,y) in canvas.keys()])
    
    image = Image.new("RGBA", (2*width, 2*height), BACKGROUND_COLOR)

    pixels = image.load()

    for (i,j) in canvas.keys():
        color_index, palette_index = canvas[(i,j)]
        pixels[i+width,j+height] = palette[palette_index][color_index] # set the colour accordingly

    #scale
    image = image.resize((zoom*(2*width), zoom*(2*height)), Image.NEAREST)

    return image

def convert_canvas_to_gif(filename, canvases, frame_durations, palette, zoom=1):

    #FRAME_DURATION = 1000/60    #for true-to-NTSC attempts
    FRAME_DURATION = 20          #given GIF limitations, this seems like a good compromise
    
    MARGIN = 0x08

    x_min = min([x for canvas in canvases for (x,y) in canvas.keys()]) - MARGIN
    x_max = max([x for canvas in canvases for (x,y) in canvas.keys()]) + MARGIN
    y_min = min([y for canvas in canvases for (x,y) in canvas.keys()]) - MARGIN
    y_max = max([y for canvas in canvases for (x,y) in canvas.keys()]) + MARGIN

    width = x_max-x_min+1
    height = y_max-y_min+1
    origin = (-x_min,-y_min)

    images = []
    durations = []
    for canvas,duration in zip(canvases,frame_durations):
        if canvas.keys():

            images.append(Image.new("RGBA", (width, height),BACKGROUND_COLOR))
            durations.append(int(FRAME_DURATION*duration))

            pixels = images[-1].load()

            for (i,j) in canvas.keys():
                color_index, palette_index = canvas[(i,j)]
                pixels[i+origin[0],j+origin[1]] = palette[palette_index][color_index] # set the colour accordingly

    #scale
    images = [image.resize((zoom*width, zoom*height), Image.NEAREST) for image in images]

    if len(durations) > 1:
        images[0].save(filename, 'GIF', save_all=True, append_images=images[1:], duration=durations, transparency=TRANSPARENCY, disposal=DISPOSAL, loop=0)
    else:
        images[0].save(filename, transparency=TRANSPARENCY)


####################################################

def main():
    data = Samus()
    raise AssertionError("Compiled utility library directly")
    
if __name__ == "__main__":
    main()