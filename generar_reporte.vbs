' ============================================================
'  g360-erp-pedido-vigencias - Generar reporte de acciones
'  Doble click para generar el reporte sin consola visible.
'  Muestra el resultado en un dialogo y abre el escritorio.
' ============================================================
Option Explicit

Dim WshShell, fso, scriptDir, cmd, rc, shell

On Error Resume Next

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("Shell.Application")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
If scriptDir = "" Then scriptDir = fso.GetAbsolutePathName(".")
WshShell.CurrentDirectory = scriptDir

' Preferir el entorno del proyecto (no depende del python del PATH)
Dim pyPath
pyPath = fso.BuildPath(scriptDir, ".venv\Scripts\python.exe")

cmd = "cmd /c "
If fso.FileExists(pyPath) Then
    cmd = cmd & """" & pyPath & """ reporte.py"
Else
    cmd = cmd & "py reporte.py"
End If

rc = WshShell.Run(cmd, 1, True)

If Err.Number <> 0 Then
    MsgBox "Error al generar el reporte: " & Err.Description, 16, "Reporte vigencias"
ElseIf rc = 0 Then
    WshShell.Popup "Reporte generado en el escritorio.", 4, "Reporte vigencias", 64
    shell.Explore scriptDir
Else
    MsgBox "El reporte no se genero (codigo " & rc & ")." & vbCrLf & _
           "Revisa que el archivo de vigencias este en el escritorio.", 48, _
           "Reporte vigencias"
End If

Set WshShell = Nothing
Set fso = Nothing
Set shell = Nothing
