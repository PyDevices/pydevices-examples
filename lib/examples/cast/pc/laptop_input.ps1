# Drive the Wireless Display window from the laptop itself: relative mouse
# moves in a square with five clicks, then keys h, i, Right, Enter. Run it
# while cast.laptop_input is casting, after the session reaches PLAY:
#   powershell -ExecutionPolicy Bypass -File laptop_input.ps1
# The P4's log should show five "click at" lines at the square's corners and
# centre and the four keys.
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, int dx, int dy, uint data, UIntPtr extra);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
"@
Add-Type -AssemblyName System.Windows.Forms
$proc = Get-Process ApplicationFrameHost -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -match 'Wireless|PyDevices|project' } | Select-Object -First 1
if (-not $proc) { Write-Output "no receiver window"; exit 1 }
$h = $proc.MainWindowHandle
[Win]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero); [void][Win]::SetForegroundWindow($h); [Win]::keybd_event(0x12, 0, 2, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 800
if ([Win]::GetForegroundWindow() -ne $h) { Write-Output "could not bring the receiver to the foreground"; exit 2 }
$r = New-Object Win+RECT; [void][Win]::GetWindowRect($h, [ref]$r)
[void][Win]::SetCursorPos([int](($r.L + $r.R) / 2), [int](($r.T + $r.B) / 2))
Start-Sleep -Milliseconds 300
function MoveBy($dx, $dy, $steps) { for ($i = 0; $i -lt $steps; $i++) { [Win]::mouse_event(0x0001, $dx, $dy, 0, [UIntPtr]::Zero); Start-Sleep -Milliseconds 25 } }
function Click() { [Win]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero); Start-Sleep -Milliseconds 120; [Win]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero); Start-Sleep -Milliseconds 300 }
MoveBy -8 -6 25; Click            # up-left, click
MoveBy 16 0 25; Click             # right, click
MoveBy 0 12 25; Click             # down, click
MoveBy -16 0 25; Click            # left, click
MoveBy 8 -6 25; Click             # back to the middle, click
Write-Output "moved a square with five clicks"
Start-Sleep -Milliseconds 400
[System.Windows.Forms.SendKeys]::SendWait("hi")
Start-Sleep -Milliseconds 300
[System.Windows.Forms.SendKeys]::SendWait("{RIGHT}{ENTER}")
Write-Output "typed h, i, Right, Enter"
