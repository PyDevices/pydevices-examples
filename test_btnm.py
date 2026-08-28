import traceback

with open("result.txt", "w") as f:
    try:
        import display_driver
        import lvgl as lv

        scr = lv.screen_active()
        bm = lv.buttonmatrix(scr)
        map_list = ["1", "2", ""]
        try:
            bm.set_map(map_list)
            f.write("list worked\n")
        except Exception as e:
            f.write("list failed: " + str(e) + "\n")

        import ctypes

        arr = (ctypes.c_char_p * len(map_list))()
        for i, s in enumerate(map_list):
            arr[i] = s.encode("utf-8") if s else None
        try:
            bm.set_map(arr)
            f.write("ctypes worked\n")
        except Exception as e:
            f.write("ctypes failed: " + str(e) + "\n")

    except Exception as e:
        f.write("Fatal: " + str(e) + "\n")
        traceback.print_exc(file=f)
