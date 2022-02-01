"""Multiple genome alignment

src: ./pairwise/{target}/{query}/{chromosome}/sing.maf
lnk: ./multiple/{target}/{clade}/{chromosome}/{target}.{query}.sing.maf
dst: ./multiple/{target}/{clade}/{chromosome}/multiz.maf

https://github.com/multiz/multiz
"""
import concurrent.futures as confu
import os
import logging
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any, IO

from .db import ensemblgenomes, name, phylo
from . import cli

_log = logging.getLogger(__name__)
_dry_run = False


def main(argv: list[str] = []):
    import argparse

    parser = argparse.ArgumentParser(parents=[cli.logging_argparser()])
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("-n", "--dry-run", action="store_true")
    parser.add_argument("-j", "--jobs", type=int, default=os.cpu_count())
    parser.add_argument("indir", type=Path)  # pairwise/oryza_sativa
    parser.add_argument("clade")  # monocot, poaceae, bep, pacmad
    args = parser.parse_args(argv or None)
    cli.logging_config(args.loglevel)
    global _dry_run
    _dry_run = args.dry_run
    outdir = prepare(args.indir, args.clade)
    chromodirs = outdir.glob("chromosome.*")
    if args.clean:
        for d in chromodirs:
            clean(d)
        return
    with confu.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = [executor.submit(multiz, p) for p in chromodirs]
    for future in confu.as_completed(futures):
        if maf := future.result():
            print(maf)


def multiz(path: Path):
    clade = path.parent.name
    (roasted, outfile) = roast(path, clade)
    with open(roasted, "rt") as fin:
        script = fin.read()
    _log.debug(script)
    p = shell(f"set -eu; cd {str(path)}\n" + script)
    if p.returncode > 0:
        for line in p.stdout.strip().splitlines():
            _log.error(f"{path.name}:{line}")
        _log.error(outfile)
        return None
    if out := p.stdout.strip():
        _log.info(out)
    return outfile


def roast(path: Path, clade: str):
    """Generate shell script to execute multiz"""
    sing_mafs = list(path.glob("*.sing.maf"))
    tmpdir = ".tmp"
    min_width = 18
    ref_label = sing_mafs[0].name.split(".", 1)[0]
    tree = getattr(phylo, clade).replace(",", " ")
    outfile = path / "multiz.maf"
    args = (
        f"roast - T={tmpdir} M={min_width} E={ref_label} '{tree}' "
        + " ".join([x.name for x in sing_mafs])
        + f" {outfile.name}"
    )
    roasted = path / "roasted.sh"
    with open(roasted, "w") as fout:
        run(args, stdout=fout, text=True)
    (path / tmpdir).mkdir(0o755, exist_ok=True)
    return (roasted, outfile)


def prepare(indir: Path, clade: str):
    target = indir.name
    tree = getattr(phylo, clade)
    species = phylo.extract_species(tree)
    species = ensemblgenomes.expand_shortnames(species)
    assert target in species
    outdir = Path("multiple") / target / clade
    outdir.mkdir(0o755, parents=True, exist_ok=True)
    with open(outdir / "tree.nh", "w") as fout:
        fout.write(tree + "\n")
    symlink(indir, outdir, species)
    return outdir


def symlink(indir: Path, outdir: Path, species: Iterable[str]):
    target = indir.name
    for query in species:
        if query == target:
            continue
        querypath = indir / query
        if not querypath.exists():
            _log.error(f"not found {querypath}")
        dstname = f"{name.shorten(target)}.{name.shorten(query)}.sing.maf"
        for chrdir in querypath.glob("chromosome.*"):
            src = chrdir / "sing.maf"
            dstdir = outdir / chrdir.name
            dstdir.mkdir(0o755, exist_ok=True)
            dst = dstdir / dstname
            relsrc = os.path.relpath(src, dstdir)
            _log.info(f"{dst}@\n -> {relsrc}")
            if not dst.exists():
                dst.symlink_to(relsrc)


def run(
    args: list[str] | str,
    stdin: IO[Any] | int | None = None,
    stdout: IO[Any] | int | None = None,
    text: bool = False,
):  # kwargs hinders type inference to Popen[bytes]
    (args, cmd) = cli.prepare_args(args, _dry_run)
    _log.info(cmd)
    return subprocess.run(args, stdin=stdin, stdout=stdout, text=text)


def shell(script: str):
    return subprocess.run(
        script, text=True, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )


def clean(path: Path):
    for entry in path.iterdir():
        if entry.name in ("multiz.maf", "roasted.sh", ".tmp"):
            print(entry)
            if not _dry_run:
                rm_rf(entry)


def rm_rf(path: Path):
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


if __name__ == "__main__":
    main()