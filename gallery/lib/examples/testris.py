# gallery: featured
# deps: pygraphics
# utils: framebuf, micropython
"""
Testris game implemented in MicroPython by Brad Barnett.
"""

# For the display & optional touch drivers
from board_config import display_drv
import board_config
import appdev

app = appdev.App(board_config)
from displaydev import alloc_buffer
from appdev import TouchGrid
from appdev import JoyMap
import keys
try:
    from random import choice  # For random piece selection
except ImportError:
    def choice(seq):
        return seq[0]
from json import load, dump  # For saving the high score
from sys import exit  # For exiting the game
from pygraphics import FrameBuffer, RGB565  # For drawing text boxes

try:
    from micropython import const  # For constant values
except ImportError:

    def const(x):
        return x

from multimer import ticks_diff, ticks_ms

if display_drv.width > display_drv.height:
    display_drv.rotation += 90


# Setup the keypad
# TouchKeypad uses read_held() for continuous movement; JoystickKeys uses read().
START = keys.K_RETURN  # RETURN
UNUSED = 0  # Not used
PAUSE = keys.K_ESCAPE  # ESCAPE
CCW = keys.K_d  # D
DROP = keys.K_UP  # UP
CW = keys.K_f  # F
LEFT = keys.K_LEFT  # LEFT
DOWN = keys.K_DOWN  # DOWN
RIGHT = keys.K_RIGHT  # RIGHT
keypad = TouchGrid(
    app,
    0,
    0,
    display_drv.width,
    display_drv.height,
    keys=[START, UNUSED, PAUSE, CW, DROP, CCW, LEFT, DOWN, RIGHT],
)

joystick_keys = JoyMap(
    app,
    joymap={
        1: {
            'hats': {
                0: [LEFT, RIGHT, DOWN, DROP]
            },
            'buttons': {
                0: START,
                1: CCW,
                2: CW,
            }
        }
    }
)


def _quit_if_needed(_where):
    # Do not call app.poll() from an on_tick callback: on sync librt
    # backends that re-enters the timer path and deadlocks. Auto-service
    # already dispatches input to TouchKeypad/JoystickKeys and handles QUIT.
    if not app.quit_requested if app else False:
        return False
    display_drv.quit()
    return True


class _Loop:
    """Cooperative poll helper."""

    def poll(self, where):
        return _quit_if_needed(where)


def _test_key_for_test_mode(key=None):
    try:
        import pydevices_test_mode

        if pydevices_test_mode.ENABLED:
            return key if key is not None else START
    except ImportError:
        pass
    return None


def _gather_keys():
    """Edge + held keys from joystick and touch keypad."""
    keys = list(joystick_keys.read())
    edge = keypad.read()
    if edge:
        keys.extend(edge)
    keys.extend(keypad.read_held())
    return keys


def _iter_wait_for_key(loop, key=None, exclude=None):
    if exclude is None:
        exclude = []
    test_key = _test_key_for_test_mode(key)
    if test_key is not None:
        yield test_key
        return
    while True:
        if loop.poll("wait_for_key"):
            yield True
            return
        keys = _gather_keys()
        if key is not None:
            if key in keys:
                yield key
                return
            if key == START:
                for pressed in keys:
                    if pressed not in exclude:
                        yield pressed
                        return
        else:
            for pressed in keys:
                if pressed not in exclude:
                    yield pressed
                    return
        yield False


def _yield_wait(loop, key=None, exclude=None):
    """Cooperative key wait: yields False while polling, True on quit, then the key."""
    for _key in _iter_wait_for_key(loop, key, exclude):
        if _key is True:
            yield True
            return
        if _key is False:
            yield False
            continue
        yield _key
        return


class _RoundState:
    def __init__(self, pieces, grid_width, grid_height):
        self.grid = [[0 for _ in range(grid_width)] for _ in range(grid_height)]
        self.bag = []
        self.next_piece = choice(pieces)
        self.score = 0
        self.lines = 0
        self.drop_time = 1000
        self.last_read = 0
        self.hard_drop = False


def _build_testris():  # noqa: C901, PLR0915
    # Define the draw_block function
    def draw_block(x, y, index):
        return display_drv.blit_rect(blocks[index], x, y, block_size, block_size)

    # Get the display dimensions
    display_width = display_drv.width
    display_height = display_drv.height

    # If byte swapping is required and the display bus is capable of having byte swapping disabled,
    # disable it and set a flag so we can swap the color bytes as they are created.
    if display_drv.requires_byteswap:
        needs_swap = display_drv.disable_auto_byteswap(True)
    else:
        needs_swap = False

    # define the palette
    class pal:
        BLACK = 0x0000
        WHITE = 0xFFFF
        RED = 0xF800 if not needs_swap else 0x00F8
        GREEN = 0x07E0 if not needs_swap else 0xE007
        BLUE = 0x001F if not needs_swap else 0xF800
        CYAN = 0x07FF if not needs_swap else 0xFF07
        MAGENTA = 0xF81F if not needs_swap else 0x1FF8
        YELLOW = 0xFFE0 if not needs_swap else 0xE0FF
        ORANGE = 0xFD20 if not needs_swap else 0x20FD
        PURPLE = 0x8010 if not needs_swap else 0x1080
        GREY = 0x8410 if not needs_swap else 0x1084

    # Define other constants
    try:
        import pydevices_test_mode

        show_splash_screen = not pydevices_test_mode.ENABLED
    except ImportError:
        show_splash_screen = True

    SPLASH_ENABLED = const(1)  # Set to 1 to show the splash screen, 0 to skip it
    DELAY = const(250)  # Delay in ms so we don't read the keypad too quickly
    SPEEDUP = const(
        25
    )  # Amount of time in ms to reduce the drop time by when a row is cleared (Difficulty)
    BAG_SIZE = const(7)  # Number of random unique pieces to add to the bag at a time, min 1, max 7
    GRID_WIDTH = const(10)
    GRID_HEIGHT = const(20)
    BACKGROUND_INDEX = const(0)  # Index of the background block (black)
    BORDER_INDEX = const(8)  # Index of the border block (gray)
    TOUCH_TARGET_INDEX = const(
        9
    )  # Index of the touch target block (white).  Only used if keypad is a Touchpad.
    ROTCW = const(1)
    ROTCCW = const(-1)

    # Define the blocks
    block_size = min(
        display_width // (GRID_WIDTH + 2), display_height // (GRID_HEIGHT + 4)
    )  # Size in pixels
    block_bevel = block_size // 5  # Width of the beveled edge in pixels

    # Calculate the border dimensions in pixels
    border_width = (GRID_WIDTH + 2) * block_size
    border_height = (GRID_HEIGHT + 2) * block_size

    # Calculate the offsets for the border and grid in pixels
    border_x_offset = (display_width - border_width) // 2  # Center the grid horizontally
    border_y_offset = (
        display_height - border_height
    )  # Align the bottom of the grid with the bottom of the display
    grid_x_offset = border_x_offset + block_size
    grid_y_offset = border_y_offset + block_size

    # Calculate the banner dimensions in pixels
    banner_width = border_width - (
        block_size * 4
    )  # Width of the banner in pixels, leave room for next piece
    banner_height = block_size * 2  # Height of the banner in pixels

    # Define the game pieces and their rotations
    pieces = [
        [[1, 1, 1, 1]],  # I piece (cyan)
        [[2, 2], [2, 2]],  # O piece (yellow)
        [[0, 3, 0], [3, 3, 3]],  # T piece (purple)
        [[4, 4, 0], [0, 4, 4]],  # S piece (blue)
        [[0, 5, 5], [5, 5, 0]],  # Z piece (green)
        [[6, 0, 0], [6, 6, 6]],  # J piece (red)
        [[0, 0, 7], [7, 7, 7]],  # L piece (orange)
    ]

    # Define the splash screen
    splash = [
        [0, 0, 0, 3, 3, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 3, 4, 4, 4, 0, 0, 6, 0, 0],
        [1, 1, 1, 3, 3, 4, 5, 5, 0, 6, 0, 0],
        [0, 1, 2, 2, 3, 4, 5, 0, 5, 6, 7, 7],
        [0, 1, 2, 3, 3, 4, 5, 5, 0, 6, 7, 0],
        [0, 1, 2, 2, 0, 4, 5, 0, 5, 6, 7, 7],
        [0, 1, 2, 0, 0, 0, 5, 0, 5, 0, 0, 7],
        [0, 0, 2, 2, 0, 0, 0, 0, 0, 0, 7, 7],
    ]

    # Create the blocks: black for background, 7 piece colors, gray for border, white for touch targets
    blocks = []
    for color in [
        pal.BLACK,
        pal.CYAN,
        pal.YELLOW,
        pal.PURPLE,
        pal.GREEN,
        pal.BLUE,
        pal.RED,
        pal.ORANGE,
        pal.GREY,
        pal.WHITE,
    ]:
        # Allocate a buffer for the block, 2 bytes per pixel.  Use DMA and internal RAM.
        block = alloc_buffer(block_size * block_size * 2)
        for y in range(block_size):  # Working top to bottom
            for x in range(block_size):  # Then left to right
                if color == pal.BLACK:
                    pixel_color = pal.BLACK  # No border or bevel for black
                elif (
                    x == 0 or x == block_size - 1 or y == 0 or y == block_size - 1
                ):  # Pixel on the border
                    pixel_color = pal.BLACK  # Draw a black border around the block
                # Left or top bevel pixel with even x on even rows, odd x on odd rows
                elif (x < block_bevel or y < block_bevel) and (x & 1 == y & 1):
                    pixel_color = pal.WHITE  # Dither with white on the top and left bevels
                # Right or bottom bevel pixel with even x on even rows, odd x on odd rows
                elif (x > block_size - block_bevel - 1 or y > block_size - block_bevel - 1) and (
                    x & 1 == y & 1
                ):
                    pixel_color = pal.BLACK  # Dither with black on the bottom and right bevels
                else:
                    pixel_color = color  # Fill the block with the specified color
                address = (
                    x + (y * block_size)
                ) * 2  # Address of the pixel in the buffer, 2 bytes per pixel
                block[address] = pixel_color & 0xFF
                block[address + 1] = pixel_color >> 8
        blocks.append(block)

    # Create a frame buffer for text
    text_buffer = alloc_buffer(banner_width * banner_height * 2)
    text_fb = FrameBuffer(text_buffer, banner_width, banner_height, RGB565)

    def draw_banner(text, x=border_x_offset, y=0, color=pal.WHITE, bg_color=pal.BLACK):
        """
        Draw text on the banner.

        Parameters:
        text (str): The text to draw.
        x (int, optional): The horizontal position at which to draw the text.
        y (int, optional): The vertical position at which to draw the text.
        color (int, optional): The color of the text. Defaults to pal.WHITE.
        bg_color (int, optional): The background color of the text. Defaults to pal.BLACK.
        """
        text_fb.fill(bg_color)  # Clear the text buffer
        text_lines = text.split("\n")  # Split the text into lines
        text_y = 4  # Leave a 4 pixel margin at the top
        for text_line in text_lines:  # For each line of text
            text_fb.text(text_line, 0, text_y, color)  # Draw the text in the text buffer
            text_y += 8  # Move down 8 pixels
        display_drv.blit_rect(
            text_buffer, x, y, banner_width, banner_height
        )  # Draw the text buffer on the display

    def show_score(state, message=""):
        """
        Show the score.

        Parameters:
            state: Current round state (_RoundState).
            message (str, optional): The message to display. Defaults to "".

        Returns:
            None
        """
        draw_banner(
            f"{message}\nScore: {state.score:,}\nLines cleared: {state.lines}\nDrop time: {state.drop_time:,} ms"
        )  # Draw the score

    def show_splash():
        """
        Show the splash screen.
        """
        splash_x = (
            display_width - len(splash[0]) * block_size
        ) // 2  # Center the splash screen horizontally
        splash_y = (
            display_height - len(splash) * block_size
        ) // 2  # Center the splash screen vertically
        draw_piece(splash, [0, 0], offset_x=splash_x, offset_y=splash_y)  # Draw the splash screen

    def clear_screen():
        """
        Clear the screen.
        """
        display_drv.fill_rect(0, 0, display_width, display_height, pal.BLACK)  # Clear the screen

    def draw_border():
        """
        Draw the border.
        """
        for x in range(border_x_offset, border_x_offset + border_width, block_size):
            draw_block(x, border_y_offset, BORDER_INDEX)  # Top border
            draw_block(
                x, border_y_offset + border_height - block_size, BORDER_INDEX
            )  # Bottom border
        for y in range(border_y_offset, border_y_offset + border_height, block_size):
            draw_block(border_x_offset, y, BORDER_INDEX)  # Left border
            draw_block(
                border_x_offset + border_width - block_size, y, BORDER_INDEX
            )  # Right border

    def draw_touch_targets():
        """
        Draw the touch targets.
        """
        draw_piece([[TOUCH_TARGET_INDEX] * 4], [GRID_WIDTH // 2 - 2, GRID_HEIGHT])
        for x in [-1, GRID_WIDTH]:
            for y in [-1, (GRID_HEIGHT // 2) - 3, GRID_HEIGHT - 5]:
                draw_piece([[TOUCH_TARGET_INDEX]] * 4, [x, y])

    def save_high_score(score):
        """
        Save the high score to a JSON file.

        Args:
            score (int): The high score to be saved.

        Returns:
            None
        """
        with open("high_score.json", "w") as f:
            dump(score, f)

    def load_high_score():
        """
        Load the high score from the 'high_score.json' file.

        Returns:
            int: The high score value if the file exists, otherwise 0.
        """
        try:
            with open("high_score.json", "r") as f:
                return load(f)
        except OSError:
            return 0



    def sample(population, k):
        """
        Randomly select k items from population without replacement.
        MicroPython doesn't have random.sample(), so approximate it.

        Parameters:
        population (list): The list from which to select items.
        k (int): The number of items to select, <= len(population).

        Returns:
        list: A list of k items randomly selected from the population.
        """
        results = []
        for _ in range(k):
            result = choice(population)
            results.append(result)
            population.remove(result)
        return results

    def rotate(piece, dir):
        """
        Rotate a piece in the specified direction.

        Parameters:
        piece (list): The piece to rotate.
        dir (int): The direction to rotate the piece. 1 for clockwise, -1 for counter-clockwise.

        Returns:
        list: The rotated piece.
        """
        piece = list(zip(*piece))  # Transpose the piece (swap rows with columns)
        # Reverse rows for clockwise rotation, or columns for counter-clockwise
        return (
            [list(reversed(row)) for row in piece]
            if dir > 0
            else [list(row) for row in reversed(piece)]
        )

    def collision(grid, piece, pos, dx, dy, rotation=0):
        """
        Check if moving or rotating a piece would cause a collision.

        Parameters:
        piece (list): The piece to check.
        pos (list): The current position of the piece.
        dx (int): The horizontal displacement to check.
        dy (int): The vertical displacement to check.
        rotation (int, optional): The rotation to check. Defaults to 0.

        Returns:
        bool: True if a collision would occur, False otherwise.
        """
        piece = rotate(piece, rotation) if rotation else piece
        for y, row in enumerate(piece):  # For each row in the piece
            for x, block in enumerate(row):  # For each block in the row
                if block:  # If the block is non-zero
                    if (
                        not (0 <= pos[0] + x + dx < GRID_WIDTH)
                        or not (0 <= pos[1] + y + dy < GRID_HEIGHT)
                        or grid[pos[1] + y + dy][pos[0] + x + dx] != 0
                    ):
                        return True
        return False

    def draw_piece(
        piece, piece_position, index=-1, offset_x=grid_x_offset, offset_y=grid_y_offset
    ):
        """
        Draw a piece at a specified position.

        Parameters:
        piece (list): The piece to draw.
        piece_position (list): The position at which to draw the piece.
        index (int): The index of the piece in the blocks list.
        offset_x (int, optional): The horizontal offset at which to draw the piece. Defaults to grid_x_offset, in pixels.
        offset_y (int, optional): The vertical offset at which to draw the piece. Defaults to grid_y_offset, in pixels.
        """
        for y, row in enumerate(piece):
            for x, block in enumerate(row):
                if block:
                    draw_block(
                        offset_x + (piece_position[0] + x) * block_size,
                        offset_y + (piece_position[1] + y) * block_size,
                        index if index >= 0 else block,
                    )

    high_score = load_high_score()  # Load the high score

    def play(loop):
        nonlocal high_score

        if SPLASH_ENABLED and show_splash_screen:  # Show the splash screen and wait for the user to press a key
            clear_screen()
            yield False  # yield so PyScript can paint / service the event loop
            # Draw splash row-by-row so WASM does not block the browser for one long blit burst.
            splash_x = (display_width - len(splash[0]) * block_size) // 2
            splash_y = (display_height - len(splash) * block_size) // 2
            for y, row in enumerate(splash):
                for x, block in enumerate(row):
                    if block:
                        draw_block(
                            splash_x + x * block_size,
                            splash_y + y * block_size,
                            block,
                        )
                yield False
            draw_banner(
                f"High Score {high_score:,}\n\nPress any key\nto continue.",
                x=(display_width - 5 * block_size) // 2,
                y=(display_height - 2 * block_size),
            )
            display_drv.show()
            # Flat wait loop (no nested generators) — keeps PyScript yielding reliably.
            while True:
                if loop.poll("splash_wait"):
                    yield True
                    return
                keys = _gather_keys()
                if keys:
                    break
                yield False

        while True:  # Outer loop - play the game repeatedly
            #     print("Outer loop")
            state = _RoundState(pieces, GRID_WIDTH, GRID_HEIGHT)
            grid = state.grid
            bag = state.bag
            next_piece = state.next_piece
            score = state.score
            lines = state.lines
            drop_time = state.drop_time
            last_read = state.last_read
            hard_drop = state.hard_drop

            # Initialize the game display and wait for the user to press START
            clear_screen()  # Clear the screen
            draw_border()  # Draw the border
            draw_banner(f"High Score {high_score:,}\n\nPress START\nto play.")
            if str(type(keypad)).find("Touchpad"):  # If we're using the touchpad
                draw_touch_targets()  # Draw the touch targets
            display_drv.show()
            for event in _yield_wait(loop, START):
                if event is True:
                    yield True
                    return
                if event is not False:
                    break

            # Play the game
            show_score(state)  # Show the score
            display_drv.show()
            while True:  # Main game loop
                if loop.poll("main_loop"):
                    yield True
                    return
                #         print("Main game loop")
                current_piece = next_piece  # Set the next piece to the current piece
                current_position = [
                    GRID_WIDTH // 2 - len(current_piece[0]) // 2,
                    0,
                ]  # Start position for the piece
                if collision(grid, current_piece, current_position, 0, 0):  # Check for game over
                    break  # Game over, exit the main loop
                if not bag:  # If the bag is empty, refill it
                    bag = sample(pieces.copy(), BAG_SIZE)  # Fill the bag with random pieces
                next_piece = bag.pop()  # Pull the next piece out of the bag
                draw_piece(next_piece, [7, -3])  # Draw the next piece beside the banner
                last_drop = ticks_ms()  # Time of last automatic drop

                while current_piece:  # Middle loop - while the piece is in play
                    if loop.poll("piece_loop"):
                        yield True
                        return
                    #             print("Redraw piece loop")
                    draw_piece(current_piece, current_position)  # Draw the current piece
                    old_piece = current_piece.copy()  # Save the previous piece
                    old_position = current_position.copy()  # Save the previous position

                    while (
                        current_piece == old_piece and current_position == old_position
                    ):  # Inner loop - while the piece hasn't moved
                        if loop.poll("inner_loop"):
                            yield True
                            return
                        # If it has been DELAY ms since the last read, then read the keypads
                        if (ticks_diff(ticks_ms(), last_read) >= DELAY):
                            keys = _gather_keys()

                            if len(keys) > 0:  # If keys were pressed
                                for key in keys:
                                    last_read = ticks_ms()  # Save the time of the last read
                                    if key == LEFT and not collision(grid, current_piece, current_position, -1, 0):
                                        current_position[0] -= 1  # Move the piece left
                                    elif key == RIGHT and not collision(grid, current_piece, current_position, 1, 0):
                                        current_position[0] += 1  # Move the piece right
                                    elif key == DOWN and not collision(grid, current_piece, current_position, 0, 1):
                                        current_position[1] += 1  # Move the piece down
                                        last_drop = ticks_ms()  # Reset the last drop time
                                    elif key == DROP and not collision(grid, current_piece, current_position, 0, 1):
                                        hard_drop = True  # Hard drop the piece
                                    elif key == CCW and not collision(grid,
                                        current_piece, current_position, 0, 0, ROTCCW
                                    ):
                                        current_piece = rotate(
                                            current_piece, ROTCCW
                                        )  # Rotate the piece counter-clockwise
                                    elif key == CW and not collision(grid,
                                        current_piece, current_position, 0, 0, ROTCW
                                    ):
                                        current_piece = rotate(current_piece, ROTCW)  # Rotate the piece clockwise
                                    elif key == PAUSE:  # Pause the game
                                        draw_banner("Paused.\n\nPress START to reset.\nAny key to resume.")
                                        pause_key = None
                                        for event in _yield_wait(loop, exclude=[PAUSE]):
                                            if event is True:
                                                yield True
                                                return
                                            if event is not False:
                                                pause_key = event
                                                break
                                        if pause_key == START:
                                            clear_screen()  # Clear the screen
                                            exit()  # Reset the machine
                                        else:  # Resume the game
                                            show_score(state)  # Show the score

                        if hard_drop:  # Hard drop the piece
                            while not collision(grid,
                                current_piece, current_position, 0, 1
                            ):  # While the piece hasn't hit bottom
                                if loop.poll("hard_drop"):
                                    yield True
                                    return
                                current_position[1] += 1  # Move the piece down
                            hard_drop = False  # Reset the hard drop flag
                            last_drop = 0  # Unset the last drop time
                        elif ticks_diff(ticks_ms(), last_drop) >= drop_time:  # Automatic drop
                            if not collision(grid, current_piece, current_position, 0, 1):
                                current_position[1] += 1  # Move the piece down
                                last_drop = ticks_ms()  # Reset the last drop time
                            else:  # Piece hit bottom
                                # Add the piece to the grid
                                for y, row in enumerate(current_piece):
                                    for x, block in enumerate(row):
                                        if block:
                                            grid[current_position[1] + y][current_position[0] + x] = (
                                                block  # Add the piece to the grid
                                            )
                                current_piece = (
                                    None  # Piece is no longer in play; its now part of the grid
                                )
                                # Check for full lines
                                full_lines = []
                                for y, row in enumerate(grid):  # Check each row
                                    if all(row):  # If each block in the row is non-zero
                                        full_lines.append(y)  # Add the row to the list of full lines
                                if full_lines:
                                    score += [100, 200, 400, 800][
                                        len(full_lines) - 1
                                    ]  # Update the score
                                    lines += len(full_lines)  # Update the number of lines cleared
                                    drop_time = max(
                                        DELAY, drop_time - SPEEDUP
                                    )  # Decrease the drop time, but not below DELAY time
                                    show_score(state)  # Show the score
                                    old_grid = [
                                        row[:] for row in grid
                                    ]  # Keep a copy of the grid before making any changes
                                    # Shift the remaining lines down
                                    for full_line in full_lines:  # For each full line
                                        for y in range(
                                            full_line, 0, -1
                                        ):  # Working from the full line up to the top
                                            grid[y] = list(grid[y - 1])  # Copy the line above it
                                        grid[0] = [0 for _ in range(GRID_WIDTH)]  # Clear the top line
                                    # Redraw only the lines that have changed
                                    for y in range(GRID_HEIGHT):  # For each line
                                        if grid[y] != old_grid[y]:  # If the line has changed
                                            for x in range(GRID_WIDTH):  # For each block in the line
                                                draw_block(
                                                    x * block_size + grid_x_offset,
                                                    y * block_size + grid_y_offset,
                                                    grid[y][x],
                                                )

                        display_drv.show()
                        yield False

                    if (
                        current_piece
                    ):  # If the piece hasn't hit bottom, erase it from its previous position
                        draw_piece(old_piece, old_position, BACKGROUND_INDEX)

                draw_piece(next_piece, [7, -3], BACKGROUND_INDEX)  # Erase the previous next piece

            # Game over - show the score and wait for the user to press a key
            if score > high_score:
                save_high_score(score)
                high_score = score
                message = "New high score!"
            else:
                message = "Game over!"
            show_score(state, message)  # Show the score
            display_drv.show()
            for event in _yield_wait(loop, START):
                if event is True:
                    yield True
                    return
                if event is not False:
                    break

    return play


_game = None


def _get_game():
    global _game
    if _game is None:
        _game = _build_testris()
    return _game


def _play_poll(play):
    try:
        return next(play)
    except StopIteration:
        return True


def _start_play():
    return _get_game()(_Loop())


play = _start_play()


def _tick(_=None):
    if _play_poll(play):
        app.request_quit()


app.every(_tick, period=20, async_=app.timer_async)