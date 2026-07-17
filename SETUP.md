# Environment Setup

## Why this isn't just `pip install -e .`

Several dependencies (`numpy`, `scipy`, `scikit-learn`, `xgboost`, `matplotlib`)
are compiled C/C++/Fortran extensions, not pure Python. On macOS in particular,
mixing pip-installed and conda-installed versions of these in the same
environment can produce a broken mix of binaries that *look* installed
correctly (imports succeed for some packages) but fail at the exact moment
one compiled extension tries to call into another with an incompatible
interface — e.g. `ImportError: cannot import name '_spropack' from
'scipy.sparse.linalg._propack'`, or xgboost failing to find `libomp.dylib`
even after it's installed via Homebrew, because Homebrew's install path on
Apple Silicon (`/opt/homebrew`) differs from where xgboost's pip wheel
expects it (`/usr/local`).

The fix: install every compiled/binary-heavy package **together, in one
conda-forge call**, so conda's dependency solver picks one mutually
compatible set of binaries from the start, rather than layering pip and
conda installs on top of each other over time.

## Setup, from scratch

```bash
conda create -n steamproj python=3.11 -y
conda activate steamproj

# Core scientific stack — install together via conda-forge, not pip.
# This is the step that matters most; skipping it or mixing in pip
# installs of these specific packages is what causes the ABI mismatch.
conda install -c conda-forge numpy scipy pandas scikit-learn xgboost matplotlib -y

# Everything else — pure-Python or less binary-sensitive, pip is fine
pip install requests beautifulsoup4 shap statsmodels plotly ipykernel

# Register this environment as a Jupyter/VS Code kernel
python -m ipykernel install --user --name steamproj --display-name "Python (steamproj)"

# Install this project's own package, WITHOUT letting pip try to
# reinstall (and potentially re-break) the dependencies conda just
# carefully resolved
cd ~/Dropbox/steamproject
pip install -e . --no-deps
```

Sanity check before doing anything else:
```bash
python -c "import numpy, scipy, pandas, sklearn, xgboost, matplotlib; print('all good')"
```

## Adding a new dependency later

This is the normal case, not an emergency — nuking the environment is NOT
the answer here (rebuilding without updating anything below wouldn't even
include the new package).

1. **Compiled/binary-heavy package** (links against BLAS/LAPACK/OpenMP —
   things like `numba`, `pytorch`, `scikit-image`): install it directly
   into the existing environment via `conda install -c conda-forge
   <package>`. This is safe on its own — conda's solver checks
   compatibility against everything already installed. The original bug
   wasn't "incremental conda installs are dangerous"; it was specifically
   pip and conda having both installed *the same* packages at different
   times and stepping on each other's files.
2. **Pure-Python package** (no heavy compiled dependencies — most smaller
   utility packages): plain `pip install <package>` is fine, same as
   `beautifulsoup4`/`shap`/`plotly` were.
3. Either way, add it to `pyproject.toml`'s `dependencies` list for
   documentation, and to the `conda install` line above if it's a
   conda-forge package, so this file stays an accurate record of the real
   setup sequence.

## If this breaks again

The root cause was ORDER of installation, not bad luck: this project's
`pyproject.toml` originally had `pip install -e .` install scikit-learn,
xgboost, and matplotlib via pip first. Much later, `conda install -c
conda-forge xgboost` tried to layer conda-built replacements for those same
packages (plus numpy/scipy) on top of files pip had already written —
conda's uninstall logic only reliably tracks files *it* installed, so this
can leave a genuinely mixed, partially-overwritten set of binaries behind.
That's what caused the ABI mismatches.

Don't patch individual import errors one at a time — you'd be patching a
potentially already-contaminated environment. Rebuild clean instead, which
fixes this for two concrete reasons: (1) `conda env remove` deletes the
whole environment directory, so no stale pip-installed files can linger
alongside new conda ones, and (2) the setup sequence above installs the
entire compiled stack together via ONE conda-forge call, before pip ever
touches any of those same packages — so the problematic pip-then-conda
layering never happens in the first place.

```bash
conda deactivate
conda env remove -n steamproj
# then repeat the full setup above
```

**Important**: this only stays fixed if you avoid recreating the original
mistake. Always install this project with `pip install -e . --no-deps` —
a plain `pip install -e .` (without `--no-deps`) would let pip try to
reinstall scikit-learn/xgboost/matplotlib/etc. from PyPI, potentially
reintroducing the exact same conflict.
