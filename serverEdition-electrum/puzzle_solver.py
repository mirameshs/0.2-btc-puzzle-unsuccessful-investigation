"""Offline, resumable BIP39 search for the public 0.2 BTC image puzzle.

Requires Python 3.10+ and cryptography. No network or transaction operations.
Only an exact match to the puzzle address is considered success.
"""
from __future__ import annotations

import argparse
import atexit
from collections import deque
from concurrent.futures import TimeoutError
from server_runtime import ShardedExecutor, cpu_info, pool_layout
import hashlib
import hmac
import itertools
import json
import math
import os
from pathlib import Path
import signal
import struct
import sys
import time
import unicodedata

try:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
except ImportError:
    raise SystemExit('Install dependency: python -m pip install cryptography')

ROOT = Path(__file__).resolve().parent
TARGET = '1KfZGvwZxsvSmemoCmEV75uqcNzYBHjkHZ'
VERSION = 1
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
WORKER = None


def sha(data):
    return hashlib.sha256(data).digest()


def base58check(data):
    payload = data + sha(sha(data))[:4]
    n, out = int.from_bytes(payload, 'big'), ''
    while n:
        n, r = divmod(n, 58)
        out = ALPHABET[r] + out
    return '1' * (len(payload) - len(payload.lstrip(b'\0'))) + out


def decode_address(text):
    n = 0
    for char in text:
        n = n * 58 + ALPHABET.index(char)
    data = n.to_bytes((n.bit_length() + 7) // 8, 'big')
    data = b'\0' * (len(text) - len(text.lstrip('1'))) + data
    if len(data) != 25 or data[0] != 0 or sha(sha(data[:-4]))[:4] != data[-4:]:
        raise ValueError('Expected a valid Bitcoin mainnet P2PKH address')
    return data[1:21]


def public(key, compressed=True):
    fmt = PublicFormat.CompressedPoint if compressed else PublicFormat.UncompressedPoint
    return ec.derive_private_key(key, ec.SECP256K1()).public_key().public_bytes(Encoding.X962, fmt)


def hash160(data):
    return hashlib.new('ripemd160', sha(data)).digest()


def electrum_normalize(text):
    """Scoped to ASCII English inputs; do not silently mishandle CJK normalization."""
    if not text.isascii():
        raise ValueError('This Electrum preset supports ASCII English inputs only')
    return ' '.join(text.lower().split())


def valid_candidate(words, index, spec):
    if spec.get('seed_scheme', 'bip39') == 'electrum-v2-standard':
        phrase = electrum_normalize(' '.join(words))
        return hmac.digest(b'Seed version', phrase.encode(), 'sha512').hex().startswith('01')
    return checksum(words, index)


def seed_for(phrase, password, scheme='bip39'):
    if scheme == 'electrum-v2-standard':
        return hashlib.pbkdf2_hmac('sha512', electrum_normalize(phrase).encode(),
                                   ('electrum' + electrum_normalize(password)).encode(), 2048)
    if scheme != 'bip39':
        raise ValueError('Unsupported seed scheme')
    norm = lambda s: unicodedata.normalize('NFKD', s).encode('utf-8')
    return hashlib.pbkdf2_hmac('sha512', norm(phrase), norm('mnemonic' + password), 2048)


def master(seed):
    digest = hmac.digest(b'Bitcoin seed', seed, 'sha512')
    key = int.from_bytes(digest[:32], 'big')
    if not 0 < key < N:
        raise ValueError('Invalid BIP32 master; stopping rather than silently skipping')
    return key, digest[32:]


def child(node, index):
    key, chain = node
    data = b'\0' + key.to_bytes(32, 'big') if index >= 2**31 else public(key)
    digest = hmac.digest(chain, data + struct.pack('>I', index), 'sha512')
    tweak = int.from_bytes(digest[:32], 'big')
    result = (key + tweak) % N
    if tweak >= N or not result:
        raise ValueError('Invalid BIP32 child; stopping rather than silently skipping')
    return result, digest[32:]


def parse_path(path):
    if not isinstance(path, str) or not path.startswith('m/'):
        raise ValueError('Base paths must start with m/')
    parts = []
    for part in path.split('/')[1:]:
        raw = part[:-1] if part.endswith("'") else part
        if not raw.isdecimal() or not 0 <= int(raw) < 2**31:
            raise ValueError(f'Invalid path: {path}')
        parts.append(int(raw) + (2**31 if part.endswith("'") else 0))
    return tuple(parts)


def checksum(words, index):
    if len(words) not in (12, 15, 18, 21, 24):
        return False
    value = 0
    for word in words:
        if word not in index:
            return False
        value = (value << 11) | index[word]
    cs = len(words) // 3
    entropy = (value >> cs).to_bytes((11 * len(words) - cs) // 8, 'big')
    return (value & ((1 << cs) - 1)) == (sha(entropy)[0] >> (8 - cs))


def positive_int(value, label, allow_zero=False):
    if type(value) is not int or value < (0 if allow_zero else 1):
        raise ValueError(f'{label} must be an integer >= {0 if allow_zero else 1}')
    return value


def load_config(path):
    raw = json.loads(path.read_text(encoding='utf-8-sig'))
    allowed = {'description', 'mode', 'word_count', 'pool', 'pool_file', 'fixed_positions',
               'slots', 'rotations', 'reverse', 'passphrases', 'base_paths',
               'index_start', 'index_count', 'include_master', 'compressed_modes', 'seed_scheme'}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f'Unknown config fields: {sorted(unknown)}')
    official = (ROOT / 'bip39-english-all.txt').read_text(encoding='utf-8-sig').split()
    if len(official) != 2048 or len(set(official)) != 2048 or official != sorted(official):
        raise ValueError('Official BIP39 word list must contain 2048 distinct sorted words')
    index = {w: i for i, w in enumerate(official)}

    def check_words(words, label):
        if not isinstance(words, list) or not words or any(not isinstance(w, str) for w in words):
            raise ValueError(f'{label} must be a nonempty list of words')
        if len(set(words)) != len(words):
            raise ValueError(f'{label} contains duplicate words')
        bad = [w for w in words if w not in index]
        if bad:
            raise ValueError(f'{label} contains non-BIP39 words: {bad}')
        return words

    count = raw.get('word_count', 12)
    if type(count) is not int or count not in (12, 15, 18, 21, 24):
        raise ValueError('word_count must be 12, 15, 18, 21 or 24')
    spec = {'version': VERSION, 'target': TARGET, 'word_count': count,
            'wordlist_hash': sha('\n'.join(official).encode()).hex(), 'mode': raw.get('mode')}
    scheme = raw.get('seed_scheme', 'bip39')
    if scheme not in ('bip39', 'electrum-v2-standard'):
        raise ValueError('Unsupported seed_scheme')
    # Keep existing BIP39 checkpoint fingerprints unchanged.
    if scheme != 'bip39':
        spec['seed_scheme'] = scheme
    if spec['mode'] == 'permutations':
        if any(k in raw for k in ('slots', 'rotations', 'reverse')):
            raise ValueError('slots/rotations/reverse apply only to slots mode')
        if ('pool' in raw) == ('pool_file' in raw):
            raise ValueError('Specify exactly one of pool or pool_file')
        pool = raw.get('pool')
        if pool is None:
            pool = (path.parent / raw['pool_file']).read_text(encoding='utf-8-sig').replace(',', ' ').split()
        check_words(pool, 'pool')
        fixed = {}
        for key, word in raw.get('fixed_positions', {}).items():
            if not key.isdecimal() or str(int(key)) != key or not 1 <= int(key) <= count:
                raise ValueError('fixed_positions uses positions starting at 1')
            if word not in pool:
                raise ValueError(f'Fixed word {word!r} must be present in pool')
            fixed[int(key) - 1] = word
        if len(set(fixed.values())) != len(fixed):
            raise ValueError('Permutation mode does not allow repeated words; use slots for repetitions')
        remaining = [w for w in pool if w not in fixed.values()]
        free = [i for i in range(count) if i not in fixed]
        if len(remaining) < len(free):
            raise ValueError('Not enough distinct pool words')
        spec.update(pool=pool, fixed=fixed, remaining=remaining, free=free)
        total = math.perm(len(remaining), len(free))
    elif spec['mode'] == 'slots':
        if any(k in raw for k in ('pool', 'pool_file', 'fixed_positions')):
            raise ValueError('pool and fixed_positions apply only to permutations mode')
        slots = [official.copy() if item == '@BIP39' else item for item in raw.get('slots', [])]
        if len(slots) != count:
            raise ValueError('slots length must equal word_count')
        for i, words in enumerate(slots):
            check_words(words, f'slot {i+1}')
        for key in ('rotations', 'reverse'):
            if type(raw.get(key, False)) is not bool:
                raise ValueError(f'{key} must be true or false')
        spec.update(slots=slots, rotations=raw.get('rotations', False), reverse=raw.get('reverse', False))
        total = math.prod(map(len, slots)) * (count if spec['rotations'] else 1) * (2 if spec['reverse'] else 1)
    else:
        raise ValueError('mode must be permutations or slots')
    passwords = raw.get('passphrases', [''])
    if not isinstance(passwords, list) or not passwords or any(not isinstance(p, str) for p in passwords):
        raise ValueError('passphrases must be a nonempty list of strings; empty string means none')
    spec['passphrases'] = list(dict.fromkeys(unicodedata.normalize('NFKD', p) for p in passwords))
    if scheme == 'electrum-v2-standard':
        spec['passphrases'] = list(dict.fromkeys(electrum_normalize(p) for p in passwords))
    bases = raw.get('base_paths', ["m/44'/0'/0'/0"])
    if not isinstance(bases, list):
        raise ValueError('base_paths must be a list')
    spec['base_paths'] = list(dict.fromkeys(bases))
    spec['parsed_paths'] = [parse_path(p) for p in spec['base_paths']]
    spec['index_start'] = positive_int(raw.get('index_start', 0), 'index_start', True)
    spec['index_count'] = positive_int(raw.get('index_count', 5), 'index_count')
    if spec['index_start'] + spec['index_count'] > 2**31:
        raise ValueError('Address indices must be less than 2^31')
    spec['include_master'] = raw.get('include_master', True)
    if type(spec['include_master']) is not bool:
        raise ValueError('include_master must be true or false')
    modes = raw.get('compressed_modes', [True])
    if not isinstance(modes, list) or not modes or any(type(m) is not bool for m in modes):
        raise ValueError('compressed_modes must be a list of booleans')
    spec['compressed_modes'] = list(dict.fromkeys(modes))
    if not spec['include_master'] and not bases:
        raise ValueError('No address checks configured')
    signature = sha(json.dumps(spec, sort_keys=True, separators=(',', ':')).encode()).hex()
    return spec, total, signature, index


def candidate_at(spec, rank):
    """Direct unranking: resume without replaying all previous candidates."""
    count = spec['word_count']
    if spec['mode'] == 'permutations':
        available = spec['remaining'].copy()
        words = [spec['fixed'].get(i) for i in range(count)]
        for j, position in enumerate(spec['free']):
            block = math.perm(len(available) - 1, len(spec['free']) - j - 1)
            selection, rank = divmod(rank, block)
            words[position] = available.pop(selection)
        return words
    rotations = count if spec['rotations'] else 1
    rank, rotation = divmod(rank, rotations)
    rank, reverse = divmod(rank, 2 if spec['reverse'] else 1)
    words = [None] * count
    for i in reversed(range(count)):
        rank, selection = divmod(rank, len(spec['slots'][i]))
        words[i] = spec['slots'][i][selection]
    if reverse:
        words.reverse()
    return words[rotation:] + words[:rotation]


def check_phrase(words, spec):
    phrase = ' '.join(words)
    target_hash = decode_address(spec['target'])
    checked = 0
    for password in spec['passphrases']:
        root = master(seed_for(phrase, password, spec.get('seed_scheme', 'bip39')))
        cache = {(): root}

        def node_for(parts):
            if parts not in cache:
                cache[parts] = child(node_for(parts[:-1]), parts[-1])
            return cache[parts]

        def nodes():
            if spec['include_master']:
                yield 'm', root[0]
            for label, parts in zip(spec['base_paths'], spec['parsed_paths']):
                for i in range(spec['index_start'], spec['index_start'] + spec['index_count']):
                    yield f'{label}/{i}', node_for(tuple(parts) + (i,))[0]

        for path, key in nodes():
            for compressed in spec['compressed_modes']:
                digest = hash160(public(key, compressed))
                checked += 1
                if digest == target_hash:
                    actual = base58check(b'\0' + digest)
                    if actual != spec['target']:
                        raise RuntimeError('Address verification disagreement')
                    return checked, {'phrase': phrase, 'passphrase': password, 'path': path,
                                     'compressed': compressed, 'address': actual,
                                     'seed_scheme': spec.get('seed_scheme', 'bip39'),
                                     'private_key_hex': f'{key:064x}',
                                     'private_key_wif': base58check(b'\x80' + key.to_bytes(32, 'big') + (b'\x01' if compressed else b''))}
    return checked, None


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    with temp.open('w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def init_worker(spec, index, duty, match_dir, signature):
    global WORKER
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    WORKER = spec, index, duty, Path(match_dir), signature


def check_batch(start, end):
    spec, index, duty, match_dir, signature = WORKER
    began = time.monotonic()
    valid = checks = 0
    for rank in range(start, end):
        words = candidate_at(spec, rank)
        if not valid_candidate(words, index, spec):
            continue
        valid += 1
        number, match = check_phrase(words, spec)
        checks += number
        if match:
            match.update(rank=rank, signature=signature, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
            # Persist immediately, even if an earlier batch is still running.
            location = match_dir / f'MATCH-{signature[:12]}-{rank}.json'
            atomic_json(location, match)
            return {'start': start, 'end': rank + 1, 'valid': valid, 'checks': checks, 'match': str(location)}
    busy = time.monotonic() - began
    if duty < 1:
        time.sleep(busy * (1 / duty - 1))
    return {'start': start, 'end': end, 'valid': valid, 'checks': checks, 'match': None}


class RunLock:
    """OS-released lock: stale files after a crash do not block resumption."""
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = path.open('a+b')
        self.handle.seek(0, 2)
        if not self.handle.tell():
            self.handle.write(b'0')
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise RuntimeError('Another process is already using this checkpoint')

    def close(self):
        self.handle.close()


def self_test():
    official = (ROOT / 'bip39-english-all.txt').read_text(encoding='utf-8-sig').split()
    index = {w: i for i, w in enumerate(official)}
    phrase = 'abandon ' * 11 + 'about'
    if not checksum(phrase.split(), index) or checksum(['abandon'] * 12, index):
        raise RuntimeError('BIP39 checksum self-test failed')
    known_seed = ('c55257c360c07c72029aebc1b53c05ed0362ada38ead3e3e9efa3708e53495531'
                  'f09a6987599d18264c1e1c92f2cf141630c7a3c4ab7c81b2f001698e7463b04')
    if seed_for(phrase, 'TREZOR').hex() != known_seed:
        raise RuntimeError('BIP39 seed self-test failed')
    key = master(seed_for(phrase, ''))
    for step in parse_path("m/44'/0'/0'/0/0"):
        key = child(key, step)
    if base58check(b'\0' + hash160(public(key[0]))) != '1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA':
        raise RuntimeError('BIP32/BIP44 address self-test failed')
    if base58check(b'\0' + hash160(public(1, False))) != '1EHNa6Q4Jz2uvNExL497mE43ikXhwF6kZm':
        raise RuntimeError('Uncompressed address self-test failed')
    decode_address(TARGET)
    # Official Electrum test_wallet_vertical.py standard-wallet vector.
    electrum_words = 'cycle rocket west magnet parrot shuffle foot correct salt library feed song'
    if not valid_candidate(electrum_words.split(), index, {'seed_scheme': 'electrum-v2-standard'}):
        raise RuntimeError('Electrum seed version self-test failed')
    root = master(seed_for(electrum_words, '', 'electrum-v2-standard'))
    for branch, expected in ((0, '1NNkttn1YvVGdqBW4PR6zvc3Zx3H5owKRf'),
                             (1, '1KSezYMhAJMWqFbVFB2JshYg69UpmEXR4D')):
        key = child(child(root, branch), 0)[0]
        if base58check(b'\0' + hash160(public(key))) != expected:
            raise RuntimeError('Electrum standard address self-test failed')


def duration(seconds):
    if seconds < 60:
        return f'{seconds:.0f}s'
    if seconds < 3600:
        return f'{seconds / 60:.1f} min'
    if seconds < 86400:
        return f'{seconds / 3600:.1f} hours'
    return f'{seconds / 86400:.2g} days'


def run(args):
    if struct.calcsize('P') != 8:
        raise RuntimeError('Server Edition requires 64-bit Python 3.10 or newer')
    self_test()
    if args.self_test:
        print('Cryptographic self-tests passed.')
        return 0
    config = args.config.resolve()
    spec, total, signature, index = load_config(config)
    print('Seed scheme: ' + spec.get('seed_scheme', 'bip39'), flush=True)
    print(f'Target: {TARGET}\nMode: {spec["mode"]}; words: {spec["word_count"]}\nSearch cases: {total:,}', flush=True)
    if args.describe:
        print(json.dumps(spec, indent=2))
        return 0
    info = cpu_info()
    if not 0 < args.duty <= 1 or not 1 <= args.workers <= info['logical_processors']:
        raise ValueError('duty must be >0 and <=1; workers must be between 1 and CPU count')
    layout = pool_layout(args.workers, args.pool_limit)
    print(f'CPU: {info}; workers: {args.workers}; independent pools: {layout}', flush=True)
    positive_int(args.batch_size, 'batch-size')
    if args.max_candidates is not None:
        positive_int(args.max_candidates, 'max-candidates')
    if args.max_seconds is not None and args.max_seconds <= 0:
        raise ValueError('max-seconds must be positive')
    state_path = (args.state or ROOT / 'solver-output' / (config.stem + '.state.json')).resolve()
    stop_path = state_path.with_suffix('.stop')
    match_dir = state_path.parent / 'matches'
    lock = RunLock(state_path.with_suffix('.lock'))
    atexit.register(lock.close)
    try:
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding='utf-8'))
            if state.get('signature') != signature:
                raise ValueError('Search config/word list changed. Use a different --state file; old progress is preserved.')
        else:
            state = {'signature': signature, 'target': TARGET, 'total': total, 'next_rank': 0,
                     'valid': 0, 'address_checks': 0, 'elapsed_seconds': 0, 'status': 'ready'}
        if not 0 <= state['next_rank'] <= total:
            raise ValueError('Checkpoint rank is out of range')
        found = list(match_dir.glob(f'MATCH-{signature[:12]}-*.json')) if match_dir.exists() else []
        if found:
            print(f'Previously saved match: {found[0]}')
            return 0
        if state['next_rank'] == total:
            print('This search space is exhausted. No match in the configured scope.')
            return 0
        if stop_path.exists():
            print(f'Stop file exists. Remove this file to resume: {stop_path}')
            return 0
        print(f'Resume at: {state["next_rank"]:,}; workers={args.workers}; worker duty={args.duty:.0%}\n'
              f'Checkpoint: {state_path}\nCtrl+C pauses after in-flight batches. Stop file: {stop_path}', flush=True)
        start_rank = state['next_rank']
        run_end = min(total, start_rank + args.max_candidates) if args.max_candidates else total
        started = last_display = last_save = time.monotonic()
        previous_elapsed = state['elapsed_seconds']
        stopping = False

        def request_stop(*_):
            nonlocal stopping
            stopping = True

        previous_signal = signal.signal(signal.SIGINT, request_stop)
        pool = None
        pending = deque()
        next_submit = start_rank

        def save(status):
            nonlocal last_save
            state['status'] = status
            state['elapsed_seconds'] = previous_elapsed + time.monotonic() - started
            atomic_json(state_path, state)
            last_save = time.monotonic()

        try:
            save('running')
            # Windows-safe spawn; at most 2 batches per worker are queued.
            import multiprocessing
            pool = ShardedExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context('spawn'),
                                   initializer=init_worker, initargs=(spec, index, args.duty, str(match_dir), signature),
                                   pool_limit=args.pool_limit)
            while pending or (next_submit < run_end and not stopping):
                now = time.monotonic()
                if stop_path.exists() or (args.max_seconds and now - started >= args.max_seconds):
                    stopping = True
                while not stopping and next_submit < run_end and len(pending) < 2 * args.workers:
                    end = min(next_submit + args.batch_size, run_end)
                    pending.append(pool.submit(check_batch, next_submit, end))
                    next_submit = end
                if not pending:
                    break
                try:
                    result = pending[0].result(timeout=0.5)
                except TimeoutError:
                    result = None
                if result is not None:
                    pending.popleft()
                    if result['start'] != state['next_rank']:
                        raise RuntimeError('Non-contiguous checkpoint; refusing to skip candidates')
                    state['next_rank'] = result['end']
                    state['valid'] += result['valid']
                    state['address_checks'] += result['checks']
                    if result['match']:
                        save('match')
                        print(f'EXACT MATCH SAVED: {result["match"]}', flush=True)
                        stopping = True
                        break
                now = time.monotonic()
                if now - last_save >= 10:
                    save('pausing' if stopping else 'running')
                if now - last_display >= 5:
                    elapsed = now - started
                    speed = (state['next_rank'] - start_rank) / elapsed
                    eta = duration((total - state['next_rank']) / speed) if speed else 'measuring'
                    print(f'{state["next_rank"]:,}/{total:,} | valid={state["valid"]:,} | '
                          f'checks={state["address_checks"]:,} | {speed:.1f} cases/s | ETA {eta}'
                          + (' | pausing...' if stopping else ''), flush=True)
                    last_display = now
            if state['status'] != 'match':
                save('exhausted' if state['next_rank'] == total else 'paused')
        except BaseException:
            # Only the contiguous completed prefix is committed; unfinished work is retried.
            save('error')
            raise
        finally:
            for future in pending:
                future.cancel()
            if pool is not None:
                pool.shutdown(wait=True, cancel_futures=True)
            signal.signal(signal.SIGINT, previous_signal)
        print(f'Status: {state["status"]}; completed {state["next_rank"]:,}/{total:,}; '
              f'valid={state["valid"]:,}; address checks={state["address_checks"]:,}', flush=True)
        if state['status'] == 'exhausted':
            print('No match in this configured search. Other words, lengths, passphrases and paths remain untested.')
        return 0
    finally:
        atexit.unregister(lock.close)
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'search-prefix.json')
    parser.add_argument('--state', type=Path, help='Alternate checkpoint for a separate search')
    parser.add_argument('--workers', type=int, help='Default: all logical processors, across Windows processor groups')
    parser.add_argument('--duty', type=float, default=1.0, help='Active fraction per worker; default 1 (no deliberate sleep)')
    parser.add_argument('--pool-limit', type=int, default=48, help='Maximum workers per independent pool, from 1 to 61')
    parser.add_argument('--full-cpu', action='store_true',
                        help='Use all logical CPUs across multiple pools, duty=1; overrides workers/duty')
    parser.add_argument('--batch-size', type=int, default=64)
    parser.add_argument('--max-candidates', type=int, help='Additional search cases this run')
    parser.add_argument('--max-seconds', type=float, help='Stop dispatching after this time; finish queued batches')
    parser.add_argument('--describe', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    try:
        args = parser.parse_args()
        if args.workers is None:
            args.workers = cpu_info()['logical_processors']
        if args.full_cpu:
            args.workers = cpu_info()['logical_processors']
            args.duty = 1.0
        return run(args)
    except (ValueError, OSError, RuntimeError, KeyError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
