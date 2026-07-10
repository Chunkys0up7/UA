# Audit chain verification CLI (specs/11 §5, specs/16 §4).
#   powershell -ExecutionPolicy Bypass -File scripts\verify-audit.ps1
$repo = Split-Path -Parent $PSScriptRoot
& "$repo\backend\.venv\Scripts\python.exe" -c @"
import sys
sys.path.insert(0, r'$repo\backend')
from app.audit.verify import verify_chain
result = verify_chain(r'$repo\data\db\audit.db')
if result.ok:
    print(f'CHAIN VERIFIED: {result.events} events, no tampering detected')
else:
    print(f'INTEGRITY FAILURE at seq {result.first_broken_seq}')
    print(f'  expected: {result.expected_hash}')
    print(f'  stored:   {result.stored_hash}')
    sys.exit(1)
"@
