# Clone the repo
git clone git@github.com:robbrad/UKBinCollectionData.git
# Migrate it to UV, as I don't use Poetry
uvx migrate-to-uv
# Set the python version, as 3.14 doesn't work with yarl
uv venv --python 3.13
# Add a dependency
uv add selenium-wire blinker<1.8.0 pytest
# Add monkey patch
cp monkey_patch/common.py UKBinCollectionData/uk_bin_collection/uk_bin_collection/common.py
cp monkey_patch/test_validate_council.py UKBinCollectionData/uk_bin_collection/tests/step_defs/test_validate_council.pyuk_bin_collection/common.py
# Run tests
cd UKBinCollectionData
uv run python -m pytest uk_bin_collection/tests/step_defs/test_validate_council.py