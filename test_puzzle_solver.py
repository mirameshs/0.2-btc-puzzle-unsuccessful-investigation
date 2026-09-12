import itertools
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

import puzzle_solver as solver


class SolverTests(unittest.TestCase):
    def setUp(self):
        self.spec, self.total, self.signature, self.index = solver.load_config(solver.ROOT / 'puzzle-search.json')

    def test_crypto_vectors(self):
        solver.self_test()
        vectors = json.loads((solver.ROOT / 'bip39-test-vectors.json').read_text(encoding='utf-8-sig'))['english']
        for entropy, phrase, seed, xprv in vectors:
            self.assertTrue(solver.checksum(phrase.split(), self.index))
            actual = solver.seed_for(phrase, 'TREZOR')
            self.assertEqual(actual.hex(), seed)
            key, chain = solver.master(actual)
            self.assertEqual(solver.base58check(bytes.fromhex('0488ade4') + b'\0'*9 + chain + b'\0' + key.to_bytes(32, 'big')), xprv)

    def test_permutation_unranking_with_subset_and_fixed(self):
        spec = {'mode': 'permutations', 'word_count': 4, 'fixed': {1: 'black'},
                'remaining': ['moon', 'tower', 'food', 'real'], 'free': [0, 2, 3]}
        expected = [[p[0], 'black', p[1], p[2]] for p in itertools.permutations(spec['remaining'], 3)]
        self.assertEqual([solver.candidate_at(spec, i) for i in range(24)], expected)

    def test_slots_rotations_and_reverse(self):
        spec = {'mode': 'slots', 'word_count': 3, 'slots': [['moon', 'food'], ['tower'], ['black', 'real']],
                'rotations': True, 'reverse': True}
        expected = []
        for product in itertools.product(*spec['slots']):
            for words in (list(product), list(product)[::-1]):
                for n in range(3):
                    expected.append(words[n:] + words[:n])
        self.assertEqual([solver.candidate_at(spec, i) for i in range(len(expected))], expected)

    def test_config_and_fixed_position(self):
        self.assertEqual(self.total, 39916800)
        for rank in (0, 1, 999, self.total - 1):
            words = solver.candidate_at(self.spec, rank)
            self.assertEqual(words[9], 'black')
            self.assertEqual(len(set(words)), 12)

    def test_exact_match_and_wrong_target(self):
        spec = self.spec.copy()
        spec.update(target='1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA', passphrases=[''],
                    base_paths=["m/44'/0'/0'/0"], parsed_paths=[solver.parse_path("m/44'/0'/0'/0")],
                    index_start=0, index_count=1, include_master=False)
        words = ['abandon']*11 + ['about']
        checks, match = solver.check_phrase(words, spec)
        self.assertEqual(checks, 1)
        self.assertEqual(match['address'], spec['target'])
        self.assertEqual(match['path'], "m/44'/0'/0'/0/0")
        self.assertEqual(solver.base58check(b'\0' + solver.hash160(solver.public(int(match['private_key_hex'], 16)))), match['address'])
        spec['target'] = solver.TARGET
        self.assertIsNone(solver.check_phrase(words, spec)[1])

    def test_worker_match_persisted(self):
        spec = self.spec.copy()
        spec.update(mode='slots', slots=[['abandon']]*11 + [['about']], rotations=False, reverse=False,
                    target='1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA', passphrases=[''],
                    base_paths=["m/44'/0'/0'/0"], parsed_paths=[solver.parse_path("m/44'/0'/0'/0")],
                    index_start=0, index_count=1, include_master=False)
        with tempfile.TemporaryDirectory() as folder:
            solver.WORKER = spec, self.index, 1, Path(folder), 'test-signature'
            result = solver.check_batch(0, 1)
            self.assertEqual(result['end'], 1)
            self.assertTrue(Path(result['match']).exists())
            self.assertEqual(json.loads(Path(result['match']).read_text())['address'], spec['target'])

    def test_bad_words_and_config(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.json'
            raw = json.loads((solver.ROOT / 'puzzle-search.json').read_text())
            raw['pool'][0] = 'breathe'
            path.write_text(json.dumps(raw))
            with self.assertRaisesRegex(ValueError, 'non-BIP39'):
                solver.load_config(path)

    def test_signature_changes_with_search_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'new.json'
            raw = json.loads((solver.ROOT / 'puzzle-search.json').read_text())
            raw['index_count'] += 1
            path.write_text(json.dumps(raw))
            self.assertNotEqual(solver.load_config(path)[2], self.signature)

    def test_atomic_state_and_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.json'
            solver.atomic_json(path, {'next_rank': 64})
            solver.atomic_json(path, {'next_rank': 128})
            self.assertEqual(json.loads(path.read_text())['next_rank'], 128)
            first = solver.RunLock(path.with_suffix('.lock'))
            try:
                with self.assertRaises(RuntimeError):
                    solver.RunLock(path.with_suffix('.lock'))
            finally:
                first.close()
            second = solver.RunLock(path.with_suffix('.lock'))
            second.close()

    def test_process_resume_without_skipping(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / 'state.json'
            cmd = [sys.executable, str(solver.ROOT / 'puzzle_solver.py'), '--state', str(state),
                   '--workers', '2', '--duty', '1', '--batch-size', '16']
            for additional, expected in [(64, 64), (37, 101)]:
                completed = subprocess.run(cmd + ['--max-candidates', str(additional)],
                                           capture_output=True, text=True, timeout=45)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                data = json.loads(state.read_text())
                self.assertEqual(data['next_rank'], expected)
                valid = sum(solver.checksum(solver.candidate_at(self.spec, i), self.index) for i in range(expected))
                self.assertEqual(data['valid'], valid)
                self.assertEqual(data['address_checks'], valid * 3 * 21)
            changed = subprocess.run(cmd + ['--config', str(solver.ROOT / 'puzzle-search-all-orders.json'), '--max-candidates', '1'],
                                     capture_output=True, text=True, timeout=45)
            self.assertEqual(changed.returncode, 1)
            self.assertIn('changed', changed.stderr)
            self.assertEqual(json.loads(state.read_text())['next_rank'], 101)


if __name__ == '__main__':
    unittest.main()
