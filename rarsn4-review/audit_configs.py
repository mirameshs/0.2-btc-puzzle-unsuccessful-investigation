"""Inspect downloaded text/configuration data, without running remote code."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import puzzle_solver as solver

data = json.loads((ROOT/'rarsn4-review/text-snapshot.json').read_text())
prefix = 'moon tower food this real subject address total ten black'.split()
results = []
for name, body in data.items():
    if not name.endswith('.conf'):
        continue
    parsed = {}
    for line in body.splitlines():
        tokens = line.split('#', 1)[0].split()
        if tokens:
            parsed.setdefault(tokens[0], []).append(tokens[1:])
    if parsed.get('TARGET', [[None]])[0][0] != solver.TARGET:
        continue
    length = int(parsed.get('WORDS', [['12']])[0][0])
    if length != 12:
        continue
    pool = {w for row in parsed.get('POOL', []) for w in row}
    slots = {int(row[0]): row[1:] for row in parsed.get('SLOT', [])}
    compatible = True
    mismatches = []
    for i, word in enumerate(prefix, 1):
        options = slots.get(i, []) if slots else list(pool)
        allowed = set('|'.join(options).split('|'))
        if '@POOL' in allowed:
            allowed |= pool
        if '@FULL' not in allowed and word not in allowed:
            compatible = False
            mismatches.append(i)
    results.append({'file': name, 'prefix_compatible': compatible, 'mismatch_positions': mismatches,
                    'paths': parsed.get('PATH', []),
                    'note': 'Compatibility of published vocabulary/slots only; not proof of a completed run.'})

words = (ROOT/'bip39-english-all.txt').read_text(encoding='utf-8-sig').split()
index = {w:i for i,w in enumerate(words)}
short_phrase = next(['act']*23+[w] for w in words if solver.checksum(['act']*23+[w], index))
report = {
    'config_count': sum(n.endswith('.conf') for n in data),
    'homelessphd_prefix': ' '.join(prefix),
    'compatible_published_12_word_configs': [r['file'] for r in results if r['prefix_compatible']],
    'inspected_12_word_puzzle_configs': results,
    'black_move_files_published': [n for n in data if n.endswith('.conf') and 'black' in n.lower()],
    'word_indices': {w: {'zero_based':index[w], 'one_based':index[w]+1} for w in ['they','that','time']},
    'counterexample_to_all_24_word_phrases_exceed_128_bytes': {
        'phrase': ' '.join(short_phrase), 'byte_length': len(' '.join(short_phrase).encode()),
        'valid_bip39_checksum': True, 'is_puzzle_solution': False,
    },
    'remote_code_executed': False,
}
(ROOT/'rarsn4-review/audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
