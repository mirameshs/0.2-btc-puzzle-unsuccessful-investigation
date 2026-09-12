"""Bounded, offline investigation of a public Bitcoin image puzzle.

No network access, wallet import, transaction signing, or spending.
The generated phrases are explicit hypotheses, not established solutions.
"""
import ast
import hashlib
import hmac
import itertools
import json
import math
import struct
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from PIL import Image
import numpy as np

ROOT = Path(__file__).resolve().parent
WORDS = (ROOT / 'bip39-english-all.txt').read_text(encoding='utf-8-sig').split()
INDEX = {word: i for i, word in enumerate(WORDS)}
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
TARGET = '1KfZGvwZxsvSmemoCmEV75uqcNzYBHjkHZ'


def sha(data):
    return hashlib.sha256(data).digest()


def b58check(data):
    payload = data + sha(sha(data))[:4]
    n = int.from_bytes(payload, 'big')
    out = ''
    while n:
        n, r = divmod(n, 58)
        out = ALPHABET[r] + out
    return '1' * (len(payload) - len(payload.lstrip(b'\0'))) + out


def public(key, compressed=True):
    fmt = PublicFormat.CompressedPoint if compressed else PublicFormat.UncompressedPoint
    return ec.derive_private_key(key, ec.SECP256K1()).public_key().public_bytes(Encoding.X962, fmt)


def address(key, compressed=True):
    digest = hashlib.new('ripemd160', sha(public(key, compressed))).digest()
    return b58check(b'\0' + digest)


def master(seed):
    digest = hmac.digest(b'Bitcoin seed', seed, 'sha512')
    key = int.from_bytes(digest[:32], 'big')
    if not 0 < key < N:
        raise ValueError('Invalid master key')
    return key, digest[32:]


def child(node, index):
    key, chain = node
    data = b'\0' + key.to_bytes(32, 'big') if index >= 2**31 else public(key)
    digest = hmac.digest(chain, data + struct.pack('>I', index), 'sha512')
    tweak = int.from_bytes(digest[:32], 'big')
    result = (tweak + key) % N
    if tweak >= N or result == 0:
        raise ValueError('Invalid child key; do not silently relabel path')
    return result, digest[32:]


def derive(node, path):
    for part in path.split('/')[1:]:
        node = child(node, int(part.rstrip("'")) + (2**31 if part.endswith("'") else 0))
    return node


def seed_for(phrase, passphrase=''):
    normalize = lambda s: unicodedata.normalize('NFKD', s).encode()
    return hashlib.pbkdf2_hmac('sha512', normalize(phrase), normalize('mnemonic' + passphrase), 2048)


def checksum(phrase):
    words = phrase.split()
    if len(words) not in (12, 15, 18, 21, 24):
        return False
    if any(w not in INDEX for w in words):
        return False
    value = 0
    for word in words:
        value = value * 2048 + INDEX[word]
    cs = len(words) // 3
    entropy = (value >> cs).to_bytes((len(words) * 11 - cs) // 8, 'big')
    return value & ((1 << cs) - 1) == sha(entropy)[0] >> (8 - cs)


def xprv_root(seed):
    key, chain = master(seed)
    return b58check(bytes.fromhex('0488ade4') + b'\0' * 9 + chain + b'\0' + key.to_bytes(32, 'big'))


def self_test():
    vectors = json.loads((ROOT / 'bip39-test-vectors.json').read_text(encoding='utf-8-sig'))['english']
    for entropy, phrase, seedhex, xprv in vectors:
        assert checksum(phrase)
        seed = seed_for(phrase, 'TREZOR')
        assert seed.hex() == seedhex
        assert xprv_root(seed) == xprv
    assert not checksum('abandon ' * 11 + 'abandon')
    assert address(1) == '1BgGZ9tcN4rm9KBzDn7KprQz87SZ26SAMH'
    assert address(1, False) == '1EHNa6Q4Jz2uvNExL497mE43ikXhwF6kZm'
    test = master(seed_for('abandon ' * 11 + 'about'))
    assert address(derive(test, "m/44'/0'/0'/0/0")[0]) == '1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA'
    return len(vectors)


def audit_file():
    path = ROOT / '0.2-btc-puzzle.png'
    data = path.read_bytes()
    pos = 8
    chunks = []
    while pos + 12 <= len(data):
        size = int.from_bytes(data[pos:pos + 4], 'big')
        kind = data[pos + 4:pos + 8].decode('ascii')
        chunks.append(kind)
        pos += size + 12
        if kind == 'IEND':
            break
    with Image.open(path) as im:
        pixels = np.asarray(im)
        result = {'size': im.size, 'mode': im.mode, 'metadata': im.info,
                  'alpha_range': [int(pixels[:, :, 3].min()), int(pixels[:, :, 3].max())]}
    result.update(sha256=sha(data).hex(), trailing_bytes=len(data)-pos,
                  chunk_types=sorted(set(chunks)))
    return result


def legacy_membership():
    # Parse the reference as data; never execute downloaded source.
    tree = ast.parse((ROOT / 'electrum-old-mnemonic-reference.py.txt').read_text(encoding='utf-8-sig'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_words' for t in node.targets):
            old_words = ast.literal_eval(node.value)
            clues = 'moon tower food breathe tuesday this subject real black'.split()
            return {'word_count': len(old_words), 'clues': {w: w in old_words for w in clues}}
    return {'error': 'Legacy word list assignment not found'}


def hypotheses():
    # Fixed hint order plus every cyclic rotation in both directions.
    # Slot substitutions are tentative semantic readings, not discovered words.
    slots = [
        ['moon'], ['tower'], ['food'], ['air', 'oxygen', 'life', 'chest'],
        ['hope', 'receive', 'rich'], ['two', 'twenty', 'stock', 'number'],
        ['day', 'vote', 'three'], ['ten', 'day', 'rain', 'night'],
        ['this'], ['subject'], ['real'], ['black'],
    ]
    seen = set()
    for combo in itertools.product(*slots):
        for seq in (combo, combo[::-1]):
            for offset in range(12):
                phrase = ' '.join(seq[offset:] + seq[:offset])
                if phrase not in seen:
                    seen.add(phrase)
                    yield phrase


def run():
    start = time.monotonic()
    tests = self_test()
    report = {'utc': datetime.now(timezone.utc).isoformat(), 'target': TARGET,
              'test_vectors_passed': tests, 'image_audit': audit_file(),
              'legacy_wordlist_check': legacy_membership(),
              'search_scope': '12-word fixed hint slots, all cyclic rotations and reversals; not exhaustive',
              'passphrases': ['', 'breathe', 'BREATHE'],
              'base_paths': ["m/44'/0'/0'/0", "m/44'/0'/0'/1", "m/0'/0", 'm/0'],
              'child_indices': [0, 1, 2],
              'also_checked': 'master key P2PKH, compressed and uncompressed',
              'phrase_count': 0, 'checksum_valid_count': 0, 'address_checks': 0, 'matches': []}
    example = 'moon tower food real black subject time proof only win world face'
    report['github_example_checksum_valid'] = checksum(example)
    report['all_102_words_12_permutations_no_repeats'] = math.perm(102, 12)
    for phrase in hypotheses():
        report['phrase_count'] += 1
        if not checksum(phrase):
            continue
        report['checksum_valid_count'] += 1
        for password in report['passphrases']:
            root = master(seed_for(phrase, password))
            checks = [('m', root[0], True), ('m', root[0], False)]
            for base in report['base_paths']:
                branch = derive(root, base)
                for index in report['child_indices']:
                    checks.append((f'{base}/{index}', child(branch, index)[0], True))
            for path, key, compressed in checks:
                report['address_checks'] += 1
                if address(key, compressed) == TARGET:
                    report['matches'].append({'phrase': phrase, 'passphrase': password, 'path': path, 'compressed': compressed})
        if report['checksum_valid_count'] % 200 == 0:
            print(f"Checked {report['phrase_count']} phrases; {report['checksum_valid_count']} checksum-valid; {len(report['matches'])} matches", flush=True)
    report['elapsed_seconds'] = round(time.monotonic() - start, 2)
    (ROOT / 'investigation-results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    run()
