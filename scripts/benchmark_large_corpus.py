#!/usr/bin/env python3
"""Large-scale corpus benchmark & determinism verifier for Log2Topic.

Generates 1,000 daily log files (3,500 rich multi-block sections, ~11.5 MB of Markdown)
and measures:
1. Cold Run: Initial Source ID assignment (3,500 IDs), backups, Subject/ and Topic_Reviews/ compilation.
2. Warm Run: Re-execution speed and 100% SHA-256 byte-for-byte determinism across all generated files.
3. Refactor Run: Renaming 100 section headings across 100 files and verifying 100% Source ID retention
   and zero orphan Subject files.
"""

import argparse
from datetime import date, timedelta
import hashlib
import io
import os
import re
import sys
import tempfile
import time
from contextlib import redirect_stdout

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import hierarchical_classifier
from hierarchical_classifier import SOURCE_ID_RE, load_metadata


BENCHMARK_RULES = """\
# Classification Rules

| Level 1 | Level 2 | Level 3 | Level 4 | Level 5 | Keywords |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Projects | Alpha Platform | | | | Alpha Platform |
| | | Architecture | | | architecture, protocol |
| | | Implementation | | | implementation, pipeline |
| | | Testing | | | testing |
| | | | Functional Test | | functional test, acceptance |
| | | | Regression Test | | regression test, stability |
| | | | Performance Test | | latency, throughput, benchmark |
| | Beta Engine | | | | Beta Engine |
| | | Scheduler | | | scheduler, queue |
| | | Storage | | | storage, index, compaction |
| | | Verification | | | verification, assertion |
| | Gamma Sensor | | | | Gamma Sensor |
| | | Calibration | | | calibration, offset, drift |
| | | Signal Processing | | | filter, fft, noise |
| | | Field Trial | | | field trial, telemetry |
| Knowledge | Systems | | | | systems |
| | | Concurrency | | | lock, mutex, atomic |
| | | Networking | | | socket, retry, timeout |
| | Methodology | | | | methodology |
| | | Benchmarking | | | profiling, flamegraph |
| | | Root Cause Analysis | | | postmortem, regression |
| Operations | Release Engineering | | | | release, packaging |
| | | CI Pipeline | | | workflow, artifact, checksum |
"""

SECTION_SPECS = [
    ("# Projects\n## Alpha Platform\n### Testing\n#### Functional Test", "Alpha Functional Test"),
    ("# Projects\n## Alpha Platform\n### Testing\n#### Regression Test", "Alpha Regression Test"),
    ("# Projects\n## Alpha Platform\n### Testing\n#### Performance Test", "Alpha Performance Test"),
    ("# Projects\n## Alpha Platform\n### Architecture", "Alpha Architecture"),
    ("# Projects\n## Alpha Platform\n### Implementation", "Alpha Implementation"),
    ("# Projects\n## Beta Engine\n### Scheduler", "Beta Scheduler"),
    ("# Projects\n## Beta Engine\n### Storage", "Beta Storage"),
    ("# Projects\n## Beta Engine\n### Verification", "Beta Verification"),
    ("# Projects\n## Gamma Sensor\n### Calibration", "Gamma Calibration"),
    ("# Projects\n## Gamma Sensor\n### Signal Processing", "Gamma Signal Processing"),
    ("# Projects\n## Gamma Sensor\n### Field Trial", "Gamma Field Trial"),
    ("# Knowledge\n## Systems\n### Concurrency", "Systems Concurrency"),
    ("# Knowledge\n## Systems\n### Networking", "Systems Networking"),
    ("# Knowledge\n## Methodology\n### Benchmarking", "Methodology Benchmarking"),
]


def build_heavy_chunk(day_idx, chunk_idx, heading_block, label):
    """Build a ~3,300-character realistic engineering/research log section."""
    include_long_table = (day_idx + chunk_idx) % 2 == 0
    table_rows = [
        "| Run | Batch Size | P50 Latency (ms) | P99 Latency (ms) | Throughput (ops/s) | Error Rate | Notes |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :--- |",
        f"| #{day_idx:04d}-A | 256 | 4.12 | 11.80 | 61,200 | 0.00% | Baseline configuration under nominal load |",
        f"| #{day_idx:04d}-B | 512 | 5.45 | 14.20 | 88,400 | 0.00% | Enabled batch coalescing and zero-copy buffer |",
        f"| #{day_idx:04d}-C | 1024 | 7.90 | 19.65 | 104,900 | 0.01% | Minor tail spike during background compaction |",
    ]
    if include_long_table:
        for extra in range(8):
            table_rows.append(
                f"| #{day_idx:04d}-X{extra} | {128 * (extra + 1)} | {3.1 + extra * 0.7:.2f} | "
                f"{9.5 + extra * 1.8:.2f} | {52000 + extra * 6300:,} | 0.00% | "
                "Extended soak matrix verification with deterministic replay window and checksum audit |"
            )
    table_block = "\n".join(table_rows)

    return (
        f"{heading_block}\n\n"
        f"In iteration `{day_idx:04d}.{chunk_idx}`, we evaluated **{label}** across sustained multi-hour workloads "
        f"to verify state recovery, deterministic ordering, and memory ceiling stability after context switches. "
        f"When returning from adjacent tasks, the primary question was whether the ring-buffer watermark and "
        f"compaction schedule introduced tail-latency jitter when concurrent readers scanned historical snapshots. "
        f"Cross-checking the baseline metrics from the prior milestone confirmed that lock contention remained bounded "
        f"below 1.2% of wall-clock time while preserving full crash-consistency guarantees.\n\n"
        f"###### Experimental Setup & Key Observations\n\n"
        f"- **Hardware & Runtime Profile**: 8 worker threads, 4 GiB bounded arena, deterministic seed `{day_idx * 17 + chunk_idx}`\n"
        f"- **Hypothesis**: Separating metadata flush from payload commit eliminates P99 spikes during snapshot rotation\n"
        f"- **Outcome**: Observed zero corrupted frames and 100% reproducible state hashes across 50 consecutive replays\n"
        f"- **Follow-up Action**: Validate behavior under simulated disk-full and partial-write fault injection\n\n"
        f"![[bench_img_{(chunk_idx % 4) + 1}.png]]\n"
        f"![Waveform capture](../../attachments/bench_img_{((chunk_idx + 1) % 4) + 1}.png \"Iteration {day_idx}-{chunk_idx}\")\n\n"
        f"```python\n"
        f"def verify_iteration_{day_idx}_{chunk_idx}(records, expected_Window=512):\n"
        f"    digest = hashlib.sha256()\n"
        f"    for idx, item in enumerate(records[:expected_Window]):\n"
        f"        digest.update(f\"{{idx}}:{{item.key}}:{{item.checksum}}\\n\".encode('utf-8'))\n"
        f"    return digest.hexdigest()\n"
        f"```\n\n"
        f"{table_block}\n\n"
        f"```text\n"
        f"[TRACE {day_idx:04d}-{chunk_idx} 00:01.004] worker=01 phase=prepare segments=64 watermark=0x0040fa10 status=OK\n"
        f"[TRACE {day_idx:04d}-{chunk_idx} 00:01.118] worker=02 phase=compact merged_blocks=128 reclaimed_bytes=4194304 status=OK\n"
        f"[TRACE {day_idx:04d}-{chunk_idx} 00:01.245] worker=03 phase=verify  audited_entries=2048 mismatched=0 status=OK\n"
        f"[TRACE {day_idx:04d}-{chunk_idx} 00:01.389] worker=04 phase=commit  journal_seq={day_idx * 100 + chunk_idx} fsync_ms=2.41 status=OK\n"
        f"[TRACE {day_idx:04d}-{chunk_idx} 00:01.512] worker=01 phase=checkpoint snapshot_id=snap-{day_idx:04d}-{chunk_idx} orphan_pages=0 status=OK\n"
        f"[TRACE {day_idx:04d}-{chunk_idx} 00:01.688] worker=02 phase=audit   integrity_hash=9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08\n"
        f"[TRACE {day_idx:04d}-{chunk_idx} 00:01.834] worker=03 phase=finish  elapsed_ms=830.0 peak_rss_kb=48120 status=COMPLETED\n"
        f"```\n\n"
        f"> [!quote]- AI Assistant Diagnostic Notes (Wrapped Callout)\n"
        f"> # Automated Trace Summary\n"
        f"> ## Root Cause Comparison\n"
        f"> The tail latency in Run C correlates with the background compaction window rather than lock contention.\n"
        f"> Keeping the callout wrapped ensures internal `#` and `##` headings stay attached to this section.\n"
    )


def hash_directory_tree(root_dir):
    digest = hashlib.sha256()
    file_count = 0
    total_bytes = 0
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames.sort()
        for fname in sorted(filenames):
            fpath = os.path.join(dirpath, fname)
            rel = os.path.relpath(fpath, root_dir).replace("\\", "/")
            with open(fpath, "rb") as fobj:
                data = fobj.read()
            file_count += 1
            total_bytes += len(data)
            digest.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(data).digest() + b"\n")
    return digest.hexdigest(), file_count, total_bytes


def run_classifier(temp_root, extra_args=()):
    from unittest.mock import patch

    fake_script = os.path.join(temp_root, "scripts", "hierarchical_classifier.py")
    os.makedirs(os.path.dirname(fake_script), exist_ok=True)
    argv = [
        "--production",
        "--output-dir",
        "Subject",
        "--review-dir",
        "Topic_Reviews",
        "--metadata-file",
        "organizer_metadata.json",
        *extra_args,
    ]
    buf = io.StringIO()
    t0 = time.perf_counter()
    with patch.object(hierarchical_classifier, "__file__", fake_script), redirect_stdout(buf):
        rc = hierarchical_classifier.main(argv)
    elapsed = time.perf_counter() - t0
    return rc, elapsed, buf.getvalue()


def run_benchmark(num_files=1000):
    with tempfile.TemporaryDirectory() as temp_dir:
        vault_dir = os.path.join(temp_dir, "Workspace")
        daily_dir = os.path.join(vault_dir, "Daily_Logs")
        attach_dir = os.path.join(vault_dir, "attachments")
        os.makedirs(daily_dir, exist_ok=True)
        os.makedirs(attach_dir, exist_ok=True)

        with open(os.path.join(vault_dir, "Classification_Rules.md"), "w", encoding="utf-8") as fobj:
            fobj.write(BENCHMARK_RULES)

        for img_idx in range(1, 5):
            with open(os.path.join(attach_dir, f"bench_img_{img_idx}.png"), "wb") as fobj:
                fobj.write(b"\x89PNG\r\n\x1a\n" + bytes([img_idx]) * 64)

        start_date = date(2024, 1, 1)
        created_files = []
        total_chunks = 0
        total_input_bytes = 0
        total_input_lines = 0

        for idx in range(num_files):
            cur_date = start_date + timedelta(days=idx)
            month_folder = os.path.join(daily_dir, f"{cur_date.year:04d}-{cur_date.month:02d}")
            os.makedirs(month_folder, exist_ok=True)
            filename = f"{cur_date.strftime('%Y-%m-%d')}-log-{idx:04d}.md"
            filepath = os.path.join(month_folder, filename)

            chunks_in_file = 3 if idx % 2 == 0 else 4
            sections = []
            for c_idx in range(chunks_in_file):
                spec_idx = (idx * 3 + c_idx) % len(SECTION_SPECS)
                heading_block, label = SECTION_SPECS[spec_idx]
                sections.append(build_heavy_chunk(idx + 1, c_idx + 1, heading_block, label))
                total_chunks += 1

            content = "\n\n".join(sections) + "\n"
            encoded = content.encode("utf-8")
            total_input_bytes += len(encoded)
            total_input_lines += content.count("\n")
            with open(filepath, "w", encoding="utf-8", newline="\n") as fobj:
                fobj.write(content)
            created_files.append(filepath)

        # 1. Cold Run
        rc1, cold_sec, out1 = run_classifier(temp_dir)
        if rc1 != 0:
            raise RuntimeError(f"Cold run failed (rc={rc1}):\n{out1}")

        subj_dir = os.path.join(vault_dir, "Subject")
        rev_dir = os.path.join(vault_dir, "Topic_Reviews")
        meta_path = os.path.join(temp_dir, "scripts", "organizer_metadata.json")

        subj_hash_1, subj_count_1, subj_bytes_1 = hash_directory_tree(subj_dir)
        rev_hash_1, rev_count_1, rev_bytes_1 = hash_directory_tree(rev_dir)
        meta_1 = load_metadata(meta_path)
        initial_ids = set(meta_1.get("entries", {}).keys())

        # 2. Warm Run (Idempotency & Determinism)
        rc2, warm_sec, out2 = run_classifier(temp_dir)
        if rc2 != 0:
            raise RuntimeError(f"Warm run failed (rc={rc2}):\n{out2}")

        subj_hash_2, subj_count_2, _ = hash_directory_tree(subj_dir)
        rev_hash_2, rev_count_2, _ = hash_directory_tree(rev_dir)
        deterministic_match = (subj_hash_1 == subj_hash_2) and (rev_hash_1 == rev_hash_2)

        # 3. Refactor Run (Rename first heading in 100 files to another valid category)
        refactored_count = min(100, len(created_files))
        for fpath in created_files[:refactored_count]:
            with open(fpath, "r", encoding="utf-8") as fobj:
                text = fobj.read()
            updated_text = re.sub(
                r"^# Projects\n## [^\n]+\n### [^\n]+(?:\n#### [^\n]+)?",
                "# Operations\n## Release Engineering\n### CI Pipeline",
                text,
                count=1,
            )
            with open(fpath, "w", encoding="utf-8", newline="\n") as fobj:
                fobj.write(updated_text)

        rc3, refactor_sec, out3 = run_classifier(temp_dir)
        if rc3 != 0:
            raise RuntimeError(f"Refactor run failed (rc={rc3}):\n{out3}")

        meta_3 = load_metadata(meta_path)
        after_refactor_ids = set(meta_3.get("entries", {}).keys())
        ids_preserved = initial_ids == after_refactor_ids
        _, subj_count_3, _ = hash_directory_tree(subj_dir)
        expected_subj_3 = sum(
            len(entry.get("generated_paths", []))
            for entry in meta_3.get("entries", {}).values()
        )
        zero_orphans = subj_count_3 == expected_subj_3

        print("======================================================================")
        print(" Log2Topic Large-Corpus Benchmark & Determinism Report")
        print("======================================================================")
        print(f" Input Daily Logs       : {num_files:,} files")
        print(f" Total Source Sections  : {total_chunks:,} sections (~{total_input_bytes // max(1, total_chunks):,} bytes/section)")
        print(f" Total Markdown Volume  : {total_input_bytes / (1024 * 1024):.2f} MB ({total_input_lines:,} lines)")
        print(f" Generated Outputs      : {subj_count_1:,} Subject files ({subj_bytes_1 / (1024 * 1024):.2f} MB) + {rev_count_1:,} Review files ({rev_bytes_1 / (1024 * 1024):.2f} MB)")
        print("----------------------------------------------------------------------")
        print(f" 1) Cold Run (3,500 new Source IDs + backup + compile) : {cold_sec:.2f} s ({total_chunks / cold_sec:,.0f} sections/s)")
        print(f" 2) Warm Run (idempotent re-compile)                   : {warm_sec:.2f} s ({total_chunks / warm_sec:,.0f} sections/s)")
        print(f" 3) Deterministic SHA-256 output match (Cold vs Warm)  : {'PASS (100% identical)' if deterministic_match else 'FAIL'}")
        print(f" 4) Heading Refactor Run ({refactored_count} sections moved)          : {refactor_sec:.2f} s")
        print(f" 5) Permanent Source ID retention & zero orphans       : {'PASS (' + str(len(after_refactor_ids)) + '/' + str(total_chunks) + ' IDs preserved, ' + str(subj_count_3) + ' active Subject files, 0 orphans)' if (ids_preserved and zero_orphans) else 'FAIL'}")
        print("======================================================================")
        return 0 if (deterministic_match and ids_preserved and zero_orphans) else 1


def main():
    parser = argparse.ArgumentParser(description="Run large-corpus benchmark for Log2Topic.")
    parser.add_argument("--files", type=int, default=1000, help="Number of daily log files to generate (default: 1000)")
    args = parser.parse_args()
    return run_benchmark(args.files)


if __name__ == "__main__":
    raise SystemExit(main())
