with open("result_list.txt", "w") as f:
    try:
        import display_driver
        import lvgl as lv

        scr = lv.screen_active()
        lst = lv.list(scr)
        methods = dir(lst)
        f.write("add_btn in methods: " + str("add_btn" in methods) + "\n")
        f.write("add_button in methods: " + str("add_button" in methods) + "\n")
    except Exception as e:
        f.write("Exception: " + str(e) + "\n")
