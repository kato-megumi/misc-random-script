#Requires AutoHotkey v2.0
#SingleInstance force

; Register the MagpieScalingChanged message
WM_MAGPIE_SCALINGCHANGED := DllCall("RegisterWindowMessage", "Str", "MagpieScalingChanged", "UInt")

currentTrail := 2
full_command_line := DllCall("GetCommandLine", "str")
scrollDisabled := false
suspendedPid := 0

; Add message filter to allow the Magpie message for all messages
DllCall("user32.dll\ChangeWindowMessageFilterEx", 
    "Ptr", A_ScriptHwnd,
    "UInt", WM_MAGPIE_SCALINGCHANGED,
    "UInt", 1,  ; MSGFLT_ADD
    "Ptr", 0)

OnMessage(WM_MAGPIE_SCALINGCHANGED, OnMagpieScalingChanged)


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
    global suspendedPid
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
    ; Show only relevant Suspend/Resume based on process state
    if !IsProcessExist(suspendedPid) {
        MyMenu.Add("No process", MenuNoop)
        MyMenu.Disable("No process")
    } else {
        suspended := IsProcessSuspended(suspendedPid)
        if suspended {
            MyMenu.Add("Resume Program", SuspendOrResumeProgram)
        } else {
            MyMenu.Add("Suspend Program", SuspendOrResumeProgram)
        }
    }
    MyMenu.Add()
    MyMenu.Add("Mouse Trail", MouseTrail)
    MyMenu.Add()
    MyMenu.Add("Reset Windows", ResetWindows)
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
    global currentTrail
    currentTrail := length
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


OnMagpieScalingChanged(wParam, lParam, msg, hwnd) {
    global suspendedPid
    ; log to file
    FileAppend(FormatTime(, "yyyy-MM-dd HH:mm:ss") . " MagpieScalingChanged: " . wParam . " : " . lParam . "`n", "MagpieScalingChanged.log")
    SetPointerTrail(wParam == 1 ? 0 : 2)
    if (wParam == 1) {
        SetPointerTrail(0)
        Sleep(200)
        suspendedPid := WinGetPID("A")
    } else {
        SetPointerTrail(2)
    }
}

; SetWinEventHook(0x0003, 0x0003, 0, CallbackCreate(OnWindowChange), 0, 0, 0) ; EVENT_SYSTEM_FOREGROUND
; OnWindowChange(hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime) {    
;     ; If pointer trail is 0, set it to 2
;     if (currentTrail == 0) {
;         SetPointerTrail(2)
;     }
; }
; SetWinEventHook(eventMin, eventMax, hmodWinEventProc, lpfnWinEventProc, idProcess, idThread, dwFlags) {
;     return DllCall("SetWinEventHook", "UInt", eventMin, "UInt", eventMax, "Ptr", hmodWinEventProc, "Ptr", lpfnWinEventProc, "UInt", idProcess, "UInt", idThread, "UInt", dwFlags, "Ptr")
; }


SuspendOrResumeProgram(ItemName, *) {
    global suspendedPid
    hProcess := DllCall("OpenProcess", "UInt", 0x1F0FFF, "Int", false, "UInt", suspendedPid, "Ptr")
    if (hProcess) {
        if (ItemName = "Suspend Program") {
            DllCall("ntdll.dll\NtSuspendProcess", "Ptr", hProcess)
        } else if (ItemName = "Resume Program") {
            DllCall("ntdll.dll\NtResumeProcess", "Ptr", hProcess)
        }
        DllCall("CloseHandle", "Ptr", hProcess)
    }
}

IsProcessExist(pid) {
    if !pid
        return false
    hProcess := DllCall("OpenProcess", "UInt", 0x1000, "Int", false, "UInt", pid, "Ptr")
    if (hProcess) {
        DllCall("CloseHandle", "Ptr", hProcess)
        return true
    }
    return false
}

IsProcessSuspended(pid) {
    ; Returns true if any thread in the process has a suspend count > 0
    if !pid
        return false
    suspended := false
    hSnap := DllCall("kernel32.dll\CreateToolhelp32Snapshot", "UInt", 0x00000004, "UInt", 0, "Ptr") ; TH32CS_SNAPTHREAD
    if (hSnap && hSnap != -1) {
        te := Buffer(28, 0) ; THREADENTRY32
        NumPut("UInt", 28, te, 0)
    if DllCall("kernel32.dll\Thread32First", "Ptr", hSnap, "Ptr", te) {
            loop {
                if (NumGet(te, 12, "UInt") = pid) {
                    tid := NumGet(te, 8, "UInt")
                    hThread := DllCall("kernel32.dll\OpenThread", "UInt", 0x0002, "Int", false, "UInt", tid, "Ptr") ; THREAD_SUSPEND_RESUME
                    if hThread {
                        prev := DllCall("kernel32.dll\SuspendThread", "Ptr", hThread, "UInt")
                        if (prev != 0xFFFFFFFF) {
                            DllCall("kernel32.dll\ResumeThread", "Ptr", hThread)
                            if (prev > 0) {
                                suspended := true
                                DllCall("kernel32.dll\CloseHandle", "Ptr", hThread)
                                break
                            }
                        }
                        DllCall("kernel32.dll\CloseHandle", "Ptr", hThread)
                    }
                }
                if !DllCall("kernel32.dll\Thread32Next", "Ptr", hSnap, "Ptr", te)
                    break
            }
        }
    DllCall("kernel32.dll\CloseHandle", "Ptr", hSnap)
    }
    return suspended
}

; Hotkeys for suspend/resume
; #s::SuspendProgram()
; #r::ResumeProgram()

ResetWindows(*) {
    ; Kill dwm.exe (Desktop Window Manager)
    try {
        ProcessClose("dwm.exe")
    }
    
    ; Restart explorer.exe
    try {
        ProcessClose("explorer.exe")
        Sleep(1000)
        Run("explorer.exe")
    }
}

; Auto-click space and 1 when Caps Lock is on
; SetTimer(CheckCapsLock, 25)

CheckCapsLock() {
    if GetKeyState("CapsLock", "T") {
        ; Send("{Space}1")
        Send("{WheelDown}")
    }
}

; No-op handler for disabled menu items
MenuNoop(*) {
}