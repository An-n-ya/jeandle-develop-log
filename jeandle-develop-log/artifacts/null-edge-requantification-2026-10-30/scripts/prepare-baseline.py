import subprocess
from pathlib import Path
root=Path('/home/annya/playground/jeandle/jeandle/jeandle-llvm-null-edge-baseline')
files=['llvm/include/llvm/Analysis/Jeandle/JavaTypeAnalysis.h','llvm/lib/Analysis/Jeandle/JavaTypeAnalysis.cpp']+[f'llvm/lib/Transforms/Jeandle/{name}.cpp' for name in ['CHADevirtualization','ConstantFieldFolding','RecoverTypeInfo','TypeCheckElimination']]
for name in files:
    s=subprocess.check_output(['git','show','e5475bb0df46:'+name],cwd=root).decode()
    if name.endswith('JavaTypeAnalysis.cpp'):
        for line in ['    uint64_t BudgetBefore = getNullEdgeOracleBudgetExhaustionCount();\n','    uint64_t BudgetAfterReference = getNullEdgeOracleBudgetExhaustionCount();\n','    uint64_t BudgetAfterFresh = getNullEdgeOracleBudgetExhaustionCount();\n']:
            s=s.replace(line,'')
        s=s.replace('    else if (BudgetBefore != BudgetAfterReference ||\n             BudgetAfterReference != BudgetAfterFresh)\n      VerificationSkipped = true;\n','')
    (root/name).write_text(s)
subprocess.run(['git','add',*files],cwd=root,check=True)
subprocess.run(['git','commit','-m','Align non-NullEdge controls for isolated performance baseline'],cwd=root,check=True)
