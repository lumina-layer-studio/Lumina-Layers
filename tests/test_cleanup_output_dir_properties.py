"""Property-based tests for cleanup_output_dir() extension filtering (Property 3).

Feature: about-page-cache-cleanup, Property 3: OUTPUT_DIR 清理扩展名过滤

Uses Hypothesis to verify:
- cleanup_output_dir deletes only files with extensions in {.3mf, .glb, .png, .jpg}
- Files with other extensions remain untouched
- deleted_count equals the number of files with cleanable extensions

**Validates: Requirements 3.4**
"""

import os
import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

from api.routers.system import CLEANABLE_EXTENSIONS, cleanup_output_dir

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Extensions that SHOULD be cleaned
cleanable_exts = st.sampled_from(sorted(CLEANABLE_EXTENSIONS))

# Extensions that should NOT be cleaned
non_cleanable_exts = st.sampled_from([
    ".txt", ".py", ".json", ".xml", ".csv", ".log", ".md",
    ".yaml", ".toml", ".cfg", ".ini", ".html", ".css", ".js",
])

# Safe filename base: alphanumeric, 1-20 chars
filename_base = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")),
    min_size=1,
    max_size=20,
)


def _filename_with_ext(ext_strategy: st.SearchStrategy[str]) -> st.SearchStrategy[str]:
    """Build a filename strategy from a base name and an extension strategy."""
    return st.tuples(filename_base, ext_strategy).map(lambda t: t[0] + t[1])


# A single file entry: (filename, is_cleanable)
cleanable_file = _filename_with_ext(cleanable_exts).map(lambda f: (f, True))
non_cleanable_file = _filename_with_ext(non_cleanable_exts).map(lambda f: (f, False))

# Mixed list of files (0-30 entries)
file_list = st.lists(
    st.one_of(cleanable_file, non_cleanable_file),
    min_size=0,
    max_size=30,
)


# ---------------------------------------------------------------------------
# Property 3: OUTPUT_DIR 清理扩展名过滤
# ---------------------------------------------------------------------------


# **Validates: Requirements 3.4**
@given(files=file_list)
@settings(max_examples=100)
def test_cleanup_output_dir_only_deletes_cleanable_extensions(
    files: list[tuple[str, bool]],
) -> None:
    """Feature: about-page-cache-cleanup, Property 3: OUTPUT_DIR 清理扩展名过滤

    For any set of filenames with various extensions, cleanup_output_dir should:
    1. Delete only files whose extension is in CLEANABLE_EXTENSIONS
    2. Leave all other files untouched
    3. Return deleted_count equal to the number of cleanable files
    """
    tmp_dir = tempfile.mkdtemp()
    try:
        # Deduplicate filenames (keep last occurrence for each name)
        seen: dict[str, bool] = {}
        for fname, is_cleanable in files:
            seen[fname] = is_cleanable

        # Create all files with some content so freed_bytes > 0
        for fname in seen:
            path = os.path.join(tmp_dir, fname)
            with open(path, "wb") as f:
                f.write(b"x" * 64)

        expected_cleanable = sum(1 for c in seen.values() if c)
        expected_remaining = sum(1 for c in seen.values() if not c)

        deleted_count, freed_bytes = cleanup_output_dir(tmp_dir)

        # Property: deleted_count equals the number of cleanable files
        assert deleted_count == expected_cleanable

        # Property: freed_bytes is correct (each file was 64 bytes)
        assert freed_bytes == expected_cleanable * 64

        # Property: remaining files are exactly the non-cleanable ones
        remaining = set(os.listdir(tmp_dir))
        assert len(remaining) == expected_remaining

        # Property: every remaining file has a non-cleanable extension
        for fname in remaining:
            _, ext = os.path.splitext(fname)
            assert ext.lower() not in CLEANABLE_EXTENSIONS
    finally:
        # Clean up the temp directory
        for fname in os.listdir(tmp_dir):
            os.remove(os.path.join(tmp_dir, fname))
        os.rmdir(tmp_dir)
