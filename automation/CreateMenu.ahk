#Requires AutoHotkey v2.0
#SingleInstance force

full_command_line := DllCall("GetCommandLine", "str")

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

XButton2:: {
    Send("{Alt down}{Tab}")
    KeyWait("XButton2")
    Send("{Alt up}")
}


*WheelLeft::  ; The * prevents any modifiers from affecting the hotkey
{
    global ctrlHeld
    if (!ctrlHeld) {
        ctrlHeld := true
        SendInput("{Ctrl down}")   ; Hold Ctrl
        SetTimer(ReleaseCtrl, -500)  ; Adjust timer as needed
    }
    return  ; Completely blocks WheelLeft from doing anything else
}
ReleaseCtrl() {
    global ctrlHeld
    ctrlHeld := false
    SendInput("{Ctrl up}")  ; Release Ctrl
}


XButton1:: {
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
    ; DllCall("SetProp", "Ptr", MyMenu.Handle, "Str", "Magpie.ToolWindow", "Uint", true)
    MyMenu.Show()
}

RunPCResolution(*) {
    ChangeResolution(3840, 2160)
    Sleep 3000
    RegWrite 1, "REG_DWORD", "HKEY_CURRENT_USER\Control Panel\Desktop\PerMonitorSettings\GSM770670708_02_07E5_A4^EA8C1CDCC9F9DC2110FC52C382EE80CA", "DpiValue"
}

RunMacResolution(*) {
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