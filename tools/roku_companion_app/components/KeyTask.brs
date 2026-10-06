sub init()
    m.top.functionName = "run"
end sub

sub run()
    port = CreateObject("roMessagePort")
    m.top.observeField("key", port)
    ' One transfer object for every key, so its connection is reused.
    xfer = CreateObject("roUrlTransfer")
    while true
        msg = wait(0, port)
        if type(msg) = "roSGNodeEvent"
            url = m.top.url
            if url <> ""
                xfer.SetUrl(url + "?" + msg.getData())
                xfer.GetToString()
            end if
        end if
    end while
end sub
