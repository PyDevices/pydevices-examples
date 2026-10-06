sub Main(args as Dynamic)
    print "PyDevices Companion launched"
    
    screen = CreateObject("roSGScreen")
    m.port = CreateObject("roMessagePort")
    screen.setMessagePort(m.port)
    
    input = CreateObject("roInput")
    if input <> invalid then input.setMessagePort(m.port)
    
    scene = screen.CreateScene("CompanionScene")
    screen.show()
    
    ' Pass all args to the scene
    scene.launchArgs = args
    
    while(true)
        msg = wait(0, m.port)
        msgType = type(msg)
        if msgType = "roSGScreenEvent"
            if msg.isScreenClosed() then return
        else if msgType = "roInputEvent"
            if msg.isInput()
                print "[Main] roInputEvent received: "; msg.getInfo()
                scene.launchArgs = msg.getInfo()
            end if
        end if
    end while
end sub
