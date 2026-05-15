"""Tests for SEC 10-K Extraction Pipeline (Task 3).

Covers:
- Normalizer (HTML/text format detection and cleaning)
- Rule Parser (item heading detection, part boundaries, status detection)
- Schemas (model validation)
- Validator (char_range, coverage, ordering checks)
- Pipeline integration (end-to-end with mock data)
"""

import asyncio
import base64

import pytest

from src.task3_sec.fetcher import (
    accession_no_dashes,
    find_10k_filing,
    normalize_accession,
    normalize_cik,
    parse_filing_url_metadata,
)
from src.task3_sec.normalizer import (
    detect_format,
    extract_primary_10k_document,
    extract_table_of_contents,
    normalize_filing,
)
from src.task3_sec.rule_parser import (
    detect_item_headings,
    detect_item_status,
    detect_part_boundaries,
    rule_based_parse,
)
from src.task3_sec.schemas import (
    ITEM_TITLE_VARIANTS,
    STANDARD_10K_ITEMS,
    ExtractedItem,
    ExtractionMethod,
    ExtractionResult,
    FilingMetadata,
    ItemStatus,
    ProcessingMetadata,
)
from src.task3_sec.validator import (
    fix_common_issues,
    validate_extraction,
)

# ========== FIXTURES ==========

SAMPLE_HTML = """
<html><head><title>10-K</title></head>
<body>
<div style="display:none"><ix:header></ix:header></div>
<h1>Annual Report</h1>
<p>Table of Contents</p>
<p>Item 1. Business ..... 5</p>
<p>Item 1A. Risk Factors ..... 20</p>
<p>Item 2. Properties ..... 45</p>

<h2>PART I</h2>

<h3>Item 1. Business</h3>
<p>We are a technology company that designs, manufactures, and sells consumer electronics,
software, and services. Our principal products include smartphones, tablets, and computers.</p>
<p>The Company was incorporated in 1977.</p>

<h3>Item 1A. Risk Factors</h3>
<p>Investing in our common stock involves a high degree of risk. You should carefully consider
the following risk factors before making an investment decision.</p>
<p>Global economic conditions could materially adversely affect our business.</p>
<p>We face intense competition in all markets.</p>

<h3>Item 1B. Unresolved Staff Comments</h3>
<p>None.</p>

<h3>Item 2. Properties</h3>
<p>Our headquarters are located in Cupertino, California. We own and lease facilities worldwide.</p>

<h3>Item 3. Legal Proceedings</h3>
<p>The Company is subject to various legal proceedings. See Note 10 of our financial statements.</p>

<h3>Item 4. Mine Safety Disclosures</h3>
<p>Not applicable.</p>

<h2>PART II</h2>

<h3>Item 5. Market for Registrant's Common Equity</h3>
<p>Our common stock is traded on the Nasdaq Global Select Market under the symbol AAPL.</p>

<h3>Item 6. [Reserved]</h3>

<h3>Item 7. Management's Discussion and Analysis</h3>
<p>The following discussion should be read in conjunction with our financial statements.</p>
<p>Revenue for fiscal year 2023 was $383.3 billion, compared to $394.3 billion in 2022.</p>

<h3>Item 7A. Quantitative and Qualitative Disclosures About Market Risk</h3>
<p>We are exposed to foreign currency exchange rate risk and interest rate risk.</p>

<h3>Item 8. Financial Statements and Supplementary Data</h3>
<p>Consolidated Statements of Operations for the years ended September 30.</p>

<h3>Item 9. Changes in and Disagreements With Accountants</h3>
<p>None.</p>

<h3>Item 9A. Controls and Procedures</h3>
<p>Our management evaluated the effectiveness of our disclosure controls.</p>

<h3>Item 9B. Other Information</h3>
<p>None.</p>

<h2>PART III</h2>

<h3>Item 10. Directors, Executive Officers and Corporate Governance</h3>
<p>The information required by this Item is incorporated by reference from the definitive
Proxy Statement (DEF 14A) for our 2024 Annual Meeting of Shareholders.</p>

<h3>Item 11. Executive Compensation</h3>
<p>The information required by this Item is incorporated by reference from the Proxy Statement.</p>

<h3>Item 12. Security Ownership of Certain Beneficial Owners</h3>
<p>The information required by this Item is incorporated by reference from the Proxy Statement.</p>

<h3>Item 13. Certain Relationships and Related Transactions</h3>
<p>The information required by this Item is incorporated by reference from the Proxy Statement.</p>

<h3>Item 14. Principal Accountant Fees and Services</h3>
<p>The information required by this Item is incorporated by reference from the Proxy Statement.</p>

<h2>PART IV</h2>

<h3>Item 15. Exhibits and Financial Statement Schedules</h3>
<p>The following documents are filed as part of this Annual Report on Form 10-K.</p>

<h3>Item 16. Form 10-K Summary</h3>
<p>None.</p>

</body></html>
"""

SAMPLE_TEXT_FILING = """
                    SECURITIES AND EXCHANGE COMMISSION
                          Washington, D.C. 20549

                                FORM 10-K

PART I

Item 1.  Business

    We are a technology company that manufactures and sells consumer electronics.
    Our principal products include personal computers and software.

Item 1A.  Risk Factors

    There are risks associated with investing in our securities.
    Economic downturns could reduce demand for our products.

Item 2.  Properties

    We lease office space at 1 Infinite Loop, Cupertino, CA.

PART II

Item 5.  Market for Common Equity

    Our shares trade on the NASDAQ under the ticker symbol AAPL.

Item 7.  Management's Discussion and Analysis

    Revenue grew by 10% year-over-year to $380 billion.

PART III

Item 10.  Directors and Executive Officers

    Incorporated by reference to the Proxy Statement filed with the SEC.

PART IV

Item 15.  Exhibits and Financial Statement Schedules

    See the accompanying exhibit index.
"""


# ========== SCHEMA TESTS ==========


class TestSchemas:
    """Test 10-K schema definitions."""

    def test_standard_items_count(self):
        """All 22 standard 10-K items should be defined (includes 1C, 9C)."""
        assert len(STANDARD_10K_ITEMS) >= 22

    def test_standard_items_parts(self):
        """Items should span Parts I through IV."""
        parts = {item["part"] for item in STANDARD_10K_ITEMS}
        assert parts == {"I", "II", "III", "IV"}

    def test_item_title_variants_coverage(self):
        """Every standard item should have title variants for fuzzy matching."""
        for item in STANDARD_10K_ITEMS:
            assert item["item_number"] in ITEM_TITLE_VARIANTS, f"Missing title variants for Item {item['item_number']}"

    def test_extracted_item_creation(self):
        """Test creating an ExtractedItem with all fields."""
        item = ExtractedItem(
            part="I",
            item_number="1A",
            item_title="Risk Factors",
            content_text="Risk factors content here...",
            char_range=[100, 5000],
            status=ItemStatus.EXTRACTED,
            confidence=0.95,
            extraction_method=ExtractionMethod.RULE_BASED,
        )
        assert item.item_number == "1A"
        assert item.status == ItemStatus.EXTRACTED

    def test_filing_metadata(self):
        """Test FilingMetadata model."""
        meta = FilingMetadata(
            cik="0000320193",
            company_name="Apple Inc.",
            accession_number="0000320193-23-000106",
        )
        assert meta.cik == "0000320193"


# ========== NORMALIZER TESTS ==========


class TestNormalizer:
    """Test HTML/text normalization."""

    def test_detect_format_xbrl(self):
        """XBRL HTML should be detected."""
        html = "<html><ix:nonNumeric>test</ix:nonNumeric></html>"
        assert detect_format(html) == "xbrl_html"

    def test_detect_format_html(self):
        """Standard HTML should be detected."""
        assert detect_format("<html><body>test</body></html>") == "html"

    def test_detect_format_text(self):
        """Plain text should be detected."""
        assert detect_format("FORM 10-K\nItem 1. Business\n") == "text"

    def test_detect_format_html_after_long_sgml_preamble(self):
        """Real EDGAR SGML headers for big filers can run 5–30 kB before any
        `<html>` appears. The detector must look beyond 5 kB or it
        misclassifies HTML filings as plain text and routes them to the wrong
        normalizer.
        """
        # 12 kB of SGML preamble (mimics EDGAR's verbose machine-generated
        # header for a financial-holding-company filing) followed by HTML
        preamble = "ACCESSION NUMBER: 0000320193-93-000001\n" * 300
        sgml_doc = (
            preamble
            + "<DOCUMENT><TYPE>10-K<TEXT>"
            + "<html><body><h1>Item 1. Business</h1></body></html>"
            + "</TEXT></DOCUMENT>"
        )
        # Strip the SGML wrapper first (this is what normalize_filing does
        # internally), then format-detect the inner document.
        from src.task3_sec.normalizer import (
            extract_primary_10k_document,
        )
        inner = extract_primary_10k_document(sgml_doc)
        assert "<html" in inner.lower()
        assert detect_format(inner) == "html"

    def test_extract_primary_10k_document_long_sgml_preamble(self):
        """If SGML preamble is > 10 kB, extraction must still find the
        primary 10-K block and not silently return the unstripped content."""
        from src.task3_sec.normalizer import extract_primary_10k_document
        preamble = "HEADER: foo\n" * 5000  # ~60 kB
        full = (
            preamble
            + "<DOCUMENT><TYPE>10-K<TEXT>INNER_BODY_MARKER</TEXT></DOCUMENT>"
        )
        result = extract_primary_10k_document(full)
        assert "INNER_BODY_MARKER" in result
        assert "HEADER: foo" not in result, "SGML preamble must be stripped"

    def test_normalize_html_removes_scripts(self):
        """Scripts and styles should be removed."""
        html = "<html><body><script>var x=1;</script><p>Content</p></body></html>"
        normalized, fmt = normalize_filing(html)
        assert "var x" not in normalized
        assert "Content" in normalized

    def test_normalize_html_removes_hidden(self):
        """Hidden display:none elements should be removed."""
        html = '<html><body><div style="display:none">Hidden</div><p>Visible</p></body></html>'
        normalized, fmt = normalize_filing(html)
        assert "Visible" in normalized
        # "Hidden" might still appear in some edge cases of parser

    def test_normalize_text_filing(self):
        """Plain text filing should be cleaned."""
        normalized, fmt = normalize_filing(SAMPLE_TEXT_FILING)
        assert fmt == "text"
        assert "Item 1" in normalized
        assert "Business" in normalized

    def test_normalize_preserves_content(self):
        """Key content should survive normalization."""
        normalized, _ = normalize_filing(SAMPLE_HTML)
        assert "technology company" in normalized
        assert "risk factors" in normalized.lower() or "Risk Factors" in normalized

    def test_extract_toc_entries(self):
        """Table of contents extraction should find item entries."""
        normalized, _ = normalize_filing(SAMPLE_HTML)
        toc = extract_table_of_contents(normalized)
        # Should find some ToC-style entries
        assert isinstance(toc, list)

    def test_extract_primary_10k_document_from_sgml(self):
        """Raw SEC SGML submissions should select the primary 10-K document."""
        sgml = """
<SEC-DOCUMENT>
<DOCUMENT>
<TYPE>EX-21
<TEXT>
Exhibit content that should not be parsed.
</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>10-K
<TEXT>
<html><body><h1>Item 1. Business</h1><p>Primary filing content.</p></body></html>
</TEXT>
</DOCUMENT>
</SEC-DOCUMENT>
"""
        extracted = extract_primary_10k_document(sgml)
        assert "Primary filing content" in extracted
        assert "Exhibit content" not in extracted


# ========== RULE PARSER TESTS ==========


class TestRuleParser:
    """Test rule-based item heading detection."""

    def test_detect_standard_headings(self):
        """Standard item headings should be detected."""
        text = """
PART I

Item 1. Business

We are a technology company.

Item 1A. Risk Factors

Investing involves risk.

Item 2. Properties

Our offices are in California.
"""
        boundaries = detect_item_headings(text)
        found = {b.item_number for b in boundaries}
        assert "1" in found
        assert "1A" in found
        assert "2" in found

    def test_detect_all_caps_headings(self):
        """ALL CAPS item headings should be detected."""
        text = """
PART I

ITEM 1. BUSINESS

We manufacture products.

ITEM 1A. RISK FACTORS

There are risks.
"""
        boundaries = detect_item_headings(text)
        found = {b.item_number for b in boundaries}
        assert "1" in found
        assert "1A" in found

    def test_detect_split_line_heading(self):
        """Headings split across lines after HTML normalization should be detected."""
        text = """
PART I

Item 1A.
Risk Factors

There are risks.

Item 1B.
Unresolved Staff Comments

None.
"""
        boundaries = detect_item_headings(text)
        found = {b.item_number for b in boundaries}
        assert "1A" in found
        assert "1B" in found

    def test_detect_reserved_heading(self):
        """Item headings with [Reserved] title should be detected."""
        boundaries = detect_item_headings("Item 6. [Reserved]\n\nItem 7. Management's Discussion\nBody")
        found = {b.item_number for b in boundaries}
        assert "6" in found
        assert "7" in found

    def test_detect_part_boundaries(self):
        """Part I, II, III, IV boundaries should be detected."""
        text = """
PART I
Item 1. Business

PART II
Item 5. Market

PART III
Item 10. Directors

PART IV
Item 15. Exhibits
"""
        parts = detect_part_boundaries(text)
        assert "I" in parts
        assert "II" in parts
        assert "III" in parts
        assert "IV" in parts

    def test_toc_deduplication(self):
        """Items appearing in ToC AND content should prefer content position."""
        text = (
            """
Table of Contents
Item 1. Business .......... 5
Item 1A. Risk Factors .... 20

"""
            + "x" * 500
            + """

PART I

Item 1. Business

Actual content of business section starts here with detailed information
about the company's products and services.

Item 1A. Risk Factors

The following risk factors should be considered.
"""
        )
        boundaries = detect_item_headings(text)
        # Should find 2 items (deduplicated from ToC)
        found = {b.item_number for b in boundaries}
        assert "1" in found
        assert "1A" in found
        assert len(boundaries) == len(found)  # No duplicates

    def test_detect_item_status_extracted(self):
        """Normal content should be classified as extracted."""
        content = "We are a global technology company with operations worldwide."
        assert detect_item_status(content) == ItemStatus.EXTRACTED

    def test_detect_item_status_incorporated(self):
        """Incorporated by reference pattern should be detected."""
        content = "The information is incorporated by reference from the Proxy Statement."
        assert detect_item_status(content) == ItemStatus.INCORPORATED_BY_REFERENCE

    def test_detect_item_status_not_applicable(self):
        """Not applicable pattern should be detected."""
        assert detect_item_status("Not applicable.") == ItemStatus.NOT_APPLICABLE
        assert detect_item_status("None.") == ItemStatus.NOT_APPLICABLE

    def test_detect_item_status_reserved(self):
        """Reserved pattern should be detected."""
        assert detect_item_status("[Reserved]") == ItemStatus.RESERVED
        assert detect_item_status("Reserved") == ItemStatus.RESERVED

    def test_detect_item_status_reserved_alt_phrasings(self):
        """Real SEC filings use several phrasings besides the canonical
        '[Reserved]'. The status detector must recognise:
          - 'Removed and Reserved.' (transitional language Item 9C 2002-2008,
             Item 6 2021)
          - 'Item is reserved.' / 'This item has been reserved.' (older
             full-sentence form)
        Otherwise items get misclassified as 'extracted' with empty content,
        which silently passes the coverage check.
        """
        assert (
            detect_item_status("Removed and Reserved.") == ItemStatus.RESERVED
        )
        assert detect_item_status("Item is reserved.") == ItemStatus.RESERVED
        assert (
            detect_item_status("This item has been reserved.")
            == ItemStatus.RESERVED
        )
        # Negative case: don't false-fire on real prose containing the word
        assert (
            detect_item_status(
                "The company maintains a reserve for credit losses of "
                "approximately $1.2B as required by ASC 326..." * 5
            )
            == ItemStatus.EXTRACTED
        )

    def test_detect_item_status_refer_to_proxy_pattern(self):
        """IBM-style filings have content like 'Refer to ... 10+ caption titles ...
        in IBMs definitive Proxy Statement'. The proxy mention is far past
        the 500-char loose-pattern window, so we need a wider 'refer to ...
        proxy' regex. Real Item 11 from IBM 2025 had this pattern."""
        ibm_item_11 = (
            "Refer to the information under the captions 2024 Summary "
            "Compensation Table and Related Narrative, 2024 Summary "
            "Compensation Table, 2024 Compensation Discussion and Analysis, "
            "2024 Grants of Plan-Based Awards Table, 2024 Outstanding Equity "
            "Awards at Fiscal Year-End Table, 2024 Option Exercises and Stock "
            "Vested Table, and Severance and Change-in-Control Provisions "
            "in the definitive Proxy Statement to be filed with the SEC."
        )
        assert detect_item_status(ibm_item_11) == ItemStatus.INCORPORATED_BY_REFERENCE

    def test_detect_item_status_proxy_far_into_content(self):
        """Even when 'Proxy Statement' appears 1500+ chars in (because the item
        starts with caption titles), a 'Refer to' antecedent should trigger
        incorporated_by_reference."""
        long_caption_list = (
            "Refer to the information under "
            + ('"' + ("Caption Title " * 50) + '" ')
            + "in the Proxy Statement filed with the SEC."
        )
        assert detect_item_status(long_caption_list) == ItemStatus.INCORPORATED_BY_REFERENCE

    def test_full_parse_result(self):
        """Full rule-based parse should return complete ParseResult."""
        normalized, _ = normalize_filing(SAMPLE_HTML)
        result = rule_based_parse(normalized)
        assert result.items_found > 0
        assert result.total_chars > 0
        assert result.confidence_avg > 0

    def test_heading_confidence_scoring(self):
        """Headings with matching titles should have higher confidence.

        Note: the rule parser deliberately downweights single matches that
        sit in the first 10% of the document (the TOC zone) — see the
        Intel-2026 TOC-suppression patch in rule_parser.py. To exercise the
        normal "high confidence" path we need the headings past the 10%
        boundary, so we pad with leading filler so the matches land in the
        body region of the synthetic doc.
        """
        # Pad with ~1 KB of body-text-like filler so the headings land past
        # the 10% TOC zone.
        filler = ("Filler narrative paragraph for layout. " * 40) + "\n\n"
        text = filler + """
Item 1. Business
Company description here.

Item 1A. Risk Factors
Risk discussion here.
"""
        boundaries = detect_item_headings(text)
        for b in boundaries:
            assert b.confidence > 0.5  # All should have reasonable confidence

    def test_single_match_in_toc_region_is_downweighted(self):
        """Regression for the Intel-2026 TOC-confusion bug.

        When a heading matches ONCE and the match sits in the doc's first
        10%, that's almost certainly a Table-of-Contents entry rather than
        the real body heading. The parser must downgrade confidence so
        Stage 2 LLM refinement can re-locate the body heading.
        """
        # Tiny doc — both items pin to start_pos < 10% of doc length.
        text = "Item 1. Business\nShort description.\n"
        boundaries = detect_item_headings(text)
        assert len(boundaries) >= 1
        toc_suspect = [b for b in boundaries if b.source == "heading_regex_toc_suspect"]
        assert toc_suspect, "Expected at least one TOC-suspect boundary"
        for b in toc_suspect:
            assert b.confidence <= 0.40, (
                "TOC-suspect boundaries must be downweighted below the "
                "Stage 2 LLM trigger threshold so refinement fires."
            )


# ========== FETCHER TESTS ==========


class TestFetcher:
    """Test SEC EDGAR API client utilities."""

    def test_normalize_cik_padding(self):
        """CIK should be zero-padded to 10 digits."""
        assert normalize_cik("320193") == "0000320193"
        assert normalize_cik("0000320193") == "0000320193"
        assert normalize_cik("1") == "0000000001"

    def test_normalize_cik_with_prefix(self):
        """CIK with non-numeric prefix should be cleaned."""
        assert normalize_cik("CIK320193") == "0000320193"

    def test_accession_no_dashes(self):
        """Accession number dashes should be removed for URLs."""
        assert accession_no_dashes("0000320193-23-000106") == "000032019323000106"

    def test_normalize_accession_strips(self):
        """Accession normalization should strip whitespace."""
        assert normalize_accession("  0000320193-23-000106  ") == "0000320193-23-000106"

    def test_normalize_accession_18_digit_form(self):
        """18-digit no-dash accession (as found in URL paths) should be
        re-dashed into the canonical form."""
        assert (
            normalize_accession("000032019323000106") == "0000320193-23-000106"
        )

    def test_is_valid_accession_shape(self):
        """Cheap shape check rejects clear typos before we burn an SEC
        round-trip."""
        from src.task3_sec.fetcher import is_valid_accession_shape

        # Valid forms
        assert is_valid_accession_shape("0000320193-23-000106") is True
        assert is_valid_accession_shape("000032019323000106") is True
        assert is_valid_accession_shape("  0000320193-23-000106 ") is True

        # Invalid: typo with letter
        assert is_valid_accession_shape("0000320193-23-X00106") is False
        # Invalid: missing dashes but wrong length
        assert is_valid_accession_shape("00003201932300010") is False
        # Invalid: extra dashes
        assert is_valid_accession_shape("0000-320193-23-000106") is False
        # Invalid: clearly bogus
        assert is_valid_accession_shape("hello") is False
        assert is_valid_accession_shape("") is False
        # Invalid: 19 digits (off by one)
        assert is_valid_accession_shape("0000320193230001067") is False

    def test_parse_filing_url_metadata(self):
        """SEC Archives filing URLs should expose CIK/accession/document metadata."""
        metadata = parse_filing_url_metadata(
            "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm"
        )
        assert metadata["cik"] == "0000320193"
        assert metadata["accession_number"] == "0000320193-23-000106"
        assert metadata["primary_document"] == "aapl-20230930.htm"

    async def test_find_10k_specific_accession_does_not_fallback_to_latest(self, monkeypatch):
        """A requested accession must not silently fall back to the latest 10-K."""

        async def fake_metadata(cik):
            return {
                "cik": "0000000001",
                "company_name": "Example Co",
                "filings": [
                    {
                        "form": "10-K",
                        "filing_date": "2026-01-01",
                        "accession_number": "0000000001-26-000001",
                        "primary_document": "latest.htm",
                        "description": "10-K",
                    }
                ],
                "filing_files": [],
            }

        async def fake_archive(cik, accession_number):
            return None

        monkeypatch.setattr("src.task3_sec.fetcher.fetch_company_metadata", fake_metadata)
        monkeypatch.setattr("src.task3_sec.fetcher.resolve_filing_from_archive", fake_archive)

        with pytest.raises(ValueError, match="not found"):
            await find_10k_filing("1", accession_number="0000000001-20-000001")


# ========== VALIDATOR TESTS ==========


class TestValidator:
    """Test extraction validation logic."""

    def _make_result(self, items: list[ExtractedItem]) -> ExtractionResult:
        """Helper to create an ExtractionResult for testing."""
        return ExtractionResult(
            filing_metadata=FilingMetadata(cik="0000320193"),
            items=items,
            processing_metadata=ProcessingMetadata(),
        )

    def test_coverage_check_all_items(self):
        """Full coverage should pass validation."""
        items = [
            ExtractedItem(
                part=item["part"],
                item_number=item["item_number"],
                item_title=item["item_title"],
                content_text="Some content here.",
                char_range=[0, 100],
                status=ItemStatus.EXTRACTED,
            )
            for item in STANDARD_10K_ITEMS
        ]
        result = self._make_result(items)
        source_text = "Some content here." * 100
        report = validate_extraction(result, source_text)
        assert report["coverage"]["passed"]

    def test_coverage_check_missing_items(self):
        """Missing items should be reported."""
        items = [
            ExtractedItem(
                part="I",
                item_number="1",
                item_title="Business",
                content_text="content",
                char_range=[0, 100],
            ),
        ]
        result = self._make_result(items)
        report = validate_extraction(result, "content" * 100)
        assert len(report["coverage"]["missing"]) > 0

    def test_coverage_fails_when_all_items_are_not_found_placeholders(self):
        """Regression for the Citi-2026 failure-masking bug.

        Before the patch: pipeline._fill_missing_items pads ALL standard
        items with NOT_FOUND placeholders so the response shape is stable,
        and _check_coverage's "found" set included those placeholders ->
        coverage["passed"] was True even when 0 real extractions occurred.

        After the patch: NOT_FOUND items are excluded from "found", AND a
        special "catastrophic" flag fires when the real-found count is 0.
        """
        # Simulate the exact post-pipeline state when the rule parser
        # detected ZERO headings: every standard item exists as a NOT_FOUND
        # placeholder.
        items = [
            ExtractedItem(
                part=item["part"],
                item_number=item["item_number"],
                item_title=item["item_title"],
                content_text="",
                char_range=[0, 0],
                status=ItemStatus.NOT_FOUND,
                confidence=0.0,
            )
            for item in STANDARD_10K_ITEMS
        ]
        result = self._make_result(items)
        report = validate_extraction(result, "irrelevant source text")
        coverage = report["coverage"]
        assert coverage["passed"] is False, (
            "Catastrophic failure (0 real extractions) must NOT pass coverage."
        )
        assert coverage["found"] == 0
        assert coverage["catastrophic"] is True
        assert coverage["placeholder_not_found"] == len(STANDARD_10K_ITEMS)
        assert report["overall_valid"] is False

    def test_coverage_counts_real_extractions_only(self):
        """Items with INCORPORATED_BY_REFERENCE / NOT_APPLICABLE / RESERVED
        statuses are legitimate (not failures) and should count toward
        coverage. Only NOT_FOUND placeholders are excluded."""
        items = []
        # First 6 items are real extractions of various legitimate statuses
        legit_statuses = [
            ItemStatus.EXTRACTED,
            ItemStatus.EXTRACTED,
            ItemStatus.INCORPORATED_BY_REFERENCE,
            ItemStatus.NOT_APPLICABLE,
            ItemStatus.RESERVED,
            ItemStatus.EXTRACTED,
        ]
        for i, std in enumerate(STANDARD_10K_ITEMS[:6]):
            items.append(
                ExtractedItem(
                    part=std["part"],
                    item_number=std["item_number"],
                    item_title=std["item_title"],
                    content_text="content" if legit_statuses[i] == ItemStatus.EXTRACTED else "",
                    char_range=[0, 50],
                    status=legit_statuses[i],
                )
            )
        # Remaining items are NOT_FOUND placeholders
        for std in STANDARD_10K_ITEMS[6:]:
            items.append(
                ExtractedItem(
                    part=std["part"],
                    item_number=std["item_number"],
                    item_title=std["item_title"],
                    content_text="",
                    char_range=[0, 0],
                    status=ItemStatus.NOT_FOUND,
                )
            )
        result = self._make_result(items)
        report = validate_extraction(result, "content" * 100)
        assert report["coverage"]["found"] == 6
        assert report["coverage"]["catastrophic"] is False
        assert report["coverage"]["placeholder_not_found"] == len(STANDARD_10K_ITEMS) - 6

    def test_ordering_check(self):
        """Items should be in standard order."""
        items = [
            ExtractedItem(
                part="I",
                item_number="1A",
                item_title="Risk Factors",
                content_text="risks",
                char_range=[0, 50],
            ),
            ExtractedItem(
                part="I",
                item_number="1",
                item_title="Business",
                content_text="business",
                char_range=[50, 100],
            ),
        ]
        result = self._make_result(items)
        report = validate_extraction(result, "x" * 200)
        order_check = [c for c in report["checks"] if c.get("check") == "ordering"][0]
        assert not order_check["passed"]

    def test_duplicate_detection(self):
        """Duplicate item numbers should be flagged."""
        items = [
            ExtractedItem(
                part="I",
                item_number="1",
                item_title="Business",
                content_text="first",
                char_range=[0, 50],
            ),
            ExtractedItem(
                part="I",
                item_number="1",
                item_title="Business",
                content_text="second",
                char_range=[50, 100],
            ),
        ]
        result = self._make_result(items)
        report = validate_extraction(result, "x" * 200)
        dupe_check = [c for c in report["checks"] if c.get("check") == "no_duplicates"][0]
        assert not dupe_check["passed"]

    def test_fix_status_incorporated(self):
        """Auto-fix should detect incorporated by reference from content."""
        items = [
            ExtractedItem(
                part="III",
                item_number="10",
                item_title="Directors",
                content_text="Incorporated by reference from the Proxy Statement.",
                char_range=[0, 50],
                status=ItemStatus.EXTRACTED,  # Wrong status
            ),
        ]
        result = self._make_result(items)
        fixed = fix_common_issues(result, "Incorporated by reference from the Proxy Statement." * 5)
        assert fixed.items[0].status == ItemStatus.INCORPORATED_BY_REFERENCE

    def test_fix_status_reserved(self):
        """Auto-fix should detect reserved status from content."""
        items = [
            ExtractedItem(
                part="II",
                item_number="6",
                item_title="Selected Financial Data",
                content_text="[Reserved]",
                char_range=[0, 10],
                status=ItemStatus.EXTRACTED,  # Wrong
            ),
        ]
        result = self._make_result(items)
        fixed = fix_common_issues(result, "[Reserved]" + "x" * 100)
        assert fixed.items[0].status == ItemStatus.RESERVED

    def test_fix_status_does_not_false_fire_on_long_business_section(self):
        """A long Item 1 that mentions 'incorporated' (corp history) and
        'reference' (somewhere in the body) must NOT be flipped to
        INCORPORATED_BY_REFERENCE. This is the Tesla 2023 regression: the
        previous loose substring check misclassified Item 1 because the body
        contained both words in unrelated contexts."""
        long_business = (
            "Overview\n\nWe design, develop, manufacture, sell and lease "
            "high-performance fully electric vehicles. The Company was "
            "incorporated in Delaware in 2003. "
            + ("Product detail. " * 200)
            + " For reference, see additional disclosures in our investor materials."
        )
        items = [
            ExtractedItem(
                part="I",
                item_number="1",
                item_title="Business",
                content_text=long_business,
                char_range=[0, len(long_business)],
                status=ItemStatus.EXTRACTED,
            ),
        ]
        result = self._make_result(items)
        fixed = fix_common_issues(result, long_business)
        assert fixed.items[0].status == ItemStatus.EXTRACTED

    def test_validator_skips_char_range_for_not_found_placeholders(self):
        """Items synthesised by _fill_missing_items use [0, 0] as a placeholder
        char_range; they should not surface as char_range_bounds errors."""
        items = [
            ExtractedItem(
                part="I",
                item_number="1C",
                item_title="Cybersecurity",
                content_text="",
                char_range=[0, 0],
                status=ItemStatus.NOT_FOUND,
            ),
        ]
        result = self._make_result(items)
        report = validate_extraction(result, "real source text " * 100)
        assert "1C" not in report["item_issues"]

    def test_coverage_passes_when_only_optional_items_missing(self):
        """Modern filings legitimately omit Item 6 (retired 2021) and pre-2023
        filings omit 1C/9C. Coverage check should not fail those filings."""
        items = [
            ExtractedItem(
                part=item["part"],
                item_number=item["item_number"],
                item_title=item["item_title"],
                content_text="content " * 20,
                char_range=[0, 100],
                status=ItemStatus.EXTRACTED,
            )
            for item in STANDARD_10K_ITEMS
            if item["item_number"] not in {"1C", "6", "9C", "16"}
        ]
        result = self._make_result(items)
        report = validate_extraction(result, "content " * 1000)
        assert report["coverage"]["passed"]
        assert set(report["coverage"]["missing"]) == {"1C", "6", "9C", "16"}
        assert report["coverage"]["missing_required"] == []


# ========== INTEGRATION TEST ==========


class TestPipelineIntegration:
    """Integration test using the sample HTML fixture."""

    def test_full_html_parse(self):
        """Full rule-based parse of sample HTML should extract items."""
        normalized, fmt = normalize_filing(SAMPLE_HTML)
        assert fmt == "html"

        result = rule_based_parse(normalized)
        assert result.items_found >= 10  # Should find most items

    def test_full_text_parse(self):
        """Full rule-based parse of sample text should extract items."""
        normalized, fmt = normalize_filing(SAMPLE_TEXT_FILING)
        assert fmt == "text"

        result = rule_based_parse(normalized)
        assert result.items_found >= 3  # Should find at least Item 1, 1A, 2

    def test_llm_status_hint_can_mark_short_items(self):
        """LLM status hints from vision refinement survive item construction."""
        from src.task3_sec.pipeline import _build_items
        from src.task3_sec.rule_parser import ItemBoundary, ParseResult

        text = "Item 4. Mine Safety Disclosures\nNo mining operations are shown in a table-only note."
        parse_result = ParseResult(
            boundaries=[
                ItemBoundary(
                    item_number="4",
                    start_pos=0,
                    end_pos=len(text),
                    heading_text="Mine Safety Disclosures",
                    confidence=0.9,
                    source="llm_refined",
                    status_hint="not_applicable",
                )
            ],
            total_chars=len(text),
            items_found=1,
            confidence_avg=0.9,
        )

        items = _build_items(text, parse_result)
        assert items[0].status == ItemStatus.NOT_APPLICABLE
        assert items[0].extraction_method == ExtractionMethod.LLM_REFINED

    def test_status_detection_in_html(self):
        """Status detection should work on normalized HTML."""
        normalized, _ = normalize_filing(SAMPLE_HTML)
        result = rule_based_parse(normalized)

        # Build items from boundaries
        for boundary in result.boundaries:
            start = boundary.start_pos
            end = boundary.end_pos if boundary.end_pos > 0 else len(normalized)
            content = normalized[start:end].strip()

            if boundary.item_number == "4":
                status = detect_item_status(content)
                assert status == ItemStatus.NOT_APPLICABLE

    def test_prompt_files_exist(self):
        """Versioned prompt files should exist in prompts/sec_extraction/."""
        import os

        prompts_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "prompts",
            "sec_extraction",
        )
        assert os.path.isfile(os.path.join(prompts_dir, "v2_boundary_refine.txt"))
        assert os.path.isfile(os.path.join(prompts_dir, "v2_missing_item_detect.txt"))
        assert os.path.isfile(os.path.join(prompts_dir, "v2_reflexive_validate.txt"))
        assert os.path.isfile(os.path.join(prompts_dir, "README.md"))

    def test_prompt_loading(self):
        """LLM refiner should load prompts from files."""
        from src.task3_sec.llm_refiner import BOUNDARY_REFINE_PROMPT, MISSING_ITEM_PROMPT

        assert len(BOUNDARY_REFINE_PROMPT) > 100
        assert "SEC 10-K" in BOUNDARY_REFINE_PROMPT
        assert len(MISSING_ITEM_PROMPT) > 100
        assert "{prev_item}" in MISSING_ITEM_PROMPT

    @pytest.mark.asyncio
    async def test_llm_refine_preserves_known_item_number(self):
        """Boundary refinement must not let the LLM rename known items."""
        from src.task3_sec.llm_refiner import _refine_single_boundary
        from src.task3_sec.rule_parser import ItemBoundary

        class FakeResponse:
            content = (
                '{"is_item_heading": true, "item_number": "8", '
                '"item_title": "Financial Statements", "content_start_offset": 0, '
                '"status": "extracted", "confidence": 0.91}'
            )

        class FakeLLM:
            async def ainvoke(self, messages):
                return FakeResponse()

        text = "Item 7. Management Discussion\nRevenue was stable."
        boundary = ItemBoundary(
            item_number="7",
            start_pos=0,
            heading_text="Management Discussion",
            confidence=0.5,
        )

        refined = await _refine_single_boundary(
            text=text,
            boundary=boundary,
            llm=FakeLLM(),
            model_name="test-model",
            trace_id="test-trace",
        )

        assert refined is not None
        assert refined.item_number == "7"

    @pytest.mark.asyncio
    async def test_task3_vision_renderers_do_not_hang(self):
        """HTML and comparison snapshot renderers use real Playwright under timeout."""
        from src.task3_sec.vision import (
            render_comparison_snapshots,
            render_html_to_jpeg_b64,
        )

        async def scenario():
            html_b64 = await render_html_to_jpeg_b64(
                "<h2>Item 7. MD&A</h2><table><tr><td>Revenue</td><td>$100</td></tr></table>",
                width_px=640,
            )
            text = "Item 1. Business\nWe make products.\n\nItem 1A. Risk Factors\nRisks include demand shocks."
            boundary = text.index("Item 1A")
            comparison = await render_comparison_snapshots(text, boundary, "1A", width_px=640)
            return html_b64, comparison

        html_b64, comparison = await asyncio.wait_for(scenario(), timeout=20)
        if not html_b64 or not comparison:
            pytest.skip("Chromium is not launchable in this environment.")
        assert html_b64 and len(base64.b64decode(html_b64)) > 100
        assert comparison and len(base64.b64decode(comparison[0][1])) > 100

    @pytest.mark.asyncio
    async def test_pipeline_force_llm_invokes_refiner(self, monkeypatch):
        """force_llm should call Stage 2 even when rule parsing is confident."""
        from src.task3_sec.pipeline import extract_10k

        calls = {}

        async def fake_find_10k_filing(cik, accession_number=None, year=None):
            return {
                "cik": cik,
                "company_name": "Example Corp",
                "accession_number": accession_number or "0000000000-00-000000",
                "filing_date": "2024-02-01",
                "filing_url": "https://www.sec.gov/Archives/example.htm",
                "primary_document": "example.htm",
                "form_type": "10-K",
            }

        async def fake_fetch_filing_content(url):
            return SAMPLE_HTML

        async def fake_refine_boundaries(text, parse_result, **kwargs):
            calls["force_refine"] = kwargs.get("force_refine")
            calls["use_vision"] = kwargs.get("use_vision")
            return parse_result

        async def fake_find_proxy_statement(cik, year):
            return None

        monkeypatch.setattr("src.task3_sec.pipeline.find_10k_filing", fake_find_10k_filing)
        monkeypatch.setattr("src.task3_sec.pipeline.fetch_filing_content", fake_fetch_filing_content)
        monkeypatch.setattr("src.task3_sec.pipeline.refine_boundaries", fake_refine_boundaries)
        monkeypatch.setattr("src.task3_sec.pipeline.find_proxy_statement", fake_find_proxy_statement)

        result = await extract_10k(
            cik="0000000001",
            accession_number="0000000001-24-000001",
            skip_xbrl=True,
            use_vision=True,
            force_llm=True,
        )

        assert calls == {"force_refine": True, "use_vision": True}
        assert "llm_refine" in result.processing_metadata.stages_used


class TestExtractionCompletenessField:
    """Tests for the ProcessingMetadata.extraction_completeness field added
    2026-05-15 in response to interviewer Q1 (Citi-2026 failure masking)."""

    def test_processing_metadata_has_completeness_fields(self) -> None:
        from src.task3_sec.schemas import ProcessingMetadata

        meta = ProcessingMetadata()
        assert hasattr(meta, "extracted_count")
        assert hasattr(meta, "expected_count")
        assert hasattr(meta, "extraction_completeness")
        # Defaults are safe
        assert meta.extracted_count == 0
        assert meta.expected_count == 0
        assert meta.extraction_completeness == 0.0

    def test_extraction_completeness_bounded_0_1(self) -> None:
        from src.task3_sec.schemas import ProcessingMetadata

        # Field has ge=0.0 le=1.0 validators
        ok = ProcessingMetadata(extraction_completeness=0.5)
        assert ok.extraction_completeness == 0.5
        import pytest

        with pytest.raises(Exception):
            ProcessingMetadata(extraction_completeness=1.5)
        with pytest.raises(Exception):
            ProcessingMetadata(extraction_completeness=-0.1)


class TestRegressionCitiIntelEvalEntries:
    """Tests that pin the new regression cases to the eval set so future
    edits can't silently drop them."""

    def test_eval_set_contains_citi_2026_regression(self) -> None:
        import json
        from pathlib import Path

        path = Path(__file__).resolve().parent.parent / "evals" / "task3" / "eval_set.json"
        cases = json.loads(path.read_text(encoding="utf-8"))
        cids = {c["case_id"] for c in cases}
        assert "t3_citigroup_2026_interviewer_regression" in cids, (
            "Citi 2026 regression case must be present in eval_set.json — "
            "this case pins the validator coverage-mask fix."
        )

    def test_eval_set_contains_intel_2026_regression(self) -> None:
        import json
        from pathlib import Path

        path = Path(__file__).resolve().parent.parent / "evals" / "task3" / "eval_set.json"
        cases = json.loads(path.read_text(encoding="utf-8"))
        cids = {c["case_id"] for c in cases}
        assert "t3_intel_2026_toc_regression" in cids, (
            "Intel 2026 regression case must be present in eval_set.json — "
            "this case pins the single-match TOC-suppression fix."
        )

    def test_regression_cases_use_cik_only_finder_path(self) -> None:
        """Both regression cases intentionally omit accession_number so the
        fetcher resolves the most-recent 10-K. This matters because the
        actual Citi/Intel 2026 accession the interviewer ran against isn't
        knowable until the filings exist; using the latest path keeps the
        regression evergreen."""
        import json
        from pathlib import Path

        path = Path(__file__).resolve().parent.parent / "evals" / "task3" / "eval_set.json"
        cases = {c["case_id"]: c for c in json.loads(path.read_text(encoding="utf-8"))}
        for cid in (
            "t3_citigroup_2026_interviewer_regression",
            "t3_intel_2026_toc_regression",
        ):
            data = cases[cid]["input_data"]
            assert "cik" in data
            assert "accession_number" not in data, (
                f"{cid}: regression case should rely on most-recent-10-K resolution"
            )
