@echo off

REM Navigate to the directory containing your scripts

cd /d "C:\Program Files (x86)\PlaneWave Instruments\PlaneWave Interface 4\Scripts"


REM Run api_interaction.py and wait for it to finish

"C:\Users\Administrator\AppData\Local\Programs\Python\Python38\python.exe" api_interaction.py

REM After api_interaction.py finishes, run automated2.py

"C:\Users\Administrator\AppData\Local\Programs\Python\Python38\python.exe" automated2.py