"""https://jbrowse.org.

src: {vNN}/pairwise/{species}/{query}/cram/genome.cram
src: {vNN}/conservation/{species}/{clade}/phastcons.bw
dst: {document_root}/{jbrowse_XYZ}/{vNN}/{species}
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

from aligons.db import api, phylo, plantdhs, plantregmap
from aligons.util import cli, config, fs, resources_data, subp

_log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = cli.ArgumentParser()
    parser.add_argument("-a", "--admin", action="store_true")
    parser.add_argument("-u", "--upgrade", action="store_true")
    parser.add_argument("indir", type=Path)  # conservation/oryza_sativa/
    args = parser.parse_args(argv or None)
    jb = JBrowse()
    if args.admin:
        jb.admin_server()
        return
    if args.upgrade:
        jb.upgrade()
        return
    jb.config(args.indir)


class JBrowse:
    def __init__(self) -> None:
        self.version = config["jbrowse"]["version"]
        document_root = Path(config["jbrowse"]["document_root"]).expanduser()
        self.slug = f"jbrowse-{self.version}"
        self.root = document_root / self.slug

    def create(self) -> None:
        if not self.root.exists():
            args = ["create", self.root]
            args.append(f"--tag=v{self.version}")
            jbrowse(args)
        with (self.root / "version.txt").open() as fin:
            version_txt = fin.read().strip()
            if version_txt != self.version:
                msg = f"{version_txt=} != {self.version=}"
                raise ValueError(msg)

    def admin_server(self) -> None:
        jbrowse(["admin-server", "--root", self.root])

    def upgrade(self) -> None:
        jbrowse(["upgrade", self.root])

    def config(self, indir: Path) -> None:
        self.create()
        jbc = JBrowseConfig(self.root, indir)
        jbc.add()
        jbc.add_external()
        jbc.set_default_session()
        jbc.configure()
        jbc.write_redirect_html(self.slug)


class JBrowseConfig:
    def __init__(self, root: Path, cons_species: Path) -> None:
        self.load = config["jbrowse"]["load"]
        self.cons_dir = cons_species
        self.species = self.cons_dir.name
        vnn_dir = cons_species.parent.parent.resolve()
        self.pairwise_dir = vnn_dir / "pairwise" / self.species
        self.relpath = Path(vnn_dir.name) / self.species
        self.target = root / self.relpath
        self.tracks: list[str] = []
        _log.info(self.target)

    def write_redirect_html(self, slug: str) -> None:
        url = f"/{slug}/?config={self.relpath}/config.json"
        if not cli.dry_run:
            with (self.target / "index.html").open("w") as fout:
                fout.write(redirect_html(url))
        _log.info(f"http://localhost/{Path(slug, self.relpath)}/ -> {url}")

    def add(self) -> None:
        self.target.mkdir(0o755, parents=True, exist_ok=True)
        self.add_assembly()
        self.add_track_gff()
        clades = [x.name for x in self.cons_dir.iterdir() if "-" not in x.name]
        _log.info(clades)
        clades = phylo.sorted_by_len_newicks(clades, reverse=True)
        for clade in clades:
            self.add_phast(clade)
        iter_crai = self.pairwise_dir.rglob("*.cram.crai")
        crams = {cram.parent.parent.name: cram.with_suffix("") for cram in iter_crai}
        for query in phylo.list_species(clades[0]):
            if cram := crams.pop(query, None):
                self.add_track(cram, "alignment", trackid=query, subdir=query)
        for query, cram in crams.items():
            self.add_track(cram, "alignment", trackid=query, subdir=query)

    def add_phast(self, clade: str) -> None:
        clade_dir = self.cons_dir / clade
        for wig in clade_dir.glob("*.bw"):
            stem = wig.stem
            self.add_track(wig, "conservation", trackid=f"{stem}-{clade}", subdir=clade)
        for csi in clade_dir.glob("*.csi"):
            bed = csi.with_suffix("")
            stem = bed.with_suffix("").stem
            self.add_track(bed, "conservation", trackid=f"{stem}-{clade}", subdir=clade)

    def add_external(self) -> None:
        if self.species == "oryza_sativa":
            add_plantregmap(self, self.species)
            add_papers_data(self)
            add_plantdhs(self)
        elif self.species == "solanum_lycopersicum":
            add_plantregmap(self, self.species)

    def add_assembly(self) -> None:
        # --alias, --name, --displayName
        genome = api.genome_fa(self.species)
        name = genome.name.split(".dna_sm.", 1)[0]
        args: subp.Args = ["add-assembly", "--overwrite"]
        args.extend(["--name", name])
        args.extend(["--displayName", name])
        args.extend(["--target", self.target])
        args.extend(["--load", self.load])
        args.append(genome)
        if not (self.target / genome.name).exists():
            jbrowse(args)

    def add_track_gff(self) -> None:
        gff = api.genome_gff3(self.species)
        ngff = gff.with_suffix("").with_suffix("").with_suffix(".name.gff3.gz")
        if ngff.exists():
            gff = ngff
        self.add_track(gff, trackid=gff.parent.name + ".gff3")
        self.text_index()

    def add_track(
        self, file: Path, category: str = "", trackid: str = "", subdir: str = ""
    ) -> None:
        # --description, --config
        args: subp.Args = ["add-track"]
        args.extend(["--target", self.target])
        args.extend(["--load", self.load])
        if subdir:
            args.extend(["--subDir", subdir])
        if trackid:
            args.extend(["--trackId", trackid])
            self.tracks.append(trackid)
        if category:
            args.extend(["--category", category])
        if (csi := Path(str(file) + ".csi")).exists():
            args.extend(["--indexFile", csi])
        args.append(file)
        if not (self.target / subdir / file.name).exists():
            jbrowse(args)

    def text_index(self) -> None:
        # --attributes, --exclude, --file,  --perTrack, --tracks, --dryrun
        args: subp.Args = ["text-index"]
        args.extend(["--target", self.target])
        jbrowse(args)

    def set_default_session(self) -> None:
        args: subp.Args = ["set-default-session"]
        args.extend(["--target", self.target])
        args.extend(["--name", f"New {self.target.name} session"])
        args.extend(["--view", "LinearGenomeView"])
        patt = r"_inProm|_CE_genome-wide"  # redundant subsets
        patt += r"|_H\dK\d"
        patt += r"|SV_all-qin"
        patt += r"|PhyloP|\.net$"
        patt += r"|_DNase$|_NPS$"
        patt += r"|^cns0|^most-cons|cns-poaceae|cns-monocot"
        rex = re.compile(patt)
        tracks = [x for x in self.tracks if not rex.search(x)]
        args.extend(["--tracks", ",".join(tracks)])
        jbrowse(args)

    def configure(self) -> None:
        config_json = self.target / "config.json"
        with config_json.open() as fin:
            cfg = json.load(fin)
        for track in cfg["tracks"]:
            if track["adapter"]["type"].startswith("Bed"):
                set_LinearBasicDisplay(track)
        assembly = cfg["assemblies"][0]
        session = cfg["defaultSession"]
        view = session["views"][0]
        self.set_displayed_regions(view, assembly["name"])
        for track in view["tracks"]:
            track["displays"] = [make_display(track)]
        if refnamealiases := self.make_refnamealiases():
            assembly["refNameAliases"] = refnamealiases
        cfg["configuration"] = make_configuration()
        with config_json.open("w") as fout:
            json.dump(cfg, fout, indent=2)

    def set_displayed_regions(self, view: dict[str, Any], asm_name: str) -> None:
        window_width = config["jbrowse"]["window_width"]
        chrom_sizes = api.chrom_sizes(self.target.name)
        asm_conf = find_config_assembly(self.target.name)
        _log.info(asm_conf)
        location = asm_conf["location"]
        mobj = re.search(r"(\w+)\s*:\s*([\d,]+)\s*(?::|\.{2,})\s*([\d,]+)", location)
        assert mobj is not None, location
        chrom = mobj.group(1)
        start = int(mobj.group(2).replace(",", ""))
        end = int(mobj.group(3).replace(",", ""))
        view["bpPerPx"] = round((end - start) / window_width, 2)
        view["offsetPx"] = int(start / view["bpPerPx"])
        view["displayedRegions"] = [
            {
                "refName": chrom,
                "start": 0,
                "end": chrom_sizes[chrom],
                "reversed": False,
                "assemblyName": asm_name,
            },
        ]

    def make_refnamealiases(self) -> dict[str, Any] | None:
        path = f"chromAlias/{self.species}.chromAlias.txt"
        resources_alias = resources_data(path)
        if not resources_alias.is_file():
            return None
        filename = Path(path).name
        with (self.target / filename).open("w") as fout:
            fout.write(resources_alias.read_text())
        return {
            "adapter": {
                "type": "RefNameAliasAdapter",
                "location": {
                    "uri": filename,
                    "locationType": "UriLocation",
                },
            },
        }


def make_display(track: dict[str, Any]) -> dict[str, Any]:
    item = {}
    if track["type"] == "FeatureTrack":
        if "gff3" in track["configuration"]:
            item = {
                "type": "LinearBasicDisplay",
                "height": 60,
            }
        else:  # bed
            item = {
                "type": "LinearBasicDisplay",
                "height": 30,
                "trackShowLabels": False,
                "trackShowDescriptions": False,
            }
    elif track["type"] == "QuantitativeTrack":
        item = make_LinearWiggleDisplay(track["configuration"])
    elif track["type"] == "AlignmentsTrack":
        item = {
            "type": "LinearPileupDisplay",
            "height": 20,
        }
    item["configuration"] = "-".join([track["configuration"], str(item["type"])])
    return item


def set_LinearBasicDisplay(track: dict[str, Any]) -> None:  # noqa: N802
    track["displays"] = [
        {
            "type": "LinearBasicDisplay",
            "displayId": track["trackId"] + "-LinearBasicDisplay",
            "renderer": {
                "type": "SvgFeatureRenderer",
                "color1": clade_color(track["trackId"]),
                "height": 10,
            },
        }
    ]


def make_LinearWiggleDisplay(configuration: str) -> dict[str, Any]:  # noqa: N802
    item: dict[str, Any] = {
        "type": "LinearWiggleDisplay",
        "height": 40,
        "color": clade_color(configuration),
    }
    if "phast" in configuration.lower():
        item["constraints"] = {"max": 1, "min": 0}
    return item


def clade_color(label: str, default: str = "#888888") -> str:
    colors = {
        "bep": "#C82828",
        "poaceae": "#C8641E",
        "monocot": "#C8B414",
        "solanum": "#C82828",
        "solanaceae": "#C8641E",
        "lamiids": "#C8B414",
    }
    clade = label.rsplit("-", 1)[-1]
    return colors.get(clade, default)


def make_configuration() -> dict[str, Any]:
    return {"theme": make_theme()}


def make_theme() -> dict[str, Any]:
    return {
        "palette": {
            "primary": {"main": "#186038"},
            "secondary": {"main": "#009259"},
            "tertiary": {"main": "#8fc21f"},
            "quaternary": {"main": "#d9e000"},
        },
    }


def add_plantdhs(jbc: JBrowseConfig) -> None:
    for path in fs.sorted_naturally(plantdhs.db_prefix().glob("Rice_*.bw")):
        trackid = path.stem.removeprefix("Rice_")
        jbc.add_track(path, "plantdhs", trackid=trackid)
    for path in fs.sorted_naturally(plantdhs.db_prefix().glob("*.gff.gz")):
        jbc.add_track(path, "plantdhs", trackid=path.stem)


def add_plantregmap(jbc: JBrowseConfig, species: str) -> None:
    for path in fs.sorted_naturally(plantregmap.rglob("*.bw", species)):
        trackid = path.with_suffix(".bedGraph").name
        jbc.add_track(path, "plantregmap", trackid=trackid)
    for path in fs.sorted_naturally(plantregmap.rglob("*.cram", species)):
        trackid = path.with_suffix(".net").name
        jbc.add_track(path, "plantregmap", trackid=trackid)
    for path in fs.sorted_naturally(plantregmap.rglob("*.gff.gz", species)):
        trackid = re.sub(r"_[^_]+\.gff\.gz$", "", path.name)
        jbc.add_track(path, "plantregmap", trackid=trackid)
    for path in fs.sorted_naturally(plantregmap.rglob("*.bed.gz", species)):
        trackid = re.sub(r"(_normal)?\.bed\.gz$", "", path.name)
        jbc.add_track(path, "plantregmap", trackid=trackid)


def add_papers_data(jbc: JBrowseConfig) -> None:
    for path in fs.sorted_naturally(api.prefix("papers").glob("*.bed.gz")):
        jbc.add_track(path, "papers", trackid=path.with_suffix("").stem)
    suzuemon = api.prefix("suzuemon")
    if (f := suzuemon / "sv_with_DEG.bed.gz").exists():
        jbc.add_track(f, "papers", trackid="SV_DEG-qin2021", subdir="suzuemon")
    if (f := suzuemon / "SV.bed.gz").exists():
        jbc.add_track(f, "papers", trackid="SV_all-qin2021", subdir="suzuemon")


def jbrowse(args: subp.Args) -> None:
    subp.run(["jbrowse", *args])


def npx_jbrowse(args: subp.Args, version: str = "") -> None:
    pkg = "@jbrowse/cli"
    pkg = f"{pkg}@{version}" if version else pkg
    subp.run(["npx", pkg, *args])


def redirect_html(url: str) -> str:
    meta = f"""<meta http-equiv="refresh" content="1; URL={url}">"""
    return f"""<html><head>{meta}</head><body>Redirecting</body></html>"""


def find_config_assembly(species: str) -> dict[str, Any]:
    for entry in config["jbrowse"]["assemblies"]:
        if entry["species"] == species:
            return entry
    msg = f"{species} not in jbrowse.assemblies"
    raise ValueError(msg)


if __name__ == "__main__":
    main()
