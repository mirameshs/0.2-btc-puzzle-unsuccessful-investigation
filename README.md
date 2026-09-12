# BLM 0.2 BTC Puzzle — An Unsuccessful Search, Documented

**Status: unsolved in this project. No matching seed or private key was found in the completed searches listed below.**

This repository records an attempt to solve the public Bitcoin image puzzle associated with:

```text
1KfZGvwZxsvSmemoCmEV75uqcNzYBHjkHZ
```

It contains offline Python search tools, candidate configurations, image inspection notes, and negative results. The purpose of publishing it is to make the work reproducible, show where the assumptions were weak, and help others avoid repeating the same searches without a new reason.

This is an archive of an unsuccessful investigation, **not a solved puzzle or a claim that the puzzle is impossible**. The historical “0.2 BTC” name is not a statement about the address's current balance or prize availability. Results below were recorded during this project and documented on September 12, 2026.

**فارسی:** این مخزن مستندات یک تلاش ناموفق برای حل معماست. هیچ سید یا کلید منطبق پیدا نشد. هدف انتشار، انتقال تجربه و جلوگیری از تکرار جستجوهای یکسان است؛ نتیجه‌ها فقط در محدودهٔ تنظیمات آزمایش‌شده معتبرند. راهنماهای فارسی در انتهای این صفحه پیوند داده شده‌اند.

![Public BLM Bitcoin puzzle](0.2-btc-puzzle.png)

## Completed searches

The counts below come from completed run reports supplied during the investigation. Inclusion here does not mean every original console log is included in the repository. Each row ended with `Status: exhausted` and no target match.

| ID | Hypothesis | Candidates examined | Passed validity filter | Address comparisons |
|---|---|---:|---:|---:|
| A | 12 selected words, `black` fixed at position 10 | 39,916,800 | 2,495,761 | 157,232,943 |
| B | Fixed 10-word prefix + two unknown words, BIP39, empty passphrase | 4,194,304 | 262,144 | 10,485,760 |
| C | Same prefix, BIP39, `breathe` / `BREATHE` | 4,194,304 | 262,144 | 20,971,520 |
| D | Same prefix, Electrum v2 standard, empty / `breathe` | 4,194,304 | 16,470 | 1,317,600 |
| E | User-proposed 8-word prefix + four restricted slots, BIP39 | 4,096 | 255 | 215,730 |

These are **not counts of independent wallets discovered**, nor evidence of getting closer to the answer. Rows B–D share the same word template. Address comparisons include multiple derivations and passphrases for a candidate. Their counts must not be presented as unique seed phrases.

Other configurations and exploratory artifacts are present. Their existence does **not** establish that their full search spaces were completed.

### A — Selected words, one fixed position

Word set:

```text
moon tower food this subject real black one order stock life vote
```

`black` was fixed at the tenth position, counting from one. The remaining eleven distinct words were permuted: `11! = 39,916,800` candidates.

- BIP39; passphrases: empty, `breathe`, `BREATHE`.
- Base paths: `m/44'/0'/0'/0`, `m/44'/0'/0'/1`, `m/0'/0`, `m/0`.
- Child indices 0–4, plus the master key; compressed public keys.
- Configuration: [`puzzle-search.json`](puzzle-search.json).

Several words, particularly `stock`, `life`, and `vote`, were tentative interpretations. Fixing `black` at position 10 was also unproven.

### B–D — The ten-word prefix

```text
moon tower food this real subject address total ten black ? ?
```

Each unknown slot ranged independently over all 2,048 English BIP39 words, allowing repetition: `2048² = 4,194,304` candidates per run.

For B and C, the BIP39 searches used `m/44'/0'/account'/0/index`, accounts 0–1 and indices 0–9, with compressed and uncompressed public keys. B used the empty passphrase; C used `breathe` and `BREATHE`.

D used the Electrum v2 **standard** seed-version filter and seed derivation, receiving/change paths `m/0/index` and `m/1/index`, indices 0–19, and compressed public keys. It tested the empty passphrase and `breathe`. Electrum normalization makes `BREATHE` equivalent to `breathe`; the case variant was not searched twice. This implementation's Electrum inputs are limited to ASCII English. It does not cover old Electrum, SegWit, or two-factor seed types.

The prefix was taken from a public researcher's example script. **A prefix written into a script is not proof of the words or their order.** In particular, no sufficient independent image evidence was established here for the selection and positions of `address total ten`.

### E — User-proposed words

Fixed first eight words:

```text
moon tower food real black subject this world
```

Each of the final four slots independently used:

```text
brave seed phrase order end future north south
```

Repetition was allowed: `8⁴ = 4,096` candidates. The proposed word `stop` was excluded because it is absent from the English BIP39 word list.

- BIP39; passphrases: empty, `breathe`, `BREATHE`.
- Base paths: `m/44'/0'/0'/0`, `m/44'/0'/0'/1`, `m/44'/0'/1'/0`, `m/44'/0'/1'/1`, `m/0'/0`, `m/0`, `m/1`.
- Child indices 0–19, plus the master key; both public-key formats.
- 255 checksum-valid candidates × 846 comparisons = 215,730 comparisons, with no match.

## What we learned

1. **Word evidence and position evidence are different.** Finding `moon` on a clock hand does not establish it as the first seed word.
2. **More CPU does not repair a weak hypothesis.** An exhausted search gains no new coverage when repeated unchanged on faster hardware.
3. **A valid checksum is only a filter.** `valid` in the output does not mean a funded wallet or the puzzle answer was found.
4. **The negative results have boundaries.** They do not rule out other word orders, lengths, passphrases, derivation paths, or seed schemes.
5. **Clue interpretations must be internally consistent.** If the supplied “sum of two numbers” hint means adding the clock numbers adjacent to the labeled hands, `tower` would be at position 3 and `moon` at position 13. That interpretation is incompatible with a 12-word phrase. It remains a hypothesis, not proof of a longer phrase.
6. **Do not silently promote guesses to facts.** Reading the final rune as X, interpreting it as Roman numeral 10, and assigning that position to `black` are separate assumptions.

Some of these issues were recognized only after searches had been configured. The review notes preserve those corrections. Earlier files may contain tentative claims or historical status descriptions; this README and the later evidence reviews provide the context for interpreting them.

## Repository guide

| Path | Purpose |
|---|---|
| [`serverEdition/`](serverEdition/) | Preferred portable search implementation and Windows launchers |
| [`puzzle_solver.py`](puzzle_solver.py) | Earlier search implementation; retained for reproduction |
| [`puzzle-search*.json`](puzzle-search.json) | Earlier configurations, including large uncompleted search spaces |
| [`seed-candidates.txt`](seed-candidates.txt) | Exploratory candidate list, not a recovered seed |
| [`clue-inspection/`](clue-inspection/) | Image inspection crops and text observations |
| [`homelessphd-review/`](homelessphd-review/) | Reference material and audit of the public prefix script |
| [`rarsn4-review/`](rarsn4-review/) | Reference material from another public investigation |
| [`hypothesis-review-fa.md`](hypothesis-review-fa.md) | Review of the first unsuccessful search |
| [`next-step-evidence-fa.md`](next-step-evidence-fa.md) | Evidence review after the prefix searches |
| [`bip39-english-all.txt`](bip39-english-all.txt) | English word list used by the searches |
| [`bip39-test-vectors.json`](bip39-test-vectors.json) | Reference vectors used for verification |

ZIP files and similarly named edition folders are historical distribution snapshots and can lag behind `serverEdition/`. Use the latter when following the commands below. Downloaded reference scripts are research material, not required executables.

## Reproduce a search on Windows

Use **64-bit Python 3.10 or newer**. From the repository root in PowerShell:

```powershell
cd serverEdition
.\INSTALL.cmd
.\START-USER-WORDS.cmd
```

`INSTALL.cmd` creates a local `.venv`, installs the `cryptography` dependency, and runs cryptographic self-tests. It does not install Python itself. Dependency installation needs internet access; the search runs offline and does not query balances or submit transactions.

| Launcher in `serverEdition/` | Search |
|---|---|
| `START-SERVER.cmd` | B: BIP39 prefix, empty passphrase |
| `START-EXTRA-PASSPHRASES.cmd` | C: BIP39 prefix, extra passphrases |
| `START-ELECTRUM.cmd` | D: Electrum standard prefix |
| `START-USER-WORDS.cmd` | E: restricted four-slot search |

These launchers reproduce already unsuccessful hypotheses; they are not recommended as new attempts to win the puzzle.

For a bounded run with four workers and a separate checkpoint:

```powershell
.\.venv\Scripts\python.exe puzzle_solver.py --config search-user-words.json --workers 4 --max-candidates 256 --state solver-output/reproduction.state.json
```

The server edition defaults to all detected logical processors and uses multiple process pools when needed. Actual reported runs included a 24-logical-processor machine. Pool construction for larger counts was tested, but performance on 64/128-core hardware was not established here. Constant 100% CPU use and linear speedup are not guaranteed.

### Progress and results

- `Ctrl+C` requests a graceful pause; queued work may take time to finish.
- Running the same command again resumes from its checkpoint.
- `exhausted` means all candidates in that configuration were processed.
- Checkpoints normally live under `serverEdition/solver-output/` and are separate per configuration.
- Changes to the search configuration require a different checkpoint; the program checks its configuration fingerprint.
- An exact target match would be saved under `solver-output/matches/MATCH-....json`, including the phrase, passphrase, derivation path, and private key. No puzzle match was reported in the completed runs above.

### Verification

From `serverEdition/`, after installation:

```powershell
.\.venv\Scripts\python.exe puzzle_solver.py --self-test
.\.venv\Scripts\python.exe -m unittest test_server -v
```

The nine-test server suite passed during development. Coverage includes reference BIP39 vectors, official Electrum standard-wallet address examples, positive-control match persistence, multi-pool execution, and checkpoint resumption. Synthetic positive controls demonstrate program behavior; they are not solutions to this puzzle. Passing these checks does not validate the puzzle assumptions or prove the absence of all software defects.

## Publishing and contributing

When preparing a public commit, keep source, configurations, and research notes; exclude local environments, caches, transient checkpoints, and any match files. Checkpoints can contain local filesystem details, and match files contain private key material. A suitable `.gitignore` starting point is:

```gitignore
**/.venv/
**/__pycache__/
*.py[cod]
**/solver-output/
*.state.json
*.state.lock
*.state.stop
**/MATCH-*.json
*.tmp
```

This block is documentation, not an automatically installed ignore file. Ignore rules do not remove files already committed. Preserve useful negative results as sanitized summaries such as the table above.

Useful contributions include a reproducible clue extraction, a correction to a derivation or search boundary, or a completed result with its exact configuration and counts. Distinguish direct observations from interpretations. A larger candidate list alone is not stronger evidence.

## References and attribution

- [HomelessPhD / BLM_0.2BTC](https://github.com/HomelessPhD/BLM_0.2BTC) — public clue collection and prefix-search reference.
- [rarsn4 / blm-0.2btc-analysis](https://github.com/rarsn4/blm-0.2btc-analysis) — separate public investigation; its reported searches were not all independently reproduced here.
- [BIP39 specification](https://github.com/bitcoin/bips/blob/master/bip-0039.mediawiki) and [English word list](https://github.com/bitcoin/bips/blob/master/bip-0039/english.txt).
- [Trezor reference vectors](https://github.com/trezor/python-mnemonic/blob/master/vectors.json).
- [Electrum mnemonic implementation](https://github.com/spesmilo/electrum/blob/master/electrum/mnemonic.py) and [wallet test vectors](https://github.com/spesmilo/electrum/blob/master/tests/test_wallet_vertical.py).

The puzzle image and third-party research are attributed to their respective sources; this repository does not claim authorship of them. No repository-wide license is granted by this README. Review upstream licenses and redistribution terms before republishing third-party material or choosing a license for original code.

## Persian documentation

- [Original solver guide](SOLVER-README-fa.md)
- [Server edition guide](serverEdition/README-fa.md)
- [Electrum experiment](serverEdition/README-ELECTRUM-fa.md)
- [User-proposed word experiment](serverEdition/README-USER-WORDS-fa.md)
- [Hypothesis review](hypothesis-review-fa.md)
- [Later evidence review](next-step-evidence-fa.md)

**The useful outcome of this project is a documented set of negative results and corrected assumptions—not a recovered key.**
