"""Read-only audit: parse the downloaded source without executing it."""
import ast
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import puzzle_solver as solver

folder = ROOT / 'homelessphd-review'
source = (folder / 'source.py.txt').read_text(encoding='utf-8-sig')
result = {}
for version in (11, 12, 13):
    try:
        ast.parse(source, feature_version=(3, version))
        result[f'python_3_{version}'] = 'parses'
    except SyntaxError as error:
        result[f'python_3_{version}'] = {'error': error.msg, 'line': error.lineno}
official = (ROOT / 'bip39-english-all.txt').read_text(encoding='utf-8-sig').split()
remote_words = (folder / 'english.txt').read_text(encoding='utf-8-sig').split()
prefix = 'moon tower food this real subject address total ten black'
node = solver.master(solver.seed_for('abandon ' * 23 + 'art', ''))
for part in solver.parse_path("m/44'/0'/0'/0/0"):
    node = solver.child(node, part)
result.update(
    wordlist_identical=official == remote_words,
    wordlist_count=len(remote_words),
    prefix_words_valid=all(word in official for word in prefix.split()),
    prefix=prefix,
    search_cases=2048**2,
    checksum_valid_completions=2048**2//16,
    address_checks_if_all_valid_completions=2048**2//16 * 2 * 10 * 2,
    our_24_word_control_address=solver.base58check(b'\0' + solver.hash160(solver.public(node[0]))),
)
(folder / 'audit.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result, indent=2))
