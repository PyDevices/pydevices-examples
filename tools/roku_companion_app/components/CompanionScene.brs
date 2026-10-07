sub init()
    m.statusLabel = m.top.findNode("statusLabel")
    m.frameView1 = m.top.findNode("frameView1")
    m.frameView2 = m.top.findNode("frameView2")
    m.frameTimer = m.top.findNode("frameTimer")
    m.frameTimer.observeField("fire", "onFrameTimerFired")
    m.frameView1.observeField("loadStatus", "onFrameLoadStatusChanged")
    m.frameView2.observeField("loadStatus", "onFrameLoadStatusChanged")
    
    m.keyTask = CreateObject("roSGNode", "KeyTask")
    m.keyTask.control = "run"

    m.tts = CreateObject("roTextToSpeech")
    m.audioPlayer = m.top.findNode("audioPlayer")
    m.videoPlayer = m.top.findNode("videoPlayer")
    m.videoPlayer.notificationInterval = 0.5
    m.videoPlayer.observeField("state", "onVideoState")
    m.videoPlayer.observeField("position", "onVideoPosition")
    
    m.top.setFocus(true)
    
    m.frameUrl = ""
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
    if mode <> invalid and mode <> "video" and mode <> "quit" then stopVideo()
    
    if mode = "tts"
        m.statusLabel.text = "TTS: " + args.text
        m.statusLabel.visible = true
        m.frameView1.visible = false
        m.frameView2.visible = false
        m.frameTimer.control = "stop"
        m.frameUrl = ""
        m.keyTask.url = ""
        print "[CompanionScene] TTS text: "; args.text
        
        if m.tts <> invalid
            m.tts.Say(args.text)
        end if
        
    else if mode = "audio"
        m.statusLabel.visible = true
        m.frameView1.visible = false
        m.frameView2.visible = false
        m.frameTimer.control = "stop"
        m.frameUrl = ""
        m.keyTask.url = ""
        m.statusLabel.text = "Streaming Audio..."
        print "[CompanionScene] Audio URL: "; args.url
        
        m.audioPlayer.control = "stop"
        
        audioContent = CreateObject("roSGNode", "ContentNode")
        audioContent.url = args.url
        audioContent.streamFormat = "wav"
        m.audioPlayer.content = audioContent
        
        m.audioPlayer.control = "play"
        
    else if mode = "frames"
        m.statusLabel.visible = false
        m.frameView1.visible = false
        m.frameView2.visible = false
        m.frameUrl = args.url
        m.sinceFrame.Mark()
        ' Remote buttons go to the server that serves the frames.
        m.keyTask.url = Left(args.url, Instr(9, args.url, "/") - 1) + "/key"
        m.frameCount = 0
        m.activeBuffer = 1
        m.isLoading = false
        m.frameTimer.control = "start"
        print "[CompanionScene] Frames URL: "; args.url
        
    else if mode = "video"
        ' Play H.264 from a URL. Reports state and position to /video on
        ' the server that sent it, so the sender can measure the delay.
        m.statusLabel.visible = false
        m.frameView1.visible = false
        m.frameView2.visible = false
        m.frameTimer.control = "stop"
        m.frameUrl = ""
        m.keyTask.url = Left(args.url, Instr(9, args.url, "/") - 1) + "/video"
        content = CreateObject("roSGNode", "ContentNode")
        content.url = args.url
        content.streamFormat = "hls"
        if args.format <> invalid then content.streamFormat = args.format
        content.live = true
        m.videoPlayer.content = content
        m.videoPlayer.visible = true
        m.videoPlayer.control = "play"
        print "[CompanionScene] Video URL: "; args.url

    else if mode = "quit"
        ' Sent by a PyDevices app on its way out.
        m.top.exitChannel = true

    else if mode = "dashboard"
        m.statusLabel.visible = true
        m.frameView1.visible = false
        m.frameView2.visible = false
        m.frameTimer.control = "stop"
        m.frameUrl = ""
        m.keyTask.url = ""
        m.statusLabel.text = args.text
        print "[CompanionScene] Dashboard text: "; args.text

    else if mode <> invalid
        ' A mode this channel doesn't have, such as one from an older
        ' PyDevices app: say so on the screen rather than ignore it.
        m.statusLabel.text = "Unknown mode: " + mode
        m.statusLabel.visible = true
        m.frameView1.visible = false
        m.frameView2.visible = false
        m.frameTimer.control = "stop"
        m.frameUrl = ""
        m.keyTask.url = ""
        print "[CompanionScene] unknown mode: "; mode
    end if
    
end sub

sub onFrameTimerFired()
    ' Fallback only: frames are requested as soon as the previous one is ready.
    ' The timer restarts the chain after a failed load, and notices when the
    ' app has gone.
    if m.frameUrl <> "" and m.sinceFrame.TotalMilliseconds() >= m.goneAfterMs
        print "[CompanionScene] no frame for "; m.sinceFrame.TotalMilliseconds(); " ms, closing"
        m.frameUrl = ""
        m.frameTimer.control = "stop"
        m.top.exitChannel = true
        return
    end if
    if not m.isLoading then requestFrame()
end sub

sub requestFrame()
    if m.frameUrl = "" then return
    m.frameCount = m.frameCount + 1
    ' Append cache-busting parameter
    sep = "?"
    if Instr(1, m.frameUrl, "?") > 0 then sep = "&"

    uri = m.frameUrl + sep + "t=" + m.frameCount.toStr()
    m.isLoading = true

    if m.activeBuffer = 1
        m.frameView2.uri = uri
    else
        m.frameView1.uri = uri
    end if

    if m.frameCount = 1 or (m.frameCount mod 25 = 0)
        print "[CompanionScene] Requesting frame #"; m.frameCount; " -> "; uri
    end if
end sub

sub onFrameLoadStatusChanged(event as Object)
    node = event.getRoSGNode()
    status = node.loadStatus
    id = node.id
    
    if status = "ready"
        if id = "frameView1"
            m.frameView1.visible = true
            m.frameView2.visible = false
            m.activeBuffer = 1
        else if id = "frameView2"
            m.frameView2.visible = true
            m.frameView1.visible = false
            m.activeBuffer = 2
        end if
        m.isLoading = false
        m.sinceFrame.Mark()
        requestFrame()
    else if status = "failed"
        print "[CompanionScene] frameView loadStatus="; status; " for "; node.uri
        m.isLoading = false
        m.statusLabel.text = "Error: Failed to load a frame from\n" + m.frameUrl
        m.statusLabel.visible = true
    end if
end sub

' While frames are streaming, every remote button the TV lets a channel see goes
' to the PyDevices app, Back included (Home always leaves the channel).
function onKeyEvent(key as String, press as Boolean) as Boolean
    if m.frameUrl = "" then return false
    p = "0"
    if press then p = "1"
    m.keyTask.key = "k=" + key + "&p=" + p
    return true
end function

sub stopVideo()
    if m.videoPlayer.visible
        m.videoPlayer.control = "stop"
        m.videoPlayer.visible = false
    end if
end sub

sub onVideoState()
    state = m.videoPlayer.state
    report = "state=" + state
    if state = "error"
        report = report + "&code=" + m.videoPlayer.errorCode.toStr() + "&msg=" + m.videoPlayer.errorMsg.EncodeUriComponent()
    end if
    print "[CompanionScene] video "; report
    if m.keyTask.url <> "" then m.keyTask.key = report
end sub

sub onVideoPosition()
    if m.keyTask.url <> "" then m.keyTask.key = "pos=" + m.videoPlayer.position.toStr()
end sub
