import pytest
from aligons.db import phylo

newick_standard = """(
    (
        oryza_sativa:0.1,
        hordeum_vulgare:0.2
    )bep:0.3,
    panicum_hallii_fil2:0.4
)poaceae:0.5;"""


@pytest.fixture()
def newick():
    return phylo.remove_whitespace(newick_standard)


@pytest.fixture()
def newick_xlength(newick: str):
    return phylo.remove_lengths(newick)


@pytest.fixture()
def newick_popular(newick: str):  # mod
    return phylo.remove_inner_names(newick)


@pytest.fixture()
def newick_xlength_tips(newick_xlength: str):
    return phylo.remove_inner_names(newick_xlength)


@pytest.fixture()
def newick_short(newick: str):  # mod
    return phylo.shorten_names(newick)


@pytest.fixture()
def newick_xlength_short_tips(newick_xlength_tips: str):  # mod
    return phylo.shorten_names(newick_xlength_tips)


def test_extract_lengths(newick_xlength: str):
    assert phylo.extract_lengths(newick_standard) == [0.1, 0.2, 0.3, 0.4, 0.5]
    assert phylo.extract_lengths(newick_xlength) == []


def test_extract_labels(
    newick_xlength: str,
    newick_popular: str,
    newick_xlength_tips: str,
    newick_short: str,
    newick_xlength_short_tips: str,
):
    tip_names = ["oryza_sativa", "hordeum_vulgare", "panicum_hallii_fil2"]
    inner_names = ["bep", "poaceae"]
    names = tip_names[:2] + ["bep", tip_names[2], "poaceae"]
    short_names = ["osat", "hvul", "bep", "phal", "poaceae"]
    short_tip_names = [short_names[i] for i in (0, 1, 3)]
    assert phylo.extract_names(newick_standard) == names
    assert phylo.extract_names(newick_xlength) == names
    assert phylo.extract_names(newick_popular) == tip_names
    assert phylo.extract_names(newick_xlength_tips) == tip_names
    assert phylo.extract_names(newick_short) == short_names
    assert phylo.extract_names(newick_xlength_short_tips) == short_tip_names
    assert phylo.extract_tip_names(newick_standard) == tip_names
    assert phylo.extract_tip_names(newick_xlength) == tip_names
    assert phylo.extract_tip_names(newick_popular) == tip_names
    assert phylo.extract_tip_names(newick_xlength_tips) == tip_names
    assert phylo.extract_tip_names(newick_short) == short_tip_names
    assert phylo.extract_tip_names(newick_xlength_short_tips) == short_tip_names
    assert phylo.extract_inner_names(newick_standard) == inner_names
    assert phylo.extract_inner_names(newick_xlength) == inner_names
    assert phylo.extract_inner_names(newick_popular) == []
    assert phylo.extract_inner_names(newick_xlength_tips) == []
    assert phylo.extract_inner_names(newick_short) == inner_names
    assert phylo.extract_inner_names(newick_xlength_short_tips) == []


def test_remove_inner(
    newick_xlength: str,
    newick_popular: str,
    newick_xlength_tips: str,
    newick_xlength_short_tips: str,
):
    assert (
        newick_popular
        == "((oryza_sativa:0.1,hordeum_vulgare:0.2):0.3,panicum_hallii_fil2:0.4):0.5;"
    )
    assert (
        newick_xlength_tips == "((oryza_sativa,hordeum_vulgare),panicum_hallii_fil2);"
    )
    assert newick_xlength_short_tips == "((osat,hvul),phal);"
    assert phylo.remove_inner(newick_xlength) == newick_xlength_tips
    assert phylo.remove_inner_names(newick_xlength) == newick_xlength_tips
    assert phylo.remove_inner_names(newick_popular) == newick_popular
    assert phylo.remove_inner(newick_xlength_tips) == newick_xlength_tips
    assert phylo.remove_inner(newick_xlength_short_tips) == newick_xlength_short_tips


def test_remove_lengths(
    newick_xlength: str,
    newick_popular: str,
    newick_xlength_tips: str,
    newick_xlength_short_tips: str,
):
    assert (
        newick_xlength
        == "((oryza_sativa,hordeum_vulgare)bep,panicum_hallii_fil2)poaceae;"
    )
    assert phylo.remove_lengths(newick_xlength) == newick_xlength
    assert phylo.remove_lengths(newick_popular) == newick_xlength_tips
    assert phylo.remove_lengths(newick_xlength_short_tips) == "((osat,hvul),phal);"


def test_shorten_labels(
    newick_short: str,
    newick_xlength_tips: str,
    newick_xlength_short_tips: str,
):
    assert newick_short == "((osat:0.1,hvul:0.2)bep:0.3,phal:0.4)poaceae:0.5;"
    assert phylo.shorten_names(newick_short) == newick_short
    assert newick_xlength_short_tips == "((osat,hvul),phal);"
    assert phylo.shorten_names(newick_xlength_tips) == newick_xlength_short_tips
    assert phylo.shorten_names(newick_xlength_short_tips) == newick_xlength_short_tips


def test_shorten():
    assert phylo.shorten("Oryza_sativa") == "osat"


def test_remove_whitespace():
    x = """ ( (A , \t B),
    C) ;\n """
    assert phylo.remove_whitespace(x) == "((A,B),C);"


def test_newickize(newick: str):
    root = phylo.parse_newick(newick)
    assert phylo.newickize(root) == newick


def test_select_clade(newick: str, newick_xlength: str):
    exp = "(oryza_sativa:0.1,hordeum_vulgare:0.2)bep:0.3;"
    assert phylo.select_clade(newick, "bep") == exp
    assert phylo.select_clade(newick_xlength, "bep") == phylo.remove_lengths(exp)


def test_select_tips():
    tree = "((((A,B),(C,D)),(E,(F,G))),H);"
    subtree = "((A,C),E);"
    tips = phylo.extract_names(subtree)
    assert phylo.select_tips(tree, tips) == subtree


def test_print_graph(capsys: pytest.CaptureFixture[str]):
    newick = "(one:1,(two:2,three:3)anc:0.5)root"
    phylo.print_graph(newick, 1)
    captured = capsys.readouterr()
    assert (
        captured.out
        == """\
 root
├─ one
└─ anc
  ├─ two
  └─ three
"""
    )
    phylo.print_graph(newick, 2)
    captured = capsys.readouterr()
    assert (
        captured.out
        == """\
┬─ one
└─┬─ two
  └─ three
"""
    )
    phylo.print_graph(newick, 3)
    captured = capsys.readouterr()
    assert (
        captured.out
        == """\
┬─── one
└─┬─ two
  └─ three
"""
    )
    phylo.print_graph(newick, 4)
    captured = capsys.readouterr()
    assert (
        captured.out
        == """\
┬───── one
└─┬─── two
  └─ three
"""
    )
