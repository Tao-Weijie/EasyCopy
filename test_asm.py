import System.Reflection
try:
    asm = System.Reflection.Assembly.Load("Python.Runtime")
    print(asm.FullName)
except Exception as e:
    print(e)
