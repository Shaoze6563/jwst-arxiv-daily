import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector import Paper, base_arxiv_id, daily_html_report, parse_atom, rank_paper, write_catalogs


CONFIG = {
    "jwst_terms": ["JWST", "NIRCam"],
    "galaxy_terms": ["galaxy", "galaxies"],
    "related_terms": ["star formation", "AGN"],
    "minimum_score": 5,
}


class CollectorTests(unittest.TestCase):
    def paper(self, title, abstract):
        now = datetime(2026, 7, 11, tzinfo=timezone.utc)
        return Paper(
            arxiv_id="2607.00001",
            title=title,
            abstract=abstract,
            authors=("A. Author",),
            categories=("astro-ph.GA",),
            published=now,
            updated=now,
            abs_url="https://arxiv.org/abs/2607.00001",
            pdf_url="https://arxiv.org/pdf/2607.00001",
        )

    def test_base_id_removes_version(self):
        self.assertEqual(base_arxiv_id("https://arxiv.org/abs/2607.12345v2"), "2607.12345")

    def test_relevant_galaxy_paper_is_ranked(self):
        result = rank_paper(
            self.paper("JWST observations of distant galaxies", "We study star formation."),
            CONFIG,
        )
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result.score, 5)

    def test_instrument_only_paper_is_rejected(self):
        result = rank_paper(
            self.paper("JWST detector calibration", "We characterize detector noise."),
            CONFIG,
        )
        self.assertIsNone(result)

    def test_atom_parser(self):
        payload = b'''<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <id>http://arxiv.org/abs/2607.00001v1</id>
            <updated>2026-07-10T00:00:00Z</updated>
            <published>2026-07-10T00:00:00Z</published>
            <title> A JWST galaxy paper </title>
            <summary> An abstract. </summary>
            <author><name>A. Author</name></author>
            <category term="astro-ph.GA"/>
            <link title="pdf" href="http://arxiv.org/pdf/2607.00001v1"/>
          </entry>
        </feed>'''
        papers = parse_atom(payload)
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].arxiv_id, "2607.00001")
        self.assertEqual(papers[0].authors, ("A. Author",))
        self.assertTrue(papers[0].pdf_url.startswith("https://"))

    def test_daily_html_escapes_content(self):
        result = rank_paper(
            self.paper("JWST galaxies <near & far>", "An AGN & star formation study."),
            CONFIG,
        )
        page = daily_html_report([result], "2026-07-11")
        self.assertIn("&lt;near &amp; far&gt;", page)
        self.assertIn("<!doctype html>", page)

    def test_catalog_hierarchy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            month = root / "2026" / "07"
            month.mkdir(parents=True)
            (month / "2026-07-11.html").write_text("daily", encoding="utf-8")
            write_catalogs(root, "2026", "07")
            self.assertTrue((month / "index.html").exists())
            self.assertTrue((root / "2026" / "index.html").exists())
            self.assertTrue((root / "index.html").exists())
            self.assertIn("2026-07-11.html", (month / "index.html").read_text())


if __name__ == "__main__":
    unittest.main()
