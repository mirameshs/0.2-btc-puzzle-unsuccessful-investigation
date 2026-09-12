import json
import multiprocessing
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import puzzle_solver as solver
from server_runtime import ShardedExecutor, cpu_info, pool_layout


class ServerTests(unittest.TestCase):
    def test_electrum_filter_and_positive_match(self):
        spec, total, signature, index = solver.load_config(solver.ROOT / 'search-electrum-prefix.json')
        self.assertEqual(total, 4194304)
        self.assertNotEqual(signature, self.signature)
        words = 'cycle rocket west magnet parrot shuffle foot correct salt library feed song'.split()
        self.assertTrue(solver.valid_candidate(words, index, spec))
        self.assertFalse(solver.checksum(words, index))
        self.assertEqual(solver.seed_for(' '.join(words), ' BREATHE ', 'electrum-v2-standard'),
                         solver.seed_for(' '.join(words), 'breathe', 'electrum-v2-standard'))
        spec.update(slots=[[w] for w in words], target='1NNkttn1YvVGdqBW4PR6zvc3Zx3H5owKRf')
        with tempfile.TemporaryDirectory() as folder:
            pool = ShardedExecutor(2, multiprocessing.get_context('spawn'), solver.init_worker,
                                   (spec, index, 1, folder, signature), pool_limit=1)
            try:
                result = pool.submit(solver.check_batch, 0, 1).result(timeout=45)
                match = json.loads(Path(result['match']).read_text())
                self.assertEqual(match['path'], 'm/0/0')
                self.assertEqual(match['seed_scheme'], 'electrum-v2-standard')
            finally:
                pool.shutdown()

    def test_electrum_resume(self):
        config = solver.ROOT / 'search-electrum-prefix.json'
        spec, _, _, index = solver.load_config(config)
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / 'state.json'
            for count, expected in ((4096, 4096), (2048, 6144)):
                result = subprocess.run([sys.executable, str(solver.ROOT / 'puzzle_solver.py'),
                    '--config', str(config), '--state', str(state), '--workers', '4', '--pool-limit', '2',
                    '--max-candidates', str(count)], capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                data = json.loads(state.read_text())
                valid = sum(solver.valid_candidate(solver.candidate_at(spec, i), index, spec) for i in range(expected))
                self.assertGreater(valid, 0)
                self.assertEqual(data['next_rank'], expected)
                self.assertEqual(data['valid'], valid)
                self.assertEqual(data['address_checks'], valid * 80)

    def setUp(self):
        self.spec, self.total, self.signature, self.index = solver.load_config(solver.ROOT / 'search-prefix.json')

    def test_crypto_vectors(self):
        solver.self_test()
        vectors = json.loads((solver.ROOT / 'bip39-test-vectors.json').read_text(encoding='utf-8-sig'))['english']
        for _, phrase, seed, xprv in vectors:
            self.assertTrue(solver.checksum(phrase.split(), self.index))
            actual = solver.seed_for(phrase, 'TREZOR')
            self.assertEqual(actual.hex(), seed)
            key, chain = solver.master(actual)
            self.assertEqual(solver.base58check(bytes.fromhex('0488ade4') + b'\0'*9 + chain + b'\0' + key.to_bytes(32, 'big')), xprv)

    def test_prefix_space_and_repeated_words(self):
        self.assertEqual(self.total, 4194304)
        for rank in (0, 1, 2047, 2048, self.total - 1):
            words = solver.candidate_at(self.spec, rank)
            self.assertEqual(' '.join(words[:10]), 'moon tower food this real subject address total ten black')
            self.assertEqual(self.index[words[10]], rank // 2048)
            self.assertEqual(self.index[words[11]], rank % 2048)
        self.assertEqual(solver.candidate_at(self.spec, 0)[-2:], ['abandon', 'abandon'])
        self.assertEqual(self.spec['passphrases'], [''])
        self.assertEqual(self.spec['compressed_modes'], [True, False])

    def test_all_last_words_checksum(self):
        # For any fixed first 11 words, exactly 128 choices of the last word pass.
        count = sum(solver.checksum(solver.candidate_at(self.spec, n), self.index) for n in range(2048))
        self.assertEqual(count, 128)

    def test_layout_and_128_worker_construction(self):
        for workers in (1, 24, 32, 61, 64, 128, 256):
            sizes = pool_layout(workers)
            self.assertEqual(sum(sizes), workers)
            self.assertLessEqual(max(sizes), 48)
        self.assertEqual(pool_layout(128), [43, 43, 42])
        with patch('server_runtime.ProcessPoolExecutor') as factory:
            pool = ShardedExecutor(128, multiprocessing.get_context('spawn'), None, ())
            self.assertEqual([c.kwargs['max_workers'] for c in factory.call_args_list], [43, 43, 42])
            pool.shutdown()

    def test_multiple_real_pools_find_and_persist_positive_control(self):
        spec = self.spec.copy()
        spec.update(slots=[['abandon']]*11 + [['about']], target='1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA',
                    base_paths=["m/44'/0'/0'/0"], parsed_paths=[solver.parse_path("m/44'/0'/0'/0")],
                    index_start=0, index_count=1, compressed_modes=[True])
        with tempfile.TemporaryDirectory() as folder:
            pool = ShardedExecutor(4, multiprocessing.get_context('spawn'), solver.init_worker,
                                   (spec, self.index, 1, folder, 'positive-control'), pool_limit=2)
            try:
                futures = [pool.submit(solver.check_batch, 0, 1) for _ in range(4)]
                for future in futures:
                    result = future.result(timeout=45)
                    match = json.loads(Path(result['match']).read_text())
                    self.assertEqual(match['address'], spec['target'])
                    self.assertEqual(match['path'], "m/44'/0'/0'/0/0")
            finally:
                pool.shutdown(wait=True, cancel_futures=True)

    def test_multipool_resume_and_change_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / 'resume.json'
            command = [sys.executable, str(solver.ROOT / 'puzzle_solver.py'), '--workers', '4',
                       '--pool-limit', '2', '--batch-size', '16', '--state', str(state)]
            for additional, expected in ((256, 256), (101, 357)):
                completed = subprocess.run(command + ['--max-candidates', str(additional)], capture_output=True, text=True, timeout=60)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                data = json.loads(state.read_text())
                self.assertEqual(data['next_rank'], expected)
                valid = sum(solver.checksum(solver.candidate_at(self.spec, i), self.index) for i in range(expected))
                self.assertEqual(data['valid'], valid)
                self.assertEqual(data['address_checks'], valid * 40)
                self.assertEqual(data['status'], 'paused')
            changed = subprocess.run(command + ['--config', str(solver.ROOT / 'search-prefix-extra-passphrases.json'),
                                                '--max-candidates', '1'], capture_output=True, text=True, timeout=60)
            self.assertEqual(changed.returncode, 1)
            self.assertIn('changed', changed.stderr)
            self.assertEqual(json.loads(state.read_text())['next_rank'], 357)

    def test_lock_and_cpu_detection(self):
        self.assertGreaterEqual(cpu_info()['logical_processors'], 1)
        with tempfile.TemporaryDirectory() as folder:
            first = solver.RunLock(Path(folder) / 'search.lock')
            try:
                with self.assertRaises(RuntimeError):
                    solver.RunLock(Path(folder) / 'search.lock')
            finally:
                first.close()


if __name__ == '__main__':
    unittest.main()
