set PROJECT_NAME=main
set SIGNTOOL_PATH="setup/signtool.exe"
set CERT_PATH="setup/mycert.pfx"
set TIMESTAMP_SERVER=http://timestamp.digicert.com
set EXEC_NAME="dist/CAU159.exe"

REM INSTALL
pyinstaller %PROJECT_NAME%.spec

REM PYARMOR
pyarmor gen --pack %PROJECT_NAME%.spec -r main.py Common/ Function/ Service/

::REM PFX CODESIGN
::%SIGNTOOL_PATH% sign /f %CERT_PATH% /p %CERT_PASSWORD% /tr %TIMESTAMP_SERVER% /td sha256 /as /fd sha256 %EXEC_NAME%

::REM VERIFY
::%SIGNTOOL_PATH% verify /pa /v %EXEC_NAME%
