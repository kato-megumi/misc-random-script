#Requires AutoHotkey v2.0
#SingleInstance force

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

XButton1::MyMenu.Show()

RunPCResolution(*) {
    ChangeResolution(3840, 2160)
}

RunMacResolution(*) {
    ChangeResolution(3024, 1890)
}

RunTabletResolution(*) {
    ChangeResolution(2560, 1600)
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