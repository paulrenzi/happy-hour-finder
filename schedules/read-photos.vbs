' Hidden launcher for read-photos.bat.
'
' Window style 0 is not a detail: this runs every five minutes, so a visible
' console would be a black window over a game twelve times an hour. Same
' pattern as every other scheduled job on this machine.
CreateObject("WScript.Shell").Run "C:\Users\paulm\happy-hour-finder\schedules\read-photos.bat", 0, False
