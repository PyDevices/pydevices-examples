sub init()
    m.statusLabel = m.top.findNode("statusLabel")
    m.cameraView1 = m.top.findNode("cameraView1")
    m.cameraView2 = m.top.findNode("cameraView2")
    m.cameraTimer = m.top.findNode("cameraTimer")
    m.cameraTimer.observeField("fire", "onCameraTimerFired")
    m.cameraView1.observeField("loadStatus", "onCameraLoadStatusChanged")
    m.cameraView2.observeField("loadStatus", "onCameraLoadStatusChanged")
    
    m.keyTask = CreateObject("roSGNode", "KeyTask")
    m.keyTask.control = "run"

    m.tts = CreateObject("roTextToSpeech")
    m.audioPlayer = m.top.findNode("audioPlayer")
    
    m.top.setFocus(true)
    
    m.cameraUrl = ""
    m.frameCount = 0
    m.activeBuffer = 1
    m.isLoading = false
    ' No frame for this long means the PyDevices app has gone (crashed,
    ' killed, or the computer slept), so the channel closes. A live app
    ' delivers one at least every second or so; a dead one's fetches can
    ' take ten seconds just to fail, so this is timed, not counted.
    m.goneAfterMs = 5000
    m.sinceFrame = CreateObject("roTimespan")
    print "[CompanionScene] initialized"
end sub

sub onLaunchArgsChanged()
    args = m.top.launchArgs
    if args = invalid
        print "[CompanionScene] launchArgs is invalid"
        return
    end if
    
    mode = args.mode
    print "[CompanionScene] onLaunchArgsChanged: mode="; mode
    
    if mode = "tts"
        m.statusLabel.text = "TTS: " + args.text
        m.statusLabel.visible = true
        m.cameraView1.visible = false
        m.cameraView2.visible = false
        m.cameraTimer.control = "stop"
        m.cameraUrl = ""
        m.keyTask.url = ""
        print "[CompanionScene] TTS text: "; args.text
        
        if m.tts <> invalid
            m.tts.Say(args.text)
        end if
        
    else if mode = "audio"
        m.statusLabel.visible = true
        m.cameraView1.visible = false
        m.cameraView2.visible = false
        m.cameraTimer.control = "stop"
        m.cameraUrl = ""
        m.keyTask.url = ""
        m.statusLabel.text = "Streaming Audio..."
        print "[CompanionScene] Audio URL: "; args.url
        
        m.audioPlayer.control = "stop"
        
        audioContent = CreateObject("roSGNode", "ContentNode")
        audioContent.url = args.url
        audioContent.streamFormat = "wav"
        m.audioPlayer.content = audioContent
        
        m.audioPlayer.control = "play"
        
    else if mode = "camera"
        m.statusLabel.visible = false
        m.cameraView1.visible = false
        m.cameraView2.visible = false
        m.cameraUrl = args.url
        m.sinceFrame.Mark()
        ' Remote buttons go to the server that serves the frames.
        m.keyTask.url = Left(args.url, Instr(9, args.url, "/") - 1) + "/key"
        m.frameCount = 0
        m.activeBuffer = 1
        m.isLoading = false
        m.cameraTimer.control = "start"
        print "[CompanionScene] Camera URL: "; args.url
        
    else if mode = "quit"
        ' Sent by a PyDevices app on its way out.
        m.top.exitChannel = true

    else if mode = "dashboard"
        m.statusLabel.visible = true
        m.cameraView1.visible = false
        m.cameraView2.visible = false
        m.cameraTimer.control = "stop"
        m.cameraUrl = ""
        m.keyTask.url = ""
        m.statusLabel.text = args.text
        print "[CompanionScene] Dashboard text: "; args.text
    end if
    
end sub

sub onCameraTimerFired()
    ' Fallback only: frames are requested as soon as the previous one is ready.
    ' The timer restarts the chain after a failed load, and notices when the
    ' app has gone.
    if m.cameraUrl <> "" and m.sinceFrame.TotalMilliseconds() >= m.goneAfterMs
        print "[CompanionScene] no frame for "; m.sinceFrame.TotalMilliseconds(); " ms, closing"
        m.cameraUrl = ""
        m.cameraTimer.control = "stop"
        m.top.exitChannel = true
        return
    end if
    if not m.isLoading then requestFrame()
end sub

sub requestFrame()
    if m.cameraUrl = "" then return
    m.frameCount = m.frameCount + 1
    ' Append cache-busting parameter
    sep = "?"
    if Instr(1, m.cameraUrl, "?") > 0 then sep = "&"

    uri = m.cameraUrl + sep + "t=" + m.frameCount.toStr()
    m.isLoading = true

    if m.activeBuffer = 1
        m.cameraView2.uri = uri
    else
        m.cameraView1.uri = uri
    end if

    if m.frameCount = 1 or (m.frameCount mod 25 = 0)
        print "[CompanionScene] Requesting frame #"; m.frameCount; " -> "; uri
    end if
end sub

sub onCameraLoadStatusChanged(event as Object)
    node = event.getRoSGNode()
    status = node.loadStatus
    id = node.id
    
    if status = "ready"
        if id = "cameraView1"
            m.cameraView1.visible = true
            m.cameraView2.visible = false
            m.activeBuffer = 1
        else if id = "cameraView2"
            m.cameraView2.visible = true
            m.cameraView1.visible = false
            m.activeBuffer = 2
        end if
        m.isLoading = false
        m.sinceFrame.Mark()
        requestFrame()
    else if status = "failed"
        print "[CompanionScene] cameraView loadStatus="; status; " for "; node.uri
        m.isLoading = false
        m.statusLabel.text = "Error: Failed to load camera frame from\n" + m.cameraUrl
        m.statusLabel.visible = true
    end if
end sub

' While frames are streaming, every remote button the TV lets a channel see goes
' to the PyDevices app, Back included (Home always leaves the channel).
function onKeyEvent(key as String, press as Boolean) as Boolean
    if m.cameraUrl = "" then return false
    p = "0"
    if press then p = "1"
    m.keyTask.key = "k=" + key + "&p=" + p
    return true
end function
