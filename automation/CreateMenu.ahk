#Requires AutoHotkey v2.0
#SingleInstance force

full_command_line := DllCall("GetCommandLine", "str")
scrollDisabled := false

if not (A_IsAdmin or RegExMatch(full_command_line, " /restart(?!\S)"))
{
    try
    {
        if A_IsCompiled
            Run '*RunAs "' A_ScriptFullPath '" /restart'
        else
            Run '*RunAs "' A_AhkPath '" /restart "' A_ScriptFullPath '"'
    }
}


+Backspace::Send("{Delete}")

XButton1:: {
    Send("{Ctrl down}")
    KeyWait("XButton1")
    Send("{Ctrl up}")
}


XButton2:: {
    ; Send("{Alt down}{Tab}")
    Send("{Alt down}")
    KeyWait("XButton2")
    Send("{Alt up}")
}

; XButton2::
; {
;     scrollDisabled := true
;     Send("{Alt down}")
; }
; XButton2 Up::
; {
;     scrollDisabled := false
;     Send("{Alt up}")
; }

; ~!WheelUp::
; {
;     if scrollDisabled
;         return  ; Block scrolling
;     else
;         Send("{WheelUp}")  ; Allow normal behavior
; }

; ; Intercept WheelDown when scroll is disabled
; ~!WheelDown::
; {
;     if scrollDisabled
;         return  ; Block scrolling
;     else
;         Send("{WheelDown}")  ; Allow normal behavior
; }

!WheelRight:: {
    WinGetPos(&x, &y, &w, &h, "A")
    WinMove(x, y, 1920 + 26, 1080 + 71, "A")
}
; 1920x1080 -> 1894x1009
; 1950x1080 -> 1824x1009
; !WheelRight::Send("d")


!WheelLeft::Send("{Tab}")
^WheelLeft::Send("Enter")
^WheelRight:: {
    MyMenu := Menu()
    MyMenu.Add("PC Resolution", RunPCResolution)
    MyMenu.Add("Mac Resolution", RunMacResolution)
    MyMenu.Add("Tablet Resolution", RunTabletResolution)
    MyMenu.Add()
    MyMenu.Add("GPU Train", RunGPUTrain)
    MyMenu.Add("GPU Limit", RunGPULimit)
    MyMenu.Add("GPU Full", RunGPUFull)
    MyMenu.Add()
    MyMenu.Add("CPU 99%", RunCPU99)
    MyMenu.Add("CPU 100%", RunCPU100)
    MyMenu.Add()
    MyMenu.Add("Limit", Limit)
    MyMenu.Add("Full", Full)
    MyMenu.Add()
    MyMenu.Add("Mouse Trail", MouseTrail)
    ; DllCall("SetProp", "Ptr", MyMenu.Handle, "Str", "Magpie.ToolWindow", "Uint", true)
    MyMenu.Show()
}

RunPCResolution(*) {
    ChangeResolution(3840, 2160)
    Sleep 3000
    RegWrite 1, "REG_DWORD", "HKEY_CURRENT_USER\Control Panel\Desktop\PerMonitorSettings\GSM770670708_02_07E5_A4^EA8C1CDCC9F9DC2110FC52C382EE80CA", "DpiValue"
}

RunMacResolution(*) {
    MouseTrail()
    ChangeResolution(3024, 1890)
    Sleep 3000
    RegWrite 2, "REG_DWORD", "HKEY_CURRENT_USER\Control Panel\Desktop\PerMonitorSettings\GSM770670708_02_07E5_A4^EA8C1CDCC9F9DC2110FC52C382EE80CA", "DpiValue"
}

RunTabletResolution(*) {
    ChangeResolution(2560, 1600)
    Sleep 3000
    RegWrite 1, "REG_DWORD", "HKEY_CURRENT_USER\Control Panel\Desktop\PerMonitorSettings\GSM770670708_02_07E5_A4^EA8C1CDCC9F9DC2110FC52C382EE80CA", "DpiValue"
}

RunGPULimit(*) {
    run 'C:\Windows\System32\schtasks.exe /RUN /TN "script\gpu_limit"'
}

RunGPUFull(*) {
    run 'C:\Windows\System32\schtasks.exe /RUN /TN "script\gpu_full"'
}

RunCPU99(*) {
    run 'C:\Windows\System32\powercfg.exe /setactive 596f3a20-c523-4d61-afba-2cc57087156a'
}

RunCPU100(*) {
    run 'C:\Windows\System32\powercfg.exe /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c'
}

RunGPUTrain(*) {
    run 'C:\Windows\System32\schtasks.exe /RUN /TN "script\gpu_train"'
}

ChangeResolution(Screen_Width := 3840, Screen_Height := 2160)
{
    Device_Mode:= Buffer(156, 0)
    NumPut("UInt", 156, Device_Mode, 36)
    DllCall("EnumDisplaySettingsA", "UInt", 0, "UInt", -1, "Ptr", Device_Mode)
    NumPut("UInt", 0x5c0000, Device_Mode, 40)
    NumPut("UInt", 32, Device_Mode, 104)
    NumPut("UInt", Screen_Width, Device_Mode, 108)
    NumPut("UInt", Screen_Height, Device_Mode, 112)
    Return DllCall( "ChangeDisplaySettingsA", "Ptr", Device_Mode, "UInt",0 )
}

Limit(*) {
    RunCPU99()
    RunGPULimit()
}

Full(*) {
    RunCPU100()
    RunGPUFull()
}

MouseTrail(*) {
    SetPointerTrail(0)
    Sleep 200
    SetPointerTrail(2)
}

SetPointerTrail(length) {
    ; Define necessary Windows API constants
    static SPI_SETMOUSETRAILS    := 0x005D
    static SPIF_UPDATEINIFILE    := 0x01
    static SPIF_SENDWININICHANGE := 0x02

    ; Call the SystemParametersInfoW function from user32.dll
    DllCall(
        "SystemParametersInfoW",                ; Function and DLL
        "UInt", SPI_SETMOUSETRAILS,             ; Action: Set Mouse Trails
        "UInt", length,                         ; Parameter: Trail length (0 to disable)
        "Ptr", 0,                               ; Parameter: Not used for this action
        "UInt", SPIF_UPDATEINIFILE | SPIF_SENDWININICHANGE ; Flags: Update system files and notify apps
    )
}


; ; Auto-click space and 1 when Caps Lock is on
; SetTimer(CheckCapsLock, 100)

; CheckCapsLock() {
;     if GetKeyState("CapsLock", "T") {
;         Send("{Space}1")
;     }
; }