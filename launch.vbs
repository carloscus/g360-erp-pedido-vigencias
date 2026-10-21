' ============================================================
'  g360-erp-pedido-vigencias - Ejecutar sin consola
'  Drill limpio: Vendedores -> Clientes -> Pedidos -> SKUs
'  Lanza build.bat fast (salta setup si .venv\.g360_ready existe)
'  y oculta la consola (0=oculta). Doble-click este archivo para
'  iniciar la app como acceso directo.
' ============================================================
Option Explicit

Dim WshShell, fso, scriptDir, cmd, rc

On Error Resume Next

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
If scriptDir = "" Then scriptDir = fso.GetAbsolutePathName(".")

WshShell.CurrentDirectory = scriptDir

' Verificar que build.bat existe antes de lanzar
If Not fso.FileExists(fso.BuildPath(scriptDir, "build.bat")) Then
    MsgBox "No se encontro build.bat en:" & vbCrLf & scriptDir, 16, "g360-erp-pedido-vigencias"
    WScript.Quit 1
End If

cmd = "cmd /c build.bat fast"
rc = WshShell.Run(cmd, 0, False)

If Err.Number <> 0 Then
    MsgBox "Error al lanzar la app: " & Err.Description, 16, "g360-erp-pedido-vigencias"
End If

Set WshShell = Nothing
Set fso = Nothing
