"""orshare parse_raw: the two author-share datasets in the rankings page text."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from orshare_data import parse_raw  # noqa: E402

RAW = (
    "Compare text request share by model author on OpenRouter.\n\n"
    "Sep 14\n30%\n60%\n100%\n"
    "1.\ndeepseek\n1.14B\n24.2%\n"
    "2.\ngoogle\n974M\n20.8%\n"
    "10.\nOthers\n523M\n11.1%\n"
    "Market share by model author, as text\n\n"
    "Text summary of the Market Share chart above. Share of text requests made on OpenRouter "
    "in the week beginning Sep 14, 2026, with the change in each author's requests against the "
    "week before it. deepseek leads at 25.4% of the week's requests.\n\n"
    "Model authors ranked by their share of text requests on OpenRouter in the most recent complete week\n"
    "Rank\tAuthor\tShare of requests\tChange in requests\n"
    "1\tdeepseek\t25.4%\t+9%\n"
    "2\tgoogle\t18.6%\t-3%\n"
    "\tAll other authors\t9.3%\t+3%\n"
)


def test_parse_extracts_both_datasets():
    p = parse_raw(RAW)
    assert p["in_progress_week"]["deepseek"] == 24.2
    assert p["in_progress_week"]["google"] == 20.8
    assert p["in_progress_week"]["Others"] == 11.1
    assert p["last_complete_week"]["deepseek"] == 25.4
    assert p["last_complete_week"]["Others"] == 9.3
    assert "All other authors" not in p["last_complete_week"]
    assert p["summary"]["leader"] == "25.4"


def test_parse_handles_missing_sections():
    assert parse_raw("nothing here") == {}
