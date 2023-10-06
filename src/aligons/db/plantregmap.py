"""http://plantregmap.gao-lab.org/."""
import logging
import re
from collections.abc import Iterator
from pathlib import Path

from aligons import db
from aligons.db import api
from aligons.extern import htslib, kent, mafs2cram
from aligons.util import cli, dl, fs, subp

from . import tools

_log = logging.getLogger(__name__)
_HOST = "plantregmap.gao-lab.org"

_longer = {
    "Osj": "Oryza_sativa_Japonica_Group",
    "Sly": "Solanum_lycopersicum",
}


def main(argv: list[str] | None = None):
    parser = cli.ArgumentParser()
    parser.add_argument("-D", "--download", action="store_true")
    parser.add_argument("-G", "--genome", action="store_true")
    parser.add_argument("pattern", nargs="?", default="*")
    args = parser.parse_args(argv or None)
    if args.download:
        fts: list[cli.FuturePath] = []
        fts.extend(download_via_ftp())
        fts.extend(retrieve_deploy(q) for q in iter_download_queries())
        cli.wait_raise(fts)
    elif args.genome:
        cli.wait_raise(download_genome())
        cli.wait_raise(split_mask_index())
    else:
        for x in fs.sorted_naturally(db_prefix().rglob(args.pattern)):
            print(x)


def download_genome():
    fts: list[cli.FuturePath] = []
    for entry in tools.iter_dataset("plantregmap.toml"):
        fts.extend(tools.retrieve(entry, db_prefix()))
    return fts


def split_mask_index():
    fts: list[cli.FuturePath] = []
    for entry in tools.iter_dataset("plantregmap.toml"):
        species = entry["species"]
        fts.append(tools.prepare_fasta(species))
        gff3_gz = api.get_file_nolabel("*.gff3.gz", species)
        fts.append(cli.thread_submit(tools.index_gff3, [gff3_gz]))
    return fts


def retrieve_deploy(query: str):
    url = f"http://{_HOST}/download_ftp.php?{query}"
    relpath = query.split("/", 1)[1]
    rawfile = db.path_mirror(_HOST) / relpath
    outfile = db_prefix() / relpath
    if outfile.suffix in (".bed", ".gff"):
        outfile = outfile.with_suffix(outfile.suffix + ".gz")
    elif outfile.name.endswith(".gtf.gz"):
        outfile = outfile.with_suffix("").with_suffix(".gff.gz")
    content = dl.get(url, rawfile).content
    if outfile.suffix == ".gz":
        future = cli.thread_submit(tools.compress, content, outfile)
    else:
        future = cli.thread_submit(fs.symlink, rawfile, outfile)
    return cli.thread_submit(htslib.try_index, future)


def iter_download_queries():
    for query in iter_download_queries_all():
        if re.search(r"Oryza_sativa_Japonica|Solanum_lycopersicum", query):
            yield query


def iter_download_queries_all():
    content = download_php()
    for mobj in re.finditer(r"download_ftp\.php\?([^\"']+)", content):
        yield mobj[1]


def download_php() -> str:
    url = f"http://{_HOST}/download.php"
    cache = db.path_mirror(_HOST) / "download.php.html"
    return dl.get(url, cache).text


def db_prefix():
    return db.path("plantregmap")


def rglob(pattern: str, species: str = ".") -> Iterator[Path]:
    for species_dir in db_prefix().iterdir():
        if re.search(species, species_dir.name, re.IGNORECASE):
            yield from species_dir.rglob(pattern)


def to_cram(link: Path, species: str) -> Path:
    outfile = link.parent / link.with_suffix(".cram")
    maf = gunzip(link)
    reference = api.genome_fa(species)
    return mafs2cram.maf2cram(maf, outfile, reference)


def to_bigwig(link: Path, species: str) -> Path:
    bedgraph = gunzip(link)
    bigwig = bedgraph.with_suffix(".bw")
    if fs.is_outdated(bigwig, bedgraph):
        kent.bedGraphToBigWig(bedgraph, api.fasize(species))
    return bigwig


def gunzip(infile: Path):
    outfile = infile.parent / infile.name.removesuffix(".gz")
    if fs.is_outdated(outfile, infile):
        subp.run(["gunzip", "-fk", infile])
        subp.run(["touch", outfile])
    return outfile


def download_via_ftp() -> list[cli.FuturePath]:
    fts: list[cli.FuturePath] = []
    with FTPplantregmap() as ftp:
        for entry in tools.iter_dataset("plantregmap.toml"):
            sp = entry["label"]
            fts.extend(ftp.download(sp))
    return fts


class FTPplantregmap(dl.LazyFTP):
    def __init__(self):
        host = "ftp.cbi.pku.edu.cn"
        super().__init__(
            host,
            "/pub/database/PlantRegMap",
            db.path_mirror(host) / "plantregmap",
            timeout=65535,
        )

    def ls_cache(self, species: str = ""):
        self.nlst_cache("")
        self.nlst_cache("08-download")
        self.nlst_cache("08-download/FTP")
        self.nlst_cache("08-download/FTP/pairwise_alignments")
        if species:
            self.nlst_cache(f"08-download/{species}")
        self.retrieve("Species_abbr.list")

    def download(self, sp: str) -> list[cli.FuturePath]:
        fts: list[cli.FuturePath] = []
        species = _longer[sp]
        self.ls_cache(species)
        for bedgraph in self.download_conservation(species):
            fts.append(cli.thread_submit(to_bigwig, bedgraph, species))  # noqa: PERF401
        for maf in self.download_multiple_alignments(species):
            fts.append(cli.thread_submit(to_cram, maf, species))  # noqa: PERF401
        for _ in self.download_pairwise_alignments(sp):
            pass
        return fts

    def download_pairwise_alignments(self, species: str) -> Iterator[Path]:
        relpath = f"08-download/FTP/pairwise_alignments/{species}"
        nlst = self.nlst_cache(relpath)
        yield from (self.retrieve_symlink(x, _longer[species]) for x in nlst)

    def download_multiple_alignments(self, species: str) -> Iterator[Path]:
        relpath = f"08-download/{species}/multiple_alignments"
        nlst = self.nlst_cache(relpath)
        yield from (self.retrieve_symlink(x, species) for x in nlst)

    def download_conservation(self, species: str) -> Iterator[Path]:
        relpath = f"08-download/{species}/sequence_conservation"
        nlst = self.nlst_cache(relpath)
        yield from (self.retrieve_symlink(x, species) for x in nlst)

    def retrieve_symlink(self, relpath: str, species: str) -> Path:
        orig = self.retrieve(relpath, checksize=True)
        outdir = db_prefix() / species / "compara"
        return fs.symlink(orig, outdir / orig.name)


if __name__ == "__main__":
    main()
